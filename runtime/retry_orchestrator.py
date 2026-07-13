"""Retry orchestrator — handles EVALUATION_RETRY with RetryEngine.

Arbiter decides. RetryEngine controls. Orchestrator executes.
No component recomputes what another already decided.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from runtime.paths import get_job_paths
from runtime.models import (
    check_architecture_supported,
    classify_exception,
    load_mission_state,
    load_mission_state_from_redis,
    save_mission_state,
    save_mission_state_to_redis,
    mission_state_path,
)
from contracts import (
    MissionState,
    RetryPlan,
    RetryAttemptRecord,
    FailureReport,
    ScoutIntelligence,
)
from runtime.retry_engine import RetryEngine
from runtime.retry_log import (
    create_retry_log,
    update_retry_log_status,
)
from runtime.ui_retry import (
    show_retry_complete,
    show_retry_history,
    show_retry_limit_reached,
    show_retry_reason,
    show_retry_started,
)
from prometheus.cli.mission.state_logger import log_mission_state

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 4


async def handle_evaluation_retry(
    job_id: str,
    redis_client,
    renderer,
    brief: dict[str, Any] | None = None,
    previous_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = await load_mission_state_from_redis(redis_client, job_id)

    last_arch = brief.get("recommended_architecture_family") if brief else "lightgbm"
    last_arch = last_arch or "lightgbm"
    prev_metric_name = "auc_roc"
    prev_metric_value = 0.0
    deployment_threshold = None

    if previous_result:
        prev_metric_name = previous_result.get("metric_name", prev_metric_name)
        prev_metric_value = previous_result.get("metric_value", prev_metric_value)
        deployment_threshold = previous_result.get("threshold")

    if state is None:
        state = MissionState(
            job_id=job_id,
            architecture=last_arch,
            phase="RETRY_PENDING",
        )
        if deployment_threshold is not None:
            state.deployment_threshold = deployment_threshold
    else:
        if deployment_threshold is None:
            deployment_threshold = state.deployment_threshold
        state.transition_to("RETRY_PENDING")

    state.transition_to("RETRY_RUNNING")
    state.metric_name = prev_metric_name
    state.metric_value = prev_metric_value
    if deployment_threshold is not None:
        state.deployment_threshold = deployment_threshold
    await save_mission_state_to_redis(redis_client, state)
    save_mission_state(state)

    log_mission_state(
        "RETRY_ORCHESTRATOR_START",
        job_id,
        retry_number=state.retry_number,
        architecture=state.architecture,
        metric_name=state.metric_name,
        metric_value=state.metric_value,
        deployment_threshold=state.deployment_threshold,
        phase=state.phase,
    )

    # ── Build ScoutIntelligence from mission data ────────────────────
    spec_key = f"job:{job_id}:mission_spec"
    spec_raw = await redis_client.get(spec_key)
    spec = json.loads(spec_raw) if spec_raw else None
    scout_intel = ScoutIntelligence.from_mission_data(brief, spec)

    engine = RetryEngine(
        job_id=job_id,
        max_attempts=MAX_RETRY_ATTEMPTS,
        metric_name=prev_metric_name,
        metric_value=prev_metric_value,
        architecture=last_arch,
        deployment_threshold=deployment_threshold,
        scout_intelligence=scout_intel,
    )

    while True:
        if not engine.has_retries_remaining:
            break

        attempt = engine.next_attempt_number
        strategy = engine.generate_strategy(
            previous_metric_value=prev_metric_value,
            previous_metric_name=prev_metric_name,
        )
        _validate_retry_contract(strategy, "RetryEngine.generate_strategy")

        logger.debug(
            f"[job={job_id}] RetryPlan created: "
            f"type={type(strategy).__name__}, "
            f"architecture={strategy.architecture}, "
            f"attempt={strategy.attempt}"
        )

        try:
            check_architecture_supported(strategy.architecture)
        except ValueError as e:
            logger.error(f"[job={job_id}] Retry proposed unsupported arch: {e}")
            renderer.print(f"  [red]Retry failed: {e}[/]")
            break

        show_retry_reason(
            renderer,
            strategy.rationale,
            strategy.previous_metric_name,
            strategy.previous_metric_value,
            state.deployment_threshold,
        )
        show_retry_started(renderer, attempt, engine.max_attempts, strategy.rationale)

        log_mission_state(
            "RETRY_STRATEGY_DECIDED",
            job_id,
            retry_number=attempt,
            architecture=strategy.architecture,
            imbalance_strategy=strategy.imbalance_strategy,
            metric_name=strategy.previous_metric_name,
            metric_value=strategy.previous_metric_value,
            deployment_threshold=state.deployment_threshold,
            rationale=strategy.rationale,
            optuna_trials=strategy.num_trials,
        )

        updated_brief = _apply_strategy_to_brief(brief, strategy)
        await _persist_retry_plan(redis_client, job_id, strategy)
        state.architecture = strategy.architecture
        state.imbalance_strategy = strategy.imbalance_strategy
        state.optuna_trials = strategy.num_trials
        state.add_timeline("RetryOrchestrator", f"Retry {attempt}: {strategy.rationale}")
        await save_mission_state_to_redis(redis_client, state)
        save_mission_state(state)

        jp = get_job_paths(job_id)
        output_dir = str(jp.retry_dir(attempt))
        os.makedirs(output_dir, exist_ok=True)
        script_path = str(jp.script_path)
        search_space_raw = await redis_client.get(f"job:{job_id}:search_space")
        search_space_json = (
            search_space_raw
            if isinstance(search_space_raw, str)
            else (json.dumps(search_space_raw) if search_space_raw else None)
        )

        from contracts import TrainingPlan

        training_job = TrainingPlan(
            job_id=job_id,
            retry_attempt=attempt,
            architecture=strategy.architecture,
            imbalance_strategy=strategy.imbalance_strategy,
            optuna_trials=strategy.num_trials,
            feature_engineering_level=strategy.feature_engineering_level,
            script_path=script_path,
            output_dir=output_dir,
            search_space_json=search_space_json,
            metric_name=state.metric_name or "auc_roc",
            deployment_threshold=state.deployment_threshold,
        )

        try:
            training_job.script_path
            if not os.path.exists(training_job.script_path):
                raise FileNotFoundError(f"Training script not found: {training_job.script_path}")
            check_architecture_supported(training_job.architecture)
            if training_job.optuna_trials < 1:
                raise ValueError(f"optuna_trials must be >= 1, got {training_job.optuna_trials}")
            valid_imbalance = ("none", "class_weight", "smote", "focal_loss")
            if training_job.imbalance_strategy not in valid_imbalance:
                raise ValueError(
                    f"Unknown imbalance strategy '{training_job.imbalance_strategy}'. Valid: {valid_imbalance}"
                )
            valid_fe = ("none", "basic", "interaction", "advanced")
            if training_job.feature_engineering_level not in valid_fe:
                raise ValueError(
                    f"Unknown feature_engineering_level '{training_job.feature_engineering_level}'. Valid: {valid_fe}"
                )
            os.makedirs(training_job.output_dir, exist_ok=True)
            renderer.print(f"  [green]TrainingPlan validated — output: {output_dir}[/]")
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"[job={job_id}] TrainingPlan validation failed: {e}")
            renderer.print(f"  [red]TrainingPlan validation failed: {e}[/]")
            state.record_failure(
                FailureReport(
                    phase="FURNACE_RUNNING",
                    exception_type=type(e).__name__,
                    exception_message=str(e),
                    retryable=False,
                )
            )
            await save_mission_state_to_redis(redis_client, state)
            save_mission_state(state)
            break

        create_retry_log(
            output_dir=output_dir,
            job_id=job_id,
            retry_attempt=attempt,
            architecture=strategy.architecture,
            imbalance_strategy=strategy.imbalance_strategy,
            optuna_trials=strategy.num_trials,
            feature_engineering_level=strategy.feature_engineering_level,
            metric_name=training_job.metric_name,
            deployment_threshold=training_job.deployment_threshold,
        )

        forge_ok = await _run_forge_with_retry(
            job_id,
            redis_client,
            renderer,
            strategy,
            updated_brief,
        )
        if not forge_ok:
            logger.error(f"[job={job_id}] Forge failed on retry {attempt}")
            update_retry_log_status(output_dir, "forge_failed", attempt=attempt)
            state.record_failure(
                FailureReport(
                    phase="FORGE_RUNNING",
                    exception_type="ForgeFailed",
                    exception_message=f"Forge failed on retry attempt {attempt}",
                    retryable=False,
                )
            )
            await save_mission_state_to_redis(redis_client, state)
            save_mission_state(state)
            break

        update_retry_log_status(output_dir, "forge_complete", attempt=attempt)

        last_checkpoint_path = str(jp.checkpoint_path) if _checkpoint_exists(job_id) else None
        furnace_ok = await _run_furnace_with_retry(
            job_id,
            redis_client,
            renderer,
            output_dir=output_dir,
            resume_from=last_checkpoint_path,
            retry_log_output_dir=output_dir,
        )
        if not furnace_ok:
            logger.error(f"[job={job_id}] Furnace failed on retry {attempt}")
            crash_entry = RetryAttemptRecord(
                attempt=attempt,
                architecture=strategy.architecture,
                metric_value=state.metric_value,
                metric_name=state.metric_name,
                decision="FAIL",
                rationale=f"Furnace crash — {strategy.rationale}",
            )
            try:
                last_crash_raw = await redis_client.get(f"job:{job_id}:last_crash")
                if last_crash_raw:
                    lc = json.loads(last_crash_raw)
                    if isinstance(lc, dict):
                        crash_entry.failure_category = lc.get("category", "training_exception")
                        update_retry_log_status(
                            output_dir,
                            "crash_occurred",
                            exception_type=lc.get("exception_type", "RuntimeError"),
                            exception_message=lc.get("exception_message", ""),
                            category=lc.get("category", "training_exception"),
                            epoch_at_crash=lc.get("epoch_at_crash", 0),
                            crash_attempt_number=lc.get("crash_attempt_number", 1),
                        )
            except Exception:
                pass
            engine.record_attempt(crash_entry)
            state.record_retry_attempt(crash_entry)
            state.architecture = strategy.architecture
            state.imbalance_strategy = strategy.imbalance_strategy
            state.optuna_trials = strategy.num_trials
            state.tried_architectures = list(
                set(state.tried_architectures) | {strategy.architecture}
            )
            engine.save_history()
            await save_mission_state_to_redis(redis_client, state)
            save_mission_state(state)
            if engine.is_exhausted:
                break
            continue

        update_retry_log_status(output_dir, "furnace_complete", attempt=attempt)

        arbiter_result = await _run_arbiter_with_retry(
            job_id,
            redis_client,
            renderer,
            output_dir=output_dir,
        )
        if not arbiter_result:
            logger.error(f"[job={job_id}] Arbiter failed on retry {attempt}")
            update_retry_log_status(output_dir, "arbiter_failed", attempt=attempt)
            state.record_failure(
                FailureReport(
                    phase="ARBITER_RUNNING",
                    exception_type="ArbiterFailed",
                    exception_message=f"Arbiter failed on retry attempt {attempt}",
                    retryable=False,
                )
            )
            await save_mission_state_to_redis(redis_client, state)
            save_mission_state(state)
            break

        decision = arbiter_result.get("decision", "FAIL")
        metric_val = arbiter_result.get("metric_value", 0.0)
        metric_name = arbiter_result.get("metric_name", "auc_roc")

        entry = RetryAttemptRecord(
            attempt=attempt,
            architecture=strategy.architecture,
            metric_value=metric_val,
            metric_name=metric_name,
            decision=decision,
            rationale=strategy.rationale,
            checkpoint_path=f"{output_dir}/checkpoints/best.ckpt",
        )
        engine.record_attempt(entry)
        engine.save_history()
        state.record_retry_attempt(entry)
        state.architecture = strategy.architecture
        state.imbalance_strategy = strategy.imbalance_strategy
        state.optuna_trials = strategy.num_trials
        state.tried_architectures = list(set(state.tried_architectures) | {strategy.architecture})
        state.best_metric = max(state.best_metric, metric_val)
        state.best_architecture = strategy.architecture
        await save_mission_state_to_redis(redis_client, state)
        save_mission_state(state)

        update_retry_log_status(
            output_dir,
            "eval_complete",
            decision=decision,
            metric_name=metric_name,
            metric_value=metric_val,
        )

        log_mission_state(
            "RETRY_ATTEMPT_RESULT",
            job_id,
            retry_number=attempt,
            architecture=strategy.architecture,
            imbalance_strategy=strategy.imbalance_strategy,
            metric_name=metric_name,
            metric_value=metric_val,
            deployment_threshold=state.deployment_threshold,
            decision=decision,
            rationale=strategy.rationale,
        )

        show_retry_complete(renderer, attempt, metric_name, metric_val, decision)

        if engine.should_terminate(decision):
            if decision == "PASS":
                state.transition_to("MISSION_PASSED")
                await save_mission_state_to_redis(redis_client, state)
                save_mission_state(state)
                update_retry_log_status(output_dir, "mission_passed", final_metric=metric_val)
                show_retry_history(
                    renderer,
                    engine.retry_history,
                    engine.best_architecture,
                    engine.best_metric,
                    engine.best_architecture,
                )
                logger.info(
                    f"[job={job_id}] Retry {attempt} achieved PASS — "
                    f"{metric_name}={metric_val:.4f}"
                )
                return {
                    "decision": "PASS",
                    "explanation": f"Retry {attempt} achieved PASS with "
                    f"{metric_name}={metric_val:.4f}",
                    "metric_value": metric_val,
                    "metric_name": metric_name,
                    "threshold": state.deployment_threshold,
                    "attempt_number": attempt,
                    "retry_state_path": mission_state_path(job_id),
                    "output_dir": output_dir,
                }
            break

    threshold = state.deployment_threshold

    show_retry_history(
        renderer,
        engine.retry_history,
        engine.best_architecture,
        engine.best_metric,
        engine.best_architecture,
    )
    show_retry_limit_reached(
        renderer,
        engine.current_attempt,
        engine.max_attempts,
        state.metric_name,
        state.metric_value,
        threshold,
    )

    state.transition_to("MISSION_FAILED")
    await save_mission_state_to_redis(redis_client, state)
    save_mission_state(state)

    try:
        update_retry_log_status(
            output_dir,
            "mission_failed",
            best_metric=engine.best_metric,
            best_architecture=engine.best_architecture,
            retry_number=engine.current_attempt,
            max_retries=engine.max_attempts,
        )
    except Exception:
        pass

    logger.info(
        f"[job={job_id}] Retry limit reached. "
        f"Best {state.metric_name}={engine.best_metric:.4f} "
        f"with {engine.best_architecture}"
    )

    return {
        "decision": "FAIL",
        "explanation": (
            f"Retry limit ({engine.max_attempts}) reached. "
            f"Best {state.metric_name}={engine.best_metric:.4f} "
            f"(threshold: {threshold})"
        ),
        "metric_value": state.metric_value,
        "metric_name": state.metric_name,
        "threshold": threshold,
        "attempt_number": engine.current_attempt,
        "retry_state_path": mission_state_path(job_id),
    }


def _apply_strategy_to_brief(
    brief: dict[str, Any] | None,
    strategy: RetryPlan,
) -> dict[str, Any] | None:
    if brief is None:
        return None
    updated = dict(brief)
    updated["recommended_architecture_family"] = strategy.architecture
    updated["imbalance_strategy"] = strategy.imbalance_strategy
    updated["optuna_trials"] = strategy.num_trials
    return updated


async def _persist_retry_plan(
    redis_client,
    job_id: str,
    strategy: RetryPlan,
) -> None:
    plan_key = f"job:{job_id}:retry_plan"
    await redis_client.set(plan_key, json.dumps(strategy.model_dump()))
    await redis_client.set(f"job:{job_id}:retry_architecture", strategy.architecture)
    await redis_client.set(f"job:{job_id}:retry_imbalance", strategy.imbalance_strategy)


def _validate_retry_contract(
    strategy: Any,
    stage: str,
) -> None:
    if isinstance(strategy, dict):
        raise TypeError(
            f"Contract violation at {stage}: expected RetryPlan, got dict. "
            f"Keys: {list(strategy.keys())}. "
            f"Use RetryPlan.from_dict() to reconstruct."
        )
    if not isinstance(strategy, RetryPlan):
        raise TypeError(
            f"Contract violation at {stage}: expected RetryPlan or None, "
            f"got {type(strategy).__name__}."
        )


async def _run_forge_with_retry(
    job_id: str,
    redis_client,
    renderer,
    strategy: RetryPlan,
    updated_brief: dict[str, Any] | None,
) -> bool:
    _validate_retry_contract(strategy, "_run_forge_with_retry")
    from agents.forge.agent import ForgeAgent
    from prometheus.cli.mission.ui import show_forge_progress, show_forge_summary

    logger.info(f"[job={job_id}] Retry: launching Forge with {strategy.architecture}")
    logger.debug(
        f"[job={job_id}] RetryPlan lifecycle: "
        f"type={type(strategy).__name__}, "
        f"architecture={strategy.architecture}, "
        f"attempt={strategy.attempt}, "
        f"imbalance_strategy={strategy.imbalance_strategy}, "
        f"optuna_trials={strategy.num_trials}"
    )
    renderer.print()
    renderer.print("  [bold cyan]Retry Forge: Executing RetryPlan...[/]")
    renderer.print()

    agent = ForgeAgent(job_id=job_id)
    agent.redis._client = redis_client

    await _persist_retry_plan(redis_client, job_id, strategy)

    retry_brief_key = f"job:{job_id}:retry_brief"
    if updated_brief:
        await redis_client.set(retry_brief_key, json.dumps(updated_brief))

    def progress(msg: str) -> None:
        show_forge_progress(renderer, msg)

    try:
        await agent.run(
            progress_callback=progress,
            retry_context=strategy,
        )
        search_space_raw = await redis_client.get(f"job:{job_id}:search_space")
        search_space = json.loads(search_space_raw) if search_space_raw else {}
        show_forge_summary(
            renderer,
            job_id,
            {
                "brief": updated_brief,
                "script_path": str(get_job_paths(job_id).script_path),
                "search_space": search_space,
            },
        )
        return True
    except Exception as e:
        logger.error(f"[job={job_id}] Forge retry failed: {e}")
        renderer.print(f"  [red]Forge retry failed: {e}[/]")
        return False
    finally:
        agent.redis._client = None


def _checkpoint_exists(job_id: str) -> bool:
    return os.path.exists(str(get_job_paths(job_id).checkpoint_path))


async def _run_furnace_with_retry(
    job_id: str,
    redis_client,
    renderer,
    output_dir: str = "",
    resume_from: str | None = None,
    retry_log_output_dir: str = "",
) -> bool:
    from agents.furnace.agent import FurnaceAgent
    from agents.dissect.agent import DissectAgent
    from memory.redis_client import RedisClient
    from prometheus.cli.mission.ui import (
        show_furnace_error,
        show_furnace_progress,
        show_furnace_summary as sfs,
    )
    from runtime.retry_log import update_retry_log_status as _log_status

    script_path = str(get_job_paths(job_id).script_path)

    def progress(msg: str) -> None:
        show_furnace_progress(renderer, msg)

    max_crash_cycles = 3
    last_crash: dict[str, Any] | None = None
    log_dir = retry_log_output_dir or output_dir

    for cycle in range(max_crash_cycles):
        logger.info(
            f"[job={job_id}] Retry: launching Furnace (crash cycle {cycle + 1}/{max_crash_cycles})"
        )
        if cycle == 0:
            renderer.print()
            renderer.print("  [bold cyan]Retry Furnace: Training with updated strategy...[/]")
            renderer.print()

        try:
            await redis_client.delete(f"job:{job_id}:last_crash")
            search_space_raw = await redis_client.get(f"job:{job_id}:search_space")
            search_space_json = (
                search_space_raw
                if isinstance(search_space_raw, str)
                else (json.dumps(search_space_raw) if search_space_raw else None)
            )

            agent: FurnaceAgent | None = None
            try:
                agent = FurnaceAgent(job_id=job_id)
                agent.redis._client = redis_client

                ckpt = (
                    resume_from
                    if cycle == 0
                    else (last_crash.get("last_checkpoint_path") if last_crash else None)
                )

                await agent.run(
                    script_path=script_path,
                    use_docker=True,
                    progress_callback=progress,
                    wait_for_dissect=False,
                    resume_from=ckpt,
                    search_space_json=search_space_json,
                    output_dir_override=output_dir or None,
                )
            finally:
                if agent is not None:
                    agent.redis._client = None

            last_crash_raw = await redis_client.get(f"job:{job_id}:last_crash")
            last_crash = json.loads(last_crash_raw) if last_crash_raw else None

            if not last_crash:
                import time

                _log_status(log_dir, "training_complete", cycle=cycle + 1)
                assert agent is not None
                sfs(
                    renderer,
                    job_id,
                    {
                        "brief": None,
                        "script_path": script_path,
                        "best_metric": agent._best_val_metric,
                        "metric_name": agent._guess_metric_name(),
                        "total_epochs": agent._epoch_count,
                        "total_trials": agent._total_trials,
                        "training_time": (
                            time.time() - agent._start_time if agent._start_time else 0
                        ),
                        "checkpoint_path": (
                            f"{output_dir}/checkpoints/best.ckpt"
                            if output_dir
                            else str(get_job_paths(job_id).checkpoint_path)
                        ),
                        "last_crash": None,
                    },
                )
                return True

            category = last_crash.get("category", "training_exception")
            exc_type = last_crash.get("exception_type", "RuntimeError")
            exc_msg = last_crash.get("exception_message", "")[:200]
            epoch_at_crash = last_crash.get("epoch_at_crash", 0)
            crash_attempt = last_crash.get("crash_attempt_number", 1)

            logger.error(
                f"[job={job_id}] Furnace crash cycle {cycle + 1}: "
                f"[{category}] {exc_type}: {exc_msg}"
            )

            _log_status(
                log_dir,
                "crash_occurred",
                cycle=cycle + 1,
                exception_type=exc_type,
                exception_message=exc_msg,
                category=category,
                epoch_at_crash=epoch_at_crash,
                crash_attempt_number=crash_attempt,
            )

            if cycle == max_crash_cycles - 1:
                renderer.print("\n  [red]All crash repair cycles exhausted — failing.[/]\n")
                show_furnace_error(
                    renderer,
                    job_id,
                    (f"Crash Category: {category}\n" f"Exception: {exc_type}: {exc_msg}"),
                    wait_for_dissect=True,
                )
                return False

            renderer.print(
                f"\n  [yellow]Crash detected (cycle {cycle + 1}/{max_crash_cycles}) — launching Dissect repair...[/]\n"
            )
            logger.info(f"[job={job_id}] Launching Dissect for crash cycle {cycle + 1}")

            dissect = DissectAgent(job_id=job_id)
            dissect.redis = RedisClient()
            dissect.redis._client = redis_client

            await dissect.handle_crash(last_crash)

            logger.info(f"[job={job_id}] Dissect repair done — re-running Furnace")
            renderer.print("  [green]Dissect repair complete — re-running Furnace...[/]\n")

        except Exception as e:
            logger.error(f"[job={job_id}] Furnace retry crash cycle {cycle + 1} failed: {e}")
            _log_status(
                log_dir,
                "furnace_exception",
                cycle=cycle + 1,
                exception_type=type(e).__name__,
                exception_message=str(e)[:200],
            )
            if cycle == max_crash_cycles - 1:
                renderer.print(
                    f"  [red]Furnace retry failed after {max_crash_cycles} cycles: {e}[/]"
                )
                return False
            renderer.print(
                f"  [yellow]Furnace retry error (cycle {cycle + 1}/{max_crash_cycles}): {e} — retrying...[/]"
            )

    return False


async def _run_arbiter_with_retry(
    job_id: str,
    redis_client,
    renderer,
    output_dir: str = "",
) -> dict[str, Any] | None:
    from agents.arbiter.controller import run_evaluation

    logger.info(f"[job={job_id}] Retry: launching Arbiter")
    renderer.print()
    renderer.print("  [bold cyan]Retry Arbiter: Evaluating retry attempt...[/]")
    renderer.print()

    try:
        checkpoint_dir = os.path.join(output_dir, "checkpoints") if output_dir else None
        result = await run_evaluation(
            job_id=job_id,
            redis_client=redis_client,
            renderer=renderer,
            checkpoint_dir=checkpoint_dir,
        )
        return result
    except Exception as e:
        logger.error(f"[job={job_id}] Arbiter retry failed: {e}")
        renderer.print(f"  [red]Arbiter retry failed: {e}[/]")
        return None

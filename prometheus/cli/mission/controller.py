from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from rich.console import Console

from runtime.paths import get_job_paths
from prometheus.cli.mission.session import (
    MissionSession,
    SessionStatus,
    get_session,
    reset_session,
)
from prometheus.cli.mission.ui import (
    build_first_prompt,
    build_next_prompt,
    show_cancelled,
    show_empty_input_warning,
    show_forge_error,
    show_forge_progress,
    show_forge_summary,
    show_furnace_error,
    show_furnace_progress,
    show_furnace_summary,
    show_mission_banner,
    show_mission_job_id,
    show_parsed_summary,
    show_parsing_error,
    show_scout_error,
    show_scout_progress,
    show_scout_summary,
    show_validation_result,
    show_waiting_message,
)
from agents.dissect.ui import (
    show_dissect_crash_received,
    show_dissect_classification,
    show_dissect_cascade_level,
    show_dissect_patch_applied,
    show_dissect_sandbox_result,
    show_dissect_summary,
    show_dissect_success,
    show_dissect_escalated,
    show_dissect_progress,
    show_dissect_waiting_furnace,
)
from prometheus.cli.mission.ui_harbor import (
    show_harbor_progress,
    show_harbor_summary,
    show_harbor_error,
    show_mission_summary,
    get_api_cost_summary_from_redis,
)
from prometheus.cli.mission.state_logger import log_mission_state, log_event_flow
from prometheus.ui.console import console as _global_console

logger = logging.getLogger(__name__)


def enter_mission_mode(console: Console | None = None) -> None:
    if console is None:
        console = _global_console

    session = get_session()
    session.status = SessionStatus.COLLECTING_DESCRIPTION
    session.created_at = datetime.now(timezone.utc)

    show_mission_banner(console)
    logger.info("Mission Started")

    try:
        description = _collect_input(console)
        if description is None:
            _exit_mission(session, console)
            logger.info("Mission Cancelled")
            return

        if not description.strip():
            show_empty_input_warning(console)
            session.status = SessionStatus.COMPLETED
            return

        session.mission_text = description
        logger.info("Mission Description Collected")

        parsed = _process_mission(console, session)

        if parsed is not None:
            if not _run_scout(console, session, parsed):
                return
            if not _run_forge(console, session):
                return
            if not _run_furnace(console, session):
                return
            result = _run_arbiter(console, session)
            # ── Handle decision ─────────────────────────────────────────
            if result and result.get("decision") == "PASS":
                _run_harbor(console, session, result)
            elif result and result.get("decision") == "RETRY":
                asyncio.run(_async_handle_retry(console, session, result))

    except Exception:
        _exit_mission(session, console)
        logger.exception("Mission Exited (unexpected error)")
        raise


def _collect_input(console: Console) -> str | None:
    lines: list[str] = []
    while True:
        try:
            p = build_first_prompt() if not lines else build_next_prompt()
            line = console.input(p)
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        stripped = line.strip()

        if stripped.lower() == "cancel":
            return None

        if not stripped:
            if not lines:
                show_empty_input_warning(console)
                continue
            break

        lines.append(stripped)

    return "\n".join(lines)


def _process_mission(
    console: Console,
    session: MissionSession,
) -> Any | None:
    description = session.mission_text

    show_waiting_message(console, "Interpreting your mission")

    parsed = _parse_mission(description)

    if parsed.warnings and any("Could not fully parse" in w for w in parsed.warnings):
        show_parsing_error(console)
        session.status = SessionStatus.COMPLETED
        return None

    session.mission_text = description
    show_parsed_summary(console, parsed)

    show_waiting_message(console, "Validating")

    result = _validate_mission(parsed)

    has_errors = not result.valid
    show_validation_result(console, result)

    if has_errors:
        session.status = SessionStatus.COMPLETED
        logger.info("Mission validation failed — aborting")
        return None

    return parsed


def _run_scout(
    console: Console,
    session: MissionSession,
    parsed: Any,
) -> bool:
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    session.job_id = job_id

    show_mission_job_id(console, job_id)
    logger.info(f"Mission ID: {job_id}")

    log_mission_state(
        "MISSION_CREATED", job_id, brief=parsed.__dict__ if hasattr(parsed, "__dict__") else None
    )

    try:
        brief = asyncio.run(_async_scout(console, parsed, job_id))
        show_scout_summary(console, brief, job_id)
        console.print()
        console.print("  [bold]Scout complete. Mission ready for Forge.[/]")
        console.print()
        logger.info(f"[job={job_id}] Scout complete — brief written, event published")
        return True
    except FileNotFoundError as e:
        show_scout_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Scout failed: {e}")
    except ValueError as e:
        show_scout_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Scout failed: {e}")
    except Exception as e:
        show_scout_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Scout failed unexpectedly")

    logger.info(f"[job={job_id}] Scout complete — ready for Forge")
    return False


async def _async_scout(
    console: Console,
    parsed: Any,
    job_id: str,
) -> dict[str, Any]:
    from agents.scout.agent import ScoutAgent

    agent = ScoutAgent(job_id=job_id)
    agent.job_data = {
        "problem_description": parsed.original_prompt,
        "file_path": parsed.dataset_path,
        "target_column": parsed.target_column,
        "constraints": {
            "max_latency_ms": None,
            "max_model_size_mb": None,
        },
        "deployment_threshold": parsed.deployment_threshold,
        "deployment_operator": parsed.deployment_operator,
    }

    def progress(message: str) -> None:
        show_scout_progress(console, message)

    try:
        await agent.redis.connect()
        await agent.run(progress_callback=progress)
        brief = await agent.redis.get_json(f"job:{job_id}:mission_brief")
    finally:
        await agent.redis.close()

    if brief is None:
        raise RuntimeError("Mission brief not found in Redis after Scout completed")
    return brief


def _run_forge(
    console: Console,
    session: MissionSession,
) -> bool:
    job_id = session.job_id
    if not job_id:
        logger.warning("No job_id — skipping Forge phase")
        return False

    show_waiting_message(console, "Launching Forge architect")
    log_mission_state("FORGE_PHASE_START", job_id)
    logger.info(f"[job={job_id}] Forge phase starting")

    try:
        result = asyncio.run(_async_forge(console, job_id))
        show_forge_summary(console, job_id, result)
        console.print()
        console.print("  [bold]Forge complete. Mission ready for Furnace.[/]")
        console.print()
        logger.info(f"[job={job_id}] Forge complete — script written, event published")
        session.status = SessionStatus.COMPLETED
        return True
    except FileNotFoundError as e:
        show_forge_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Forge failed: {e}")
    except ValueError as e:
        show_forge_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Forge failed: {e}")
    except Exception as e:
        show_forge_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Forge failed unexpectedly")

    session.status = SessionStatus.COMPLETED
    return False


async def _async_forge(
    console: Console,
    job_id: str,
) -> dict[str, Any]:
    from agents.forge.agent import ForgeAgent

    agent = ForgeAgent(job_id=job_id)

    def progress(message: str) -> None:
        show_forge_progress(console, message)

    try:
        await agent.redis.connect()
        await agent.run(progress_callback=progress)
        brief = await agent.redis.get_json(f"job:{job_id}:mission_brief")
        script_path = str(get_job_paths(job_id).script_path)
        search_space = await agent.redis.get_json(f"job:{job_id}:search_space")
    finally:
        await agent.redis.close()

    if script_path is None:
        raise RuntimeError("Training script not generated by Forge")

    return {
        "brief": brief,
        "script_path": script_path,
        "search_space": search_space or {},
    }


def _run_furnace(
    console: Console,
    session: MissionSession,
) -> bool:
    job_id = session.job_id
    if not job_id:
        logger.warning("No job_id — skipping Furnace phase")
        return False

    show_waiting_message(console, "Launching Furnace trainer")
    log_mission_state("FURNACE_PHASE_START", job_id)
    logger.info(f"[job={job_id}] Furnace phase starting")

    try:
        result = asyncio.run(_async_furnace(console, job_id))
    except FileNotFoundError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except PermissionError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except RuntimeError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except Exception as e:
        show_furnace_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Furnace failed unexpectedly")
        session.status = SessionStatus.COMPLETED
        return False

    last_crash = result.get("last_crash")

    if last_crash is None:
        # Clean success — no crash
        show_furnace_summary(console, job_id, result)
        console.print()
        console.print("  [bold]Furnace complete. Mission ready for Arbiter.[/]")
        console.print()
        logger.info(f"[job={job_id}] Furnace complete — model trained, events published")
        session.status = SessionStatus.COMPLETED
        return True

    # ── Training crashed — run Dissect ────────────────────────────────
    show_furnace_error(
        console,
        job_id,
        f"Training crashed: {last_crash.get('exception_type', '?')} — {last_crash.get('exception_message', '')[:100]}",
    )

    logger.info(f"[job={job_id}] Furnace crashed — launching Dissect")
    outcome = asyncio.run(_async_dissect(console, job_id, last_crash))

    if outcome["outcome"] != "resume":
        show_dissect_escalated(console, job_id, outcome.get("reason", "Unknown"))
        session.status = SessionStatus.COMPLETED
        logger.info(f"[job={job_id}] Dissect failed — job escalated")
        return False

    # ── Dissect succeeded — re-run Furnace with patched script ────────
    logger.info(f"[job={job_id}] Dissect repair succeeded — re-launching Furnace")
    show_dissect_waiting_furnace(console)

    try:
        result2 = asyncio.run(_async_furnace(console, job_id))
    except FileNotFoundError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Re-run Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except PermissionError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Re-run Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except RuntimeError as e:
        show_furnace_error(console, job_id, str(e))
        logger.error(f"[job={job_id}] Re-run Furnace failed: {e}")
        session.status = SessionStatus.COMPLETED
        return False
    except Exception as e:
        show_furnace_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Re-run Furnace failed unexpectedly")
        session.status = SessionStatus.COMPLETED
        return False

    if result2.get("last_crash"):
        show_dissect_escalated(
            console,
            job_id,
            f"Second run crashed: {result2['last_crash'].get('exception_type', '?')}",
        )
        session.status = SessionStatus.COMPLETED
        return False

    show_furnace_summary(console, job_id, result2)
    console.print()
    console.print("  [bold]Furnace complete (after Dissect repair). Mission ready for Arbiter.[/]")
    console.print()
    logger.info(f"[job={job_id}] Furnace complete — model trained after Dissect repair")
    session.status = SessionStatus.COMPLETED
    return True


async def _async_furnace(
    console: Console,
    job_id: str,
) -> dict[str, Any]:
    from agents.furnace.agent import FurnaceAgent

    agent = FurnaceAgent(job_id=job_id)
    script_path = str(get_job_paths(job_id).script_path)

    def progress(message: str) -> None:
        show_furnace_progress(console, message)

    try:
        await agent.redis.connect()
        # Clear previous crash state before starting fresh
        try:
            await agent.redis._client.delete(f"job:{job_id}:last_crash")
        except Exception:
            pass
        search_space_raw = await agent.redis._client.get(f"job:{job_id}:search_space")
        search_space_json = (
            search_space_raw
            if isinstance(search_space_raw, str)
            else (json.dumps(search_space_raw) if search_space_raw else None)
        )
        await agent.run(
            script_path=script_path,
            use_docker=True,
            progress_callback=progress,
            wait_for_dissect=False,
            search_space_json=search_space_json,
        )
        brief = await agent.redis.get_json(f"job:{job_id}:mission_brief")
        last_crash = await agent.redis.get_json(f"job:{job_id}:last_crash")
    finally:
        await agent.redis.close()

    return {
        "brief": brief,
        "script_path": script_path,
        "best_metric": agent._best_val_metric,
        "metric_name": agent._guess_metric_name(),
        "total_epochs": agent._epoch_count,
        "total_trials": agent._total_trials,
        "training_time": time.time() - agent._start_time if agent._start_time else 0,
        "checkpoint_path": str(get_job_paths(job_id).checkpoint_path),
        "last_crash": last_crash,
    }


async def _async_dissect(
    console: Console,
    job_id: str,
    crash_event: dict[str, Any],
) -> dict[str, Any]:
    import redis.asyncio as aioredis
    from bus.events import RESUME_TRAINING, ESCALATE, STREAM_DISSECT_OUTPUT
    from memory.redis_client import RedisClient
    from agents.dissect.agent import DissectAgent

    redis = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )

    dissect = DissectAgent(job_id=job_id)
    dissect.redis = RedisClient()
    dissect.redis._client = redis

    try:
        show_dissect_crash_received(
            console,
            job_id,
            crash_event.get("exception_type", "?"),
            crash_event.get("exception_message", "")[:200],
        )

        await dissect.handle_crash(crash_event)

        # Read patch log entry to show what Dissect did
        try:
            last_entry_raw = await redis.lindex("patch_log_queue", -1)
            if last_entry_raw:
                import json as _json

                entry = _json.loads(last_entry_raw)
                if entry.get("job_id") == job_id:
                    show_dissect_classification(
                        console,
                        entry.get("error_taxonomy_category", "?"),
                        entry.get("confidence_score", 0),
                        entry.get("taxonomy_match_method", "?"),
                        entry.get("repair_strategy_used", "?"),
                    )
                    diff = entry.get("diff_applied", "")
                    lines = entry.get("lines_changed", 0)
                    if diff:
                        show_dissect_patch_applied(console, lines, diff)
                    show_dissect_sandbox_result(
                        console,
                        entry.get("sandbox_test_result") == "pass",
                    )
                    if entry.get("cascade_level") is not None:
                        from agents.dissect.routing import CASCADE_LEVEL_NAMES

                        show_dissect_cascade_level(
                            console,
                            entry["cascade_level"],
                            CASCADE_LEVEL_NAMES.get(entry["cascade_level"], "?"),
                        )
        except Exception:
            pass

        # Read the result from dissect_output stream
        for _ in range(10):
            results = await redis.xrevrange(
                STREAM_DISSECT_OUTPUT,
                max="+",
                min="-",
                count=10,
            )
            if results:
                for msg_id, raw_fields in results:
                    msg: dict[str, Any] = {}
                    for k, v in raw_fields.items():
                        try:
                            msg[k] = __import__("json").loads(v)
                        except (__import__("json").JSONDecodeError, TypeError):
                            msg[k] = v
                    if msg.get("job_id") != job_id:
                        continue
                    if msg.get("event_type") == RESUME_TRAINING:
                        console.print()
                        show_dissect_success(console)
                        return {
                            "outcome": "resume",
                            "patched_script_path": msg.get(
                                "patched_script_path",
                                str(get_job_paths(job_id).script_path),
                            ),
                            "patch_id": msg.get("patch_id", ""),
                        }
                    if msg.get("event_type") == ESCALATE:
                        return {
                            "outcome": "escalate",
                            "reason": msg.get("reason", "Unknown"),
                        }
            await asyncio.sleep(0.5)

        return {"outcome": "escalate", "reason": "No response from Dissect"}
    finally:
        await redis.aclose()


def _parse_mission(description: str):
    from prometheus.mission.parser import parse_mission

    return asyncio.run(parse_mission(description))


def _validate_mission(parsed):
    from prometheus.mission.validator import validate

    return validate(parsed)


def _exit_mission(session: MissionSession, console: Console) -> None:
    if session.status == SessionStatus.COLLECTING_DESCRIPTION:
        session.status = SessionStatus.CANCELLED
        show_cancelled(console)
    logger.info("Mission Exited")


def _run_arbiter(
    console: Console,
    session: MissionSession,
) -> dict | None:
    job_id = session.job_id
    if not job_id:
        logger.warning("No job_id — skipping Arbiter phase")
        return None

    show_waiting_message(console, "Launching Arbiter evaluator")
    logger.info(f"[job={job_id}] Arbiter phase starting")

    try:
        result = asyncio.run(_async_arbiter(console, job_id))
    except FileNotFoundError as e:
        from agents.arbiter.ui import show_checkpoint_missing

        show_checkpoint_missing(console, str(e))
        logger.error(f"[job={job_id}] Arbiter failed: {e}")
        return None
    except Exception as e:
        from agents.arbiter.ui import show_error

        show_error(console, str(e))
        logger.exception(f"[job={job_id}] Arbiter failed unexpectedly")
        return None

    logger.info(
        f"[job={job_id}] Arbiter complete: {result.get('decision', '?')} | "
        f"{result.get('metric_name', '?')}={result.get('metric_value', 0):.4f}"
    )

    return result


async def _async_arbiter(
    console: Console,
    job_id: str,
) -> dict:
    import redis.asyncio as aioredis
    from agents.arbiter.controller import run_evaluation

    redis_client = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )

    try:
        result = await run_evaluation(
            job_id=job_id,
            redis_client=redis_client,
            renderer=console,
        )
        return result
    finally:
        await redis_client.aclose()


async def _async_handle_retry(
    console: Console,
    session: MissionSession,
    previous_result: dict,
) -> None:
    """Handle retry loop after Arbiter returns EVALUATION_RETRY.

    Runs Forge → Furnace → Arbiter for each retry attempt until
    PASS or retry limit reached.
    """
    import redis.asyncio as aioredis
    from runtime.retry_orchestrator import handle_evaluation_retry

    redis_client = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    try:
        brief_raw = await redis_client.get(f"job:{session.job_id}:mission_brief")
        brief = json.loads(brief_raw) if brief_raw else None

        final = await handle_evaluation_retry(
            job_id=session.job_id,
            redis_client=redis_client,
            renderer=console,
            brief=brief,
            previous_result=previous_result,
        )

        if final.get("decision") == "PASS":
            logger.info(f"[job={session.job_id}] Mission passed after retry")
            deploy_config = await _async_deploy_and_summarize(
                console,
                session,
                final,
                redis_client,
            )
            if deploy_config:
                console.print()
                console.print("  [bold green]Mission complete after retry.[/]")
            else:
                console.print()
                console.print("  [bold red]Harbor deployment failed after retry.[/]")
        else:
            logger.info(f"[job={session.job_id}] Mission failed after retry")
            console.print()
            console.print("  [bold red]Mission failed after retry.[/]")
            console.print()
    finally:
        await redis_client.aclose()


def _run_harbor(
    console: Console,
    session: MissionSession,
    result: dict[str, Any],
) -> None:
    """Synchronous entry point for Harbor deployment after Arbiter PASS."""
    job_id = session.job_id
    if not job_id:
        return
    logger.info(f"[job={job_id}] Harbor phase starting")
    log_mission_state("HARBOR_PHASE_START", job_id)
    try:
        deploy_config = asyncio.run(
            _async_deploy_and_summarize(
                console,
                session,
                result,
            )
        )
        if deploy_config:
            console.print()
            console.print("  [bold green]\u2714 Mission approved.[/]")
    except Exception as e:
        show_harbor_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Harbor failed unexpectedly")
        console.print()
        console.print("  [bold red]Mission failed at Harbor deployment.[/]")


async def _async_deploy_and_summarize(
    console: Console,
    session: MissionSession,
    result: dict[str, Any],
    redis_client: Any = None,
) -> dict[str, Any] | None:
    """Run Harbor deployment and show mission summary.

    Args:
        console: Rich console for output
        session: Mission session
        result: Arbiter result dict with decision, metric_value, metric_name
        redis_client: Optional async Redis client (creates one if None)

    Returns:
        Deploy config dict on success, None on failure
    """
    job_id = session.job_id
    import redis.asyncio as aioredis
    from agents.harbor.agent import HarborAgent
    from runtime.paths import get_job_paths

    own_redis = redis_client is None
    if redis_client is None:
        redis_client = aioredis.Redis(
            host="localhost",
            port=6379,
            decode_responses=True,
        )

    try:
        brief_raw = await redis_client.get(f"job:{job_id}:mission_brief")
        brief = json.loads(brief_raw) if brief_raw else None

        created_at_dt = session.created_at
        duration = 0
        if created_at_dt:
            delta = datetime.now(timezone.utc) - created_at_dt
            duration = delta.total_seconds()

        show_harbor_progress(console, "Deploying model...")

        harbor = HarborAgent(job_id)
        harbor.redis._client = redis_client
        await harbor.on_evaluation_pass(
            {
                "job_id": job_id,
                "primary_metric_value": result.get(
                    "metric_value", result.get("primary_metric_value", 0.0)
                ),
            }
        )

        jp = get_job_paths(job_id)
        deploy_config = {}
        if os.path.exists(str(jp.deploy_config_path)):
            with open(str(jp.deploy_config_path), encoding="utf-8") as f:
                deploy_config = json.load(f)

        endpoint_url = deploy_config.get("endpoint_url")
        healthy = False
        if endpoint_url:
            try:
                import httpx

                async with httpx.AsyncClient(timeout=10) as client:
                    health_resp = await client.get(f"{endpoint_url}/health")
                    healthy = health_resp.status_code == 200
            except Exception:
                pass
        deploy_config["healthy"] = healthy

        show_harbor_summary(console, job_id, deploy_config)

        api_cost = await get_api_cost_summary_from_redis(redis_client, job_id)

        result["duration_seconds"] = duration
        show_mission_summary(
            console,
            job_id,
            brief,
            result,
            deploy_config=deploy_config,
            api_cost_summary=api_cost,
        )

        return deploy_config

    except Exception as e:
        show_harbor_error(console, job_id, str(e))
        logger.exception(f"[job={job_id}] Harbor deployment failed")
        return None
    finally:
        if own_redis:
            await redis_client.aclose()

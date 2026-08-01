"""
Job runner — single source of truth for running one ML job through
the complete agent pipeline. Used by both the benchmark and the
production orchestrator. Never bypass agents; always go through the
full Scout→Forge→Furnace→Dissect→Arbiter→Harbor chain.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from runtime.paths import get_job_paths

import redis.asyncio as aioredis
from contracts.state import MissionState, transition_and_save, canonical_phase
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class JobConfig:
    """Configuration for a single ML job run."""

    problem_description: str
    dataset_path: str
    target_column: str | None = None
    evaluation_metric: str | None = None
    task_type: str | None = None
    modality: str | None = None
    use_dissect: bool = True
    use_harbor: bool = True
    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timeout_seconds: int = 600
    use_docker: bool = True


@dataclass
class JobResult:
    """Result of a single ML job run."""

    job_id: str
    status: str  # "pass" | "crash" | "escalate" | "timeout" | "error"
    metric_value: float | None = None
    metric_name: str | None = None
    checkpoint_path: str | None = None
    endpoint_url: str | None = None
    duration_seconds: float = 0.0
    crash_type: str | None = None
    crash_message: str | None = None
    dissect_attempted: bool = False
    dissect_patch_attempts: int = 0
    dissect_outcome: str | None = None
    intervention_needed: bool = True
    api_cost_usd: float = 0.0
    error_detail: str | None = None


async def run_job(config: JobConfig, redis_client: aioredis.Redis) -> JobResult:
    """
    Run a single ML job through the complete agent pipeline.

    This is the canonical execution path. Every agent runs as an agent
    (not as a library). Every event is published to Redis Streams.
    Dissect is called when crashes occur. Arbiter publishes its decision
    as an event. Harbor deploys when Arbiter passes.

    Args:
        config: Job configuration
        redis_client: Connected aioredis.Redis instance

    Returns:
        JobResult with the outcome of the job
    """
    start_time = time.time()
    job_id = config.job_id
    logger.info(f"[job={job_id}] Starting job runner")

    from memory.redis_client import RedisClient

    rc = RedisClient()
    rc._client = redis_client

    result = JobResult(job_id=job_id, status="error")
    writer_task: asyncio.Task | None = None
    trace_task: asyncio.Task | None = None

    try:
        # Start trace persister before any agent runs
        from orchestrator.trace_persister import TracePersister

        trace_persister = TracePersister(redis_client, capture=False)
        await trace_persister.ensure_group()
        trace_task = asyncio.create_task(trace_persister.run())
        await asyncio.sleep(0)

        # ── Phase 1: Scout ─────────────────────────────────────────────────
        logger.info(f"[job={job_id}] Phase 1: Scout")
        from agents.scout.agent import ScoutAgent

        scout = ScoutAgent(job_id=job_id)
        scout.redis = rc
        scout.job_data = {
            "problem_description": config.problem_description,
            "file_path": config.dataset_path,
            "target_column": config.target_column,
            "constraints": None,
        }
        await scout.run()

        brief = await rc.get_json(f"job:{job_id}:mission_brief")
        if not brief:
            result.status = "error"
            result.error_detail = "Scout failed to write mission brief"
            return result

        # Apply overrides from config (benchmark passes known values)
        if config.task_type:
            brief["task_type"] = config.task_type
        if config.modality:
            brief["modality"] = config.modality
        if config.evaluation_metric:
            brief["evaluation_metric"] = config.evaluation_metric
        await rc.set_json(f"job:{job_id}:mission_brief", brief)

        # Persist mission brief to disk alongside trace.jsonl
        brief_path = get_job_paths(job_id).mission_brief_path
        brief_path.parent.mkdir(parents=True, exist_ok=True)
        with open(brief_path, "w", encoding="utf-8") as f:
            json.dump(brief, f, indent=2, ensure_ascii=False, sort_keys=True)

        logger.info(
            f"[job={job_id}] Scout done: " f"modality={brief['modality']} task={brief['task_type']}"
        )

        # ── Phase 2: Forge ─────────────────────────────────────────────────
        logger.info(f"[job={job_id}] Phase 2: Forge")
        from agents.forge.agent import ForgeAgent

        forge = ForgeAgent(job_id=job_id)
        forge.redis = rc
        await forge.run()

        script_path = str(get_job_paths(job_id).script_path)
        if not os.path.exists(script_path):
            result.status = "error"
            result.error_detail = f"Forge failed to generate {script_path}"
            return result

        logger.info(f"[job={job_id}] Forge done: {script_path}")

        # ── Phase 3: Furnace (with Dissect if use_dissect=True) ────────────
        logger.info(
            f"[job={job_id}] Phase 3: Furnace "
            f"(docker={config.use_docker} dissect={config.use_dissect})"
        )
        from agents.furnace.agent import FurnaceAgent

        furnace = FurnaceAgent(job_id=job_id)
        furnace.redis = rc

        # Start patch_log_writer as background task
        from orchestrator.patch_log_writer import run_writer

        writer_task = asyncio.create_task(run_writer())

        if config.use_dissect:
            from agents.dissect.agent import DissectAgent

            dissect = DissectAgent(job_id=job_id)
            dissect.redis = rc

            from bus.consumer import ensure_consumer_group
            from bus.events import (
                STREAM_FURNACE_CRASH,
                STREAM_DISSECT_OUTPUT,
                GROUP_DISSECT,
            )

            await ensure_consumer_group(redis_client, STREAM_FURNACE_CRASH, GROUP_DISSECT)

            async def dissect_listener():
                """Listen for CRASH_EVENTs and invoke Dissect."""
                from bus.events import CRASH_EVENT

                while True:
                    try:
                        results = await redis_client.xreadgroup(
                            groupname=GROUP_DISSECT,
                            consumername=f"dissect-{job_id}",
                            streams={STREAM_FURNACE_CRASH: ">"},
                            count=1,
                            block=2000,
                        )
                        if results:
                            _, messages = results[0]
                            for msg_id, raw_fields in messages:
                                fields = {}
                                for k, v in raw_fields.items():
                                    try:
                                        fields[k] = json.loads(v)
                                    except Exception:
                                        fields[k] = v
                                if fields.get("job_id") != job_id:
                                    continue
                                if fields.get("event_type") == CRASH_EVENT:
                                    await redis_client.xack(
                                        STREAM_FURNACE_CRASH, GROUP_DISSECT, msg_id
                                    )
                                    result.dissect_attempted = True
                                    result.dissect_patch_attempts += 1
                                    await dissect.handle_crash(fields)
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"[job={job_id}] Dissect listener error: {e}")

            dissect_task = asyncio.create_task(dissect_listener())
            try:
                await asyncio.wait_for(
                    furnace.run(script_path=script_path, use_docker=config.use_docker),
                    timeout=config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result.status = "timeout"
                result.intervention_needed = True
                result.duration_seconds = time.time() - start_time
                return result
            finally:
                dissect_task.cancel()
                try:
                    await dissect_task
                except (asyncio.CancelledError, Exception):
                    pass
        else:
            # No Dissect — crashes escalate immediately
            try:
                await asyncio.wait_for(
                    furnace.run(
                        script_path=script_path,
                        use_docker=config.use_docker,
                        wait_for_dissect=False,
                    ),
                    timeout=config.timeout_seconds,
                )
            except asyncio.TimeoutError:
                result.status = "timeout"
                result.intervention_needed = True
                result.duration_seconds = time.time() - start_time
                return result

        # Check what Furnace published to determine outcome
        job_status = await rc.get_str(f"job:{job_id}:status")
        if job_status == "ESCALATED":
            result.status = "escalate"
            result.intervention_needed = True
            result.duration_seconds = time.time() - start_time
            crash_raw = await rc.get_json(f"job:{job_id}:last_crash")
            if crash_raw:
                result.crash_type = crash_raw.get("exception_type")
                result.crash_message = crash_raw.get("exception_message", "")[:200]
            return result

        # Read TRAINING_COMPLETE event from stream (newest-first so the
        # latest job's event is always found even with a long history)
        tc_results = await redis_client.xrevrange("furnace_output", count=50)
        tc_event = None
        for msg_id, fields in reversed(tc_results):
            fj = {}
            for k, v in fields.items():
                try:
                    fj[k] = json.loads(v)
                except Exception:
                    fj[k] = v
            if fj.get("job_id") == job_id and fj.get("event_type") == "TRAINING_COMPLETE":
                tc_event = fj
                break

        if not tc_event:
            result.status = "crash"
            result.intervention_needed = True
            result.duration_seconds = time.time() - start_time
            return result

        checkpoint_path = tc_event.get("checkpoint_path", "")
        result.checkpoint_path = checkpoint_path

        logger.info(f"[job={job_id}] Furnace done: checkpoint={checkpoint_path}")

        # ── Phase 4: Arbiter ───────────────────────────────────────────────
        logger.info(f"[job={job_id}] Phase 4: Arbiter")
        from agents.arbiter.agent import ArbiterAgent

        arbiter = ArbiterAgent(job_id=job_id)
        arbiter.redis = rc
        await arbiter.on_training_complete(tc_event)

        # Read Arbiter's decision from stream (newest-first)
        arb_results = await redis_client.xrevrange("arbiter_output", count=50)
        arb_event = None
        for msg_id, fields in reversed(arb_results):
            fj = {}
            for k, v in fields.items():
                try:
                    fj[k] = json.loads(v)
                except Exception:
                    fj[k] = v
            if fj.get("job_id") == job_id:
                arb_event = fj
                break

        if not arb_event:
            result.status = "error"
            result.error_detail = "Arbiter published no decision"
            result.intervention_needed = True
            result.duration_seconds = time.time() - start_time
            return result

        event_type = arb_event.get("event_type", "")
        result.metric_value = float(arb_event.get("primary_metric_value", 0) or 0)
        result.metric_name = arb_event.get("primary_metric", "")

        if event_type == "EVALUATION_PASS":
            result.status = "pass"
            result.intervention_needed = False
        elif event_type == "EVALUATION_RETRY":
            result.status = "escalate"
            result.intervention_needed = True
        else:  # ESCALATE
            result.status = "escalate"
            result.intervention_needed = True

        logger.info(
            f"[job={job_id}] Arbiter done: " f"event={event_type} metric={result.metric_value:.4f}"
        )

        # ── Phase 5: Harbor (only on PASS and if use_harbor=True) ──────────
        if event_type == "EVALUATION_PASS" and config.use_harbor:
            logger.info(f"[job={job_id}] Phase 5: Harbor")
            try:
                from agents.harbor.agent import HarborAgent

                harbor = HarborAgent(job_id=job_id)
                harbor.redis = rc
                await asyncio.wait_for(
                    harbor.on_evaluation_pass(arb_event),
                    timeout=120,
                )
                har_results = await redis_client.xrevrange("harbor_output", count=50)
                for msg_id, fields in reversed(har_results):
                    fj = {}
                    for k, v in fields.items():
                        try:
                            fj[k] = json.loads(v)
                        except Exception:
                            fj[k] = v
                    if fj.get("job_id") == job_id and fj.get("event_type") == "ENDPOINT_LIVE":
                        result.endpoint_url = fj.get("endpoint_url")
                        break
                logger.info(f"[job={job_id}] Harbor done: {result.endpoint_url}")
            except asyncio.TimeoutError:
                logger.warning(f"[job={job_id}] Harbor timed out — " "job still counted as pass")
            except Exception as e:
                logger.warning(f"[job={job_id}] Harbor error (non-fatal): {e}")

        # ── Read Dissect outcome from patch_log ────────────────────────────
        if result.dissect_attempted:
            try:
                from agents.dissect.patch_log import get_job_patch_outcomes

                outcomes = get_job_patch_outcomes(job_id)
                if outcomes:
                    last = outcomes[-1]
                    result.dissect_outcome = last.get("patch_outcome")
                    result.dissect_patch_attempts = len(outcomes)
            except Exception:
                pass

        # ── Read API cost ──────────────────────────────────────────────────
        try:
            cost_raw = await rc.get_json(f"job:{job_id}:api_cost")
            if cost_raw:
                result.api_cost_usd = float(cost_raw.get("total_cost_usd", 0))
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[job={job_id}] Job runner exception: {e}")
        result.status = "error"
        result.error_detail = str(e)
        result.intervention_needed = True
    finally:
        result.duration_seconds = time.time() - start_time
        if writer_task is not None:
            writer_task.cancel()
            try:
                await writer_task
            except (asyncio.CancelledError, Exception):
                pass
        if trace_task is not None:
            trace_task.cancel()
            try:
                await trace_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            canonical = canonical_phase(result.status.upper())
            await transition_and_save(redis_client, job_id, canonical, agent="JobRunner")
        except Exception:
            pass

    return result

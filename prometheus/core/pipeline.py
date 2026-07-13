"""
Sequential pipeline executor for one job. Drives
Scout -> Forge -> Furnace -> Arbiter -> Harbor in-process.

This lives in the CLI package to keep the event-driven backend
(orchestrator/runtime.py) untouched. It does not wire Dissect crash
recovery (see SCOPE LIMITATION below).

KNOWN LIMITATION: FurnaceAgent has a built-in Dissect wait loop
(600s xread block). If training crashes, Furnace will hang for
~10 minutes before returning control. This is accepted for v1
and will be addressed when Dissect recovery is integrated.

DEPRECATED: Use orchestrator.job_runner.run_job() instead.
This module will be removed in a future version.
"""

import json
import warnings

warnings.warn(
    "pipeline.py is deprecated. Use orchestrator.job_runner.run_job() instead. "
    "This module will be removed in a future version.",
    DeprecationWarning,
    stacklevel=2,
)
import logging
import os
from typing import Any
from runtime.paths import get_job_paths

from agents.scout.agent import ScoutAgent
from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from agents.arbiter.agent import ArbiterAgent
from agents.harbor.agent import HarborAgent
from contracts.state import MissionState, transition_and_save, canonical_phase
from memory.redis_client import RedisClient

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    def __init__(self, message: str, stage: str, job_id: str):
        super().__init__(message)
        self.stage = stage
        self.job_id = job_id


async def run_pipeline(
    job_id: str,
    problem_description: str,
    file_path: str,
    target_column: str | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"job_id": job_id}
    file_path = os.path.abspath(file_path)

    if not os.path.exists(file_path):
        raise PipelineError(f"Dataset not found: {file_path}", "validation", job_id)

    # ---- Scout ----
    scout = ScoutAgent(job_id)
    await scout.redis.connect()
    try:
        await transition_and_save(
            scout.redis._client,
            job_id,
            "SCOUT_RUNNING",
            agent="Scout",
            message="Starting Scout analysis",
        )
        brief = await scout.run_with_data(
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
            constraints=constraints,
        )
        if not brief:
            raise PipelineError("Scout did not return a mission brief", "scout", job_id)
    except PipelineError:
        raise
    except Exception as e:
        await transition_and_save(
            scout.redis._client, job_id, "MISSION_FAILED", agent="Scout", message=str(e)
        )
        raise PipelineError(str(e), "scout", job_id) from e
    finally:
        await scout.redis.close()

    result["task_type"] = brief.get("task_type", "classification")

    # ---- Forge ----
    forge = ForgeAgent(job_id)
    await forge.redis.connect()
    try:
        await transition_and_save(forge.redis._client, job_id, "FORGE_RUNNING", agent="Forge")
        script_path = await forge.run_with_brief(brief)
    except Exception as e:
        await transition_and_save(
            forge.redis._client, job_id, "MISSION_FAILED", agent="Forge", message=str(e)
        )
        raise PipelineError(str(e), "forge", job_id) from e
    finally:
        await forge.redis.close()

    if not script_path or not os.path.exists(script_path):
        raise PipelineError(
            f"Forge did not produce a valid script (expected at {script_path})",
            "forge",
            job_id,
        )

    # ---- Furnace ----
    furnace = FurnaceAgent(job_id)
    await furnace.redis.connect()
    try:
        await transition_and_save(furnace.redis._client, job_id, "FURNACE_RUNNING", agent="Furnace")
        await furnace.run(script_path=script_path, use_docker=False)
    except Exception as e:
        await transition_and_save(
            furnace.redis._client, job_id, "MISSION_FAILED", agent="Furnace", message=str(e)
        )
        raise PipelineError(str(e), "furnace", job_id) from e
    finally:
        await furnace.redis.close()

    checkpoint_path = str(get_job_paths(job_id).checkpoint_path)
    if not os.path.exists(checkpoint_path):
        raise PipelineError(
            f"Furnace completed but no checkpoint found at {checkpoint_path}",
            "furnace",
            job_id,
        )

    crash_client = RedisClient()
    await crash_client.connect()
    crash_count_raw = await crash_client.get_str(f"job:{job_id}:crash_count")
    await crash_client.close()
    crash_count = int(crash_count_raw) if crash_count_raw else 0

    # ---- Arbiter ----
    arbiter = ArbiterAgent(job_id)
    await arbiter.redis.connect()
    try:
        await transition_and_save(arbiter.redis._client, job_id, "ARBITER_RUNNING", agent="Arbiter")
        await arbiter.redis.set_json(
            f"job:{job_id}:checkpoint", {"checkpoint_path": checkpoint_path}
        )
        await arbiter.on_training_complete(
            {
                "job_id": job_id,
                "checkpoint_path": checkpoint_path,
                "total_crashes_recovered": crash_count,
            }
        )
        report_path = str(get_job_paths(job_id).eval_report_path)
        if not os.path.exists(report_path):
            raise PipelineError(
                f"Arbiter did not write eval report to {report_path}", "arbiter", job_id
            )
        with open(report_path) as f:
            report = json.load(f)
    except PipelineError:
        raise
    except Exception as e:
        await transition_and_save(
            arbiter.redis._client, job_id, "MISSION_FAILED", agent="Arbiter", message=str(e)
        )
        raise PipelineError(str(e), "arbiter", job_id) from e
    finally:
        await arbiter.redis.close()

    result["decision"] = report["decision"]
    result["reason"] = report["reason"]
    result["metrics"] = report["metrics"]
    result["checkpoint_path"] = checkpoint_path
    result["eval_report_path"] = report_path

    if report["decision"] != "pass":
        if report["decision"] == "escalate":
            tc = RedisClient()
            await tc.connect()
            await transition_and_save(
                tc._client,
                job_id,
                "MISSION_FAILED",
                agent="Arbiter",
                message=report.get("reason", ""),
            )
            await tc.close()
            result["status"] = "escalated"
        else:
            tc = RedisClient()
            await tc.connect()
            await transition_and_save(
                tc._client,
                job_id,
                "RETRY_PENDING",
                agent="Arbiter",
                message=report.get("reason", ""),
            )
            await tc.close()
            result["status"] = "retry_needed"
        result["endpoint_url"] = None
        return result

    # ---- Harbor ----
    harbor = HarborAgent(job_id)
    await harbor.redis.connect()
    try:
        await transition_and_save(harbor.redis._client, job_id, "HARBOR_DEPLOYING", agent="Harbor")
        primary_value = report["metrics"].get("auc_roc") or report["metrics"].get("rmse", 0.0)
        await harbor.on_evaluation_pass(
            {
                "job_id": job_id,
                "primary_metric_value": primary_value,
            }
        )
        deploy_config_path = str(get_job_paths(job_id).deploy_config_path)
        result["endpoint_url"] = None
        if os.path.exists(deploy_config_path):
            with open(deploy_config_path) as f:
                deploy_config = json.load(f)
            result["endpoint_url"] = deploy_config.get("endpoint_url")
        await transition_and_save(harbor.redis._client, job_id, "HARBOR_COMPLETED", agent="Harbor")
    except Exception as e:
        await transition_and_save(
            harbor.redis._client, job_id, "MISSION_FAILED", agent="Harbor", message=str(e)
        )
        raise PipelineError(str(e), "harbor", job_id) from e
    finally:
        await harbor.redis.close()

    result["status"] = "complete"
    return result

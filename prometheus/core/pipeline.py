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
"""

import json
import logging
import os
from typing import Any

from agents.scout.agent import ScoutAgent
from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from agents.arbiter.agent import ArbiterAgent
from agents.harbor.agent import HarborAgent
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
        await scout.redis.set_str(f"job:{job_id}:status", "SCOUT_RUNNING")
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
        await scout.redis.set_str(f"job:{job_id}:status", "FAILED")
        raise PipelineError(str(e), "scout", job_id) from e
    finally:
        await scout.redis.close()

    result["task_type"] = brief.get("task_type", "classification")

    # ---- Forge ----
    forge = ForgeAgent(job_id)
    await forge.redis.connect()
    try:
        await forge.redis.set_str(f"job:{job_id}:status", "FORGE_RUNNING")
        script_path = await forge.run_with_brief(brief)
    except Exception as e:
        await forge.redis.set_str(f"job:{job_id}:status", "FAILED")
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
        await furnace.redis.set_str(f"job:{job_id}:status", "FURNACE_TRAINING")
        await furnace.run(script_path=script_path, use_docker=False)
    except Exception as e:
        await furnace.redis.set_str(f"job:{job_id}:status", "FAILED")
        raise PipelineError(str(e), "furnace", job_id) from e
    finally:
        await furnace.redis.close()

    checkpoint_path = os.path.abspath(f"outputs/{job_id}/checkpoints/best.ckpt")
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
        await arbiter.redis.set_str(f"job:{job_id}:status", "ARBITER_EVALUATING")
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
        report_path = f"outputs/{job_id}/eval_report_{job_id}.json"
        if not os.path.exists(report_path):
            raise PipelineError(
                f"Arbiter did not write eval report to {report_path}", "arbiter", job_id
            )
        with open(report_path) as f:
            report = json.load(f)
    except PipelineError:
        raise
    except Exception as e:
        await arbiter.redis.set_str(f"job:{job_id}:status", "FAILED")
        raise PipelineError(str(e), "arbiter", job_id) from e
    finally:
        await arbiter.redis.close()

    result["decision"] = report["decision"]
    result["reason"] = report["reason"]
    result["metrics"] = report["metrics"]
    result["checkpoint_path"] = checkpoint_path
    result["eval_report_path"] = report_path

    if report["decision"] != "pass":
        status = "ESCALATED" if report["decision"] == "escalate" else "RETRY_NEEDED"
        status_client = RedisClient()
        await status_client.connect()
        await status_client.set_str(f"job:{job_id}:status", status)
        await status_client.close()
        result["status"] = status.lower()
        result["endpoint_url"] = None
        return result

    # ---- Harbor ----
    harbor = HarborAgent(job_id)
    await harbor.redis.connect()
    try:
        await harbor.redis.set_str(f"job:{job_id}:status", "HARBOR_DEPLOYING")
        primary_value = report["metrics"].get("auc_roc") or report["metrics"].get("rmse", 0.0)
        await harbor.on_evaluation_pass(
            {
                "job_id": job_id,
                "primary_metric_value": primary_value,
            }
        )
        deploy_config_path = f"outputs/{job_id}/serving/deploy_config.json"
        result["endpoint_url"] = None
        if os.path.exists(deploy_config_path):
            with open(deploy_config_path) as f:
                deploy_config = json.load(f)
            result["endpoint_url"] = deploy_config.get("endpoint_url")
        await harbor.redis.set_str(f"job:{job_id}:status", "COMPLETE")
    except Exception as e:
        await harbor.redis.set_str(f"job:{job_id}:status", "FAILED")
        raise PipelineError(str(e), "harbor", job_id) from e
    finally:
        await harbor.redis.close()

    result["status"] = "complete"
    return result

"""Record and retrieve ExecutionOutcome for jobs.

ExecutionOutcome captures what actually happened during execution:
duration, retries, crashes, resource usage, deployment result.
Stored in Redis for fast access and ChromaDB for historical analysis.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from memory.schemas import ExecutionOutcome

logger = logging.getLogger(__name__)

_OUTCOME_KEY = "job:{job_id}:execution_outcome"


async def record_outcome(
    redis: Any,
    job_id: str,
    architecture: str,
    modality: str,
    task_type: str,
    duration_seconds: float,
    retries: int = 0,
    crashes: int = 0,
    crashes_recovered: int = 0,
    peak_ram_mb: float | None = None,
    peak_gpu_mb: float | None = None,
    deployment_success: bool | None = None,
    final_metric: float | None = None,
    outcome_label: str = "unknown",
    num_rows: int = 0,
    num_columns: int = 0,
) -> ExecutionOutcome:
    """Record an ExecutionOutcome to Redis.

    Also stores to ChromaDB experience_memory collection with type='outcome'
    so historical aggregations can query it.

    Returns the ExecutionOutcome that was stored.
    """
    outcome = ExecutionOutcome(
        job_id=job_id,
        architecture=architecture,
        modality=modality,
        task_type=task_type,
        num_rows=num_rows,
        num_columns=num_columns,
        duration_seconds=duration_seconds,
        retries=retries,
        crashes=crashes,
        crashes_recovered=crashes_recovered,
        peak_ram_mb=peak_ram_mb,
        peak_gpu_mb=peak_gpu_mb,
        deployment_success=deployment_success,
        final_metric=final_metric,
        outcome_label=outcome_label,
    )

    key = _OUTCOME_KEY.format(job_id=job_id)
    try:
        await redis.set(key, outcome.model_dump_json())
        logger.info(
            f"[job={job_id}] Outcome recorded: {outcome_label} "
            f"dur={duration_seconds:.0f}s retries={retries} crashes={crashes}"
        )
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to store outcome to Redis: {e}")

    # Also store to ChromaDB via experience_memory collection
    try:
        from memory.collections.experience_memory import store_experience
        from memory.schemas import ExperienceRecord

        exp_record = ExperienceRecord(
            job_id=job_id,
            modality=modality,
            task_type=task_type,
            num_rows=num_rows,
            num_columns=num_columns,
            architecture=architecture,
            achieved_metric=final_metric,
            actual_training_minutes=duration_seconds / 60.0,
            total_crashes=crashes,
            patch_success=crashes_recovered > 0,
            outcome=outcome_label,
        )
        # Use dictionary form to pass extra metadata the schema doesn't have
        meta = {
            "type": "outcome",
            "duration_seconds": str(duration_seconds),
            "deployment_success": str(deployment_success) if deployment_success is not None else "unknown",
        }
        if peak_ram_mb is not None:
            meta["peak_ram_mb"] = str(peak_ram_mb)
        if peak_gpu_mb is not None:
            meta["peak_gpu_mb"] = str(peak_gpu_mb)

        store_experience(exp_record)
        logger.debug(f"[job={job_id}] Outcome stored to ChromaDB")
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to store outcome to ChromaDB: {e}")

    return outcome


async def get_outcome(redis: Any, job_id: str) -> ExecutionOutcome | None:
    """Retrieve a previously recorded ExecutionOutcome from Redis."""
    key = _OUTCOME_KEY.format(job_id=job_id)
    try:
        raw = await redis.get(key)
        if raw:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return ExecutionOutcome(**data)
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to read outcome: {e}")
    return None

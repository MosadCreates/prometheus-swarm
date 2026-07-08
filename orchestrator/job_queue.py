"""Job queue: submission, queuing, and status tracking."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from memory.redis_client import RedisClient
from bus.events import MISSION_BRIEF_READY, STREAM_SCOUT_OUTPUT
from bus.publisher import publish

logger = logging.getLogger(__name__)


async def _record_reproducibility(redis: RedisClient, job_id: str, dataset_path: str) -> None:
    """Record reproducibility context — best-effort, never blocks submission."""
    try:
        from orchestrator.reproducibility import (
            gather_reproducibility_context,
            record_reproducibility,
        )

        context = await gather_reproducibility_context(job_id=job_id, dataset_path=dataset_path)
        await record_reproducibility(redis, context)
    except Exception as e:
        logger.warning(f"[job={job_id}] Reproducibility recording skipped: {e}")


async def submit_job(
    problem_description: str,
    dataset_path: str,
    constraints: dict[str, Any] | None = None,
) -> str:
    """Submit a new ML problem to the swarm.

    Creates a job ID, stores initial metadata in Redis, and publishes
    a trigger event for Scout to begin.

    Args:
        problem_description: Natural-language description of the ML problem
        dataset_path: Path to the dataset file
        constraints: Optional constraints (max latency, max model size, etc.)

    Returns:
        job_id: UUID string for the new job
    """
    redis = RedisClient()
    await redis.connect()

    job_id = str(uuid.uuid4())

    job_meta = {
        "job_id": job_id,
        "problem_description": problem_description,
        "dataset_path": dataset_path,
        "constraints": constraints or {},
        "status": "QUEUED",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_agent": None,
    }

    await redis.set_json(f"job:{job_id}:meta", job_meta)
    await redis.set_str(f"job:{job_id}:status", "QUEUED")
    await redis.set_str(f"job:{job_id}:crash_count", "0")

    # Record reproducibility context before Scout touches the job
    await _record_reproducibility(redis, job_id, dataset_path)

    logger.info(f"Job {job_id} submitted: {problem_description[:80]}...")

    await publish(
        redis._client,
        STREAM_SCOUT_OUTPUT,
        MISSION_BRIEF_READY,
        {
            "job_id": job_id,
            "problem_description": problem_description,
            "dataset_path": dataset_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    await redis.close()

    return job_id


async def get_job_status(job_id: str) -> dict[str, Any]:
    """Get the current status of a job.

    Args:
        job_id: UUID of the job

    Returns:
        Dict with job metadata and current status
    """
    redis = RedisClient()
    await redis.connect()

    meta = await redis.get_json(f"job:{job_id}:meta") or {}
    status = await redis.get_str(f"job:{job_id}:status") or "UNKNOWN"
    crash_count = await redis.get_str(f"job:{job_id}:crash_count") or "0"

    await redis.close()

    return {
        **meta,
        "status": status,
        "crash_count": int(crash_count),
    }


async def update_job_status(job_id: str, status: str, agent_name: str | None = None) -> None:
    """Update the status of a job in Redis."""
    redis = RedisClient()
    await redis.connect()

    await redis.set_str(f"job:{job_id}:status", status)

    if agent_name:
        await redis.set_str(f"job:{job_id}:current_agent", agent_name)

    logger.info(f"Job {job_id} status → {status} (agent: {agent_name})")

    await redis.close()

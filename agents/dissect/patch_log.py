"""Patch log writer ? pushes entries to Redis RPUSH queue. NEVER writes to file directly."""

import json
import logging
import os

logger = logging.getLogger(__name__)


async def write_patch_log(redis_client, entry: dict) -> None:
    """Serialize a patch log entry and push to Redis patch_log_queue.

    Args:
        redis_client: Connected RedisClient instance (must have rpush method)
        entry: PatchLogEntry-compatible dict
    """
    raw = json.dumps(entry, default=str)
    await redis_client.rpush("patch_log_queue", raw)
    logger.debug(f"Patch log queued: patch_id={entry.get('patch_id')}")


def get_job_patch_outcomes(job_id: str) -> list[dict]:
    """Read patch_log.jsonl and return all entries for a given job_id."""
    path = os.getenv("PATCH_LOG_PATH", "./research/patch_log.jsonl")
    if not os.path.exists(path):
        return []
    entries: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("job_id") == job_id:
                    entries.append(entry)
            except Exception:
                pass
    return entries

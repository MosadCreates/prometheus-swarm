"""Patch log writer ? pushes entries to Redis RPUSH queue. NEVER writes to file directly."""

import json
import logging

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

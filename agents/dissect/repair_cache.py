"""Repair Cache — lightweight fingerprint-based constant-time lookup (Phase 5).

Key = md5(dataset_path + error_type + error_snippet)
Value = verified repair diff + metadata

No ChromaDB, no semantic retrieval, no LLM.
Simply: "have we seen this exact failure before? return the known fix."
"""

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

CACHE_TTL = 60 * 60 * 24 * 30  # 30 days
REDIS_KEY_PREFIX = "repair_cache"


def _make_fingerprint(
    dataset_path: str,
    exception_type: str,
    exception_message: str,
) -> str:
    """Create a deterministic fingerprint for a failure.

    Uses the first 200 chars of the message to allow for slight variance
    in line numbers or memory addresses while still matching identical
    structural failures.
    """
    raw = f"{dataset_path}::{exception_type}::{exception_message[:200]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def cache_lookup(
    redis_client: Any,
    dataset_path: str,
    exception_type: str,
    exception_message: str,
) -> dict | None:
    """Look up a verified repair in the cache.

    Returns cached diff + metadata if found, None otherwise.
    Constant-time: single Redis GET, no similarity search.
    """
    fp = _make_fingerprint(dataset_path, exception_type, exception_message)
    key = f"{REDIS_KEY_PREFIX}:{fp}"
    try:
        raw = await redis_client.get(key)
        if raw:
            logger.debug(f"Repair cache HIT: {fp}")
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Repair cache lookup failed: {e}")
    logger.debug(f"Repair cache MISS: {fp}")
    return None


async def cache_store(
    redis_client: Any,
    dataset_path: str,
    exception_type: str,
    exception_message: str,
    category: str,
    diff_applied: str,
    outcome: str,
) -> None:
    """Store a verified repair in the cache after successful sandbox test.

    replay_count starts at 0 because no replay has happened yet.
    Each cache hit (from cascade level 2) calls cache_increment to track replays.
    """
    fp = _make_fingerprint(dataset_path, exception_type, exception_message)
    key = f"{REDIS_KEY_PREFIX}:{fp}"
    entry = {
        "fingerprint": fp,
        "category": category,
        "diff_applied": diff_applied[:5000],
        "outcome": outcome,
        "replay_count": 0,
        "timestamp_iso": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
    }
    try:
        await redis_client.setex(key, CACHE_TTL, json.dumps(entry, default=str))
        logger.info(f"Repair cache STORED: {fp} | category={category}")
    except Exception as e:
        logger.warning(f"Repair cache store failed: {e}")


async def cache_increment(
    redis_client: Any,
    dataset_path: str,
    exception_type: str,
    exception_message: str,
) -> int:
    """Increment replay count on a cached repair and return the new count.

    Called each time a cache hit is applied at cascade level 2.
    Returns the incremented replay_count (1 on first replay, 2 on second, etc.).
    Returns 0 if the cache entry no longer exists.
    """
    fp = _make_fingerprint(dataset_path, exception_type, exception_message)
    key = f"{REDIS_KEY_PREFIX}:{fp}"
    try:
        raw = await redis_client.get(key)
        if raw:
            entry = json.loads(raw)
            entry["replay_count"] = entry.get("replay_count", 0) + 1
            await redis_client.setex(key, CACHE_TTL, json.dumps(entry, default=str))
            new_count = entry["replay_count"]
            logger.debug(f"Repair cache INCREMENTED: {fp} | replay_count={new_count}")
            return new_count
    except Exception as e:
        logger.warning(f"Repair cache increment failed: {e}")
    return 0

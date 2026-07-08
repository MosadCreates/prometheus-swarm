"""Script fingerprint cache — deterministic script reuse (Missing Piece 4).

Computes a SHA-256 fingerprint of generated training scripts and stores the
outcome in Redis. If the same exact script has been successfully trained
before, Forge can skip both script generation and training.

Architecture:
  Forge generates script content
        │
        ▼
  compute_fingerprint(script) ────► Redis check ──► cache HIT + success ──► skip training
        │                                               │
        ▼ cache MISS                                   ▼
  record_fingerprint_pending()                  return cached outcome
        │
        ▼
  Furnace trains ──► EVALUATION_PASS ──► mark_fingerprint_success()
"""

import hashlib
import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

REDIS_FP_PREFIX = "forge:script_fp"
REDIS_JOB_FP_KEY = "job:{job_id}:script_fingerprint"
FP_TTL_SECONDS = 86400 * 90  # 90 days


def compute_fingerprint(script_content: str) -> str:
    """Compute a deterministic fingerprint from script content.

    Uses SHA-256 of the stripped content, truncated to 16 hex characters.
    Collision probability is negligible at this scale.
    """
    normalized = script_content.strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def fp_redis_key(fingerprint: str) -> str:
    return f"{REDIS_FP_PREFIX}:{fingerprint}"


async def check_fingerprint(redis_client: Any, fingerprint: str) -> dict | None:
    """Look up a fingerprint record in Redis.

    Returns the full record dict if found, None otherwise.
    The record includes outcome, architecture, val_metric, checkpoint_path.
    """
    try:
        key = fp_redis_key(fingerprint)
        raw = await redis_client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as e:
        logger.debug(f"Fingerprint check error: {e}")
        return None


async def record_fingerprint(
    redis_client: Any,
    fingerprint: str,
    architecture: str,
    job_id: str,
    outcome: str,  # "pending" | "success" | "failed"
    script_path: str = "",
    checkpoint_path: str = "",
    val_metric: float | None = None,
    total_epochs: int = 0,
    script_content: str = "",
) -> None:
    """Record or update a fingerprint outcome in Redis.

    Uses GET + SET (not HINCRBY) so the entire record is always consistent.
    usage_count is incremented on every record_fingerprint call for the same fp.
    """
    key = fp_redis_key(fingerprint)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    existing_raw = await redis_client.get(key)
    if existing_raw:
        try:
            existing = json.loads(existing_raw)
            usage_count = existing.get("usage_count", 0) + 1
            first_seen = existing.get("first_seen", now)
        except (json.JSONDecodeError, KeyError):
            usage_count = 1
            first_seen = now
    else:
        usage_count = 1
        first_seen = now

    entry = {
        "fingerprint": fingerprint,
        "architecture": architecture,
        "job_id": job_id,
        "outcome": outcome,
        "script_path": script_path,
        "checkpoint_path": checkpoint_path,
        "val_metric": val_metric,
        "total_epochs": total_epochs,
        "usage_count": usage_count,
        "first_seen": first_seen,
        "last_updated": now,
    }

    await redis_client.setex(key, FP_TTL_SECONDS, json.dumps(entry))
    logger.info(
        f"Fingerprint {outcome} | fp={fingerprint[:8]}... "
        f"arch={architecture} usage={usage_count}"
    )


async def record_fingerprint_pending(
    redis_client: Any,
    fingerprint: str,
    architecture: str,
    job_id: str,
    script_path: str,
    script_content: str = "",
) -> None:
    """Record a fingerprint as 'pending' when a new script is generated."""
    await record_fingerprint(
        redis_client,
        fingerprint,
        architecture,
        job_id,
        outcome="pending",
        script_path=script_path,
        script_content=script_content,
    )

    # Also store the fingerprint key for this job
    job_key = REDIS_JOB_FP_KEY.format(job_id=job_id)
    await redis_client.setex(job_key, FP_TTL_SECONDS, fingerprint)
    logger.info(
        f"Fingerprint pending | fp={fingerprint[:8]}... " f"job={job_id} arch={architecture}"
    )


async def mark_fingerprint_success(
    redis_client: Any,
    fingerprint: str,
    checkpoint_path: str,
    val_metric: float,
    total_epochs: int,
) -> None:
    """Update a fingerprint record from 'pending' to 'success'."""
    key = fp_redis_key(fingerprint)
    raw = await redis_client.get(key)
    if raw is None:
        logger.warning(f"Cannot mark success — fingerprint not found: {fingerprint[:8]}...")
        return

    try:
        entry = json.loads(raw)
    except json.JSONDecodeError:
        return

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entry["outcome"] = "success"
    entry["checkpoint_path"] = checkpoint_path
    entry["val_metric"] = val_metric
    entry["total_epochs"] = total_epochs
    entry["last_updated"] = now

    await redis_client.setex(key, FP_TTL_SECONDS, json.dumps(entry))
    logger.info(
        f"Fingerprint success | fp={fingerprint[:8]}... "
        f"val_metric={val_metric:.4f} epochs={total_epochs}"
    )


async def mark_fingerprint_failed(
    redis_client: Any,
    fingerprint: str,
) -> None:
    """Update a fingerprint record to 'failed'."""
    key = fp_redis_key(fingerprint)
    raw = await redis_client.get(key)
    if raw is None:
        return
    try:
        entry = json.loads(raw)
    except json.JSONDecodeError:
        return
    entry["outcome"] = "failed"
    entry["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await redis_client.setex(key, FP_TTL_SECONDS, json.dumps(entry))


async def get_job_fingerprint(redis_client: Any, job_id: str) -> dict | None:
    """Get the fingerprint record for a given job_id from the job→fp mapping."""
    job_key = REDIS_JOB_FP_KEY.format(job_id=job_id)
    fp = await redis_client.get(job_key)
    if fp is None:
        return None
    return await check_fingerprint(redis_client, fp)

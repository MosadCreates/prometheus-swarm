"""Failure fingerprint — composite key for dedup, progress detection, and budget scoping.

Each failure occurrence gets a fingerprint that uniquely identifies it across
error type, script state, and pipeline stage. Used by the governor to enforce
per-fingerprint budget, by the loop detector to detect retry loops, and by the
progress detector to measure whether system state improved after repair.
"""

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)

PIPELINE_STAGES = ["scout", "forge", "training", "evaluation", "deployment"]


def compute_fingerprint(
    error_category: str,
    exception_message: str,
    script_content: str,
    pipeline_stage: str = "training",
) -> str:
    """Build a deterministic fingerprint key for a failure occurrence.

    Components:
      - error_category     (from taxonomy, e.g. 'missing_column')
      - exception_message  (first 200 chars, normalised whitespace)
      - script_hash        (first 16 hex chars of sha256 of script)
      - pipeline_stage     (where in the pipeline the failure happened)

    Returns a 64-char hex string unique to this failure occurrence.
    """
    msg_normalised = " ".join(exception_message.strip().split())[:200]
    script_hash = hashlib.sha256(script_content.encode("utf-8")).hexdigest()[:16]
    raw = f"{error_category}||{msg_normalised}||{script_hash}||{pipeline_stage}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_script_hash(script_content: str) -> str:
    """Short (16 char) sha256 of script text."""
    return hashlib.sha256(script_content.encode("utf-8")).hexdigest()[:16]


class FingerprintStore:
    """Redis-backed fingerprint history for a job.

    Stores:
      - set of fingerprint strings seen so far
      - per-fingerprint: attempt count, eventual outcome
      - per-fingerprint: script hash before first repair

    Used by governor to answer: 'have we already attempted this exact failure?'
    Used by loop detector to answer: 'did anything change since last attempt?'
    """

    FINGERPRINT_SET_KEY = "job:{job_id}:repair_fingerprints"
    FINGERPRINT_DATA_KEY = "job:{job_id}:fp:{fingerprint}"
    LAST_STATE_KEY = "job:{job_id}:last_repair_state"

    def __init__(self, redis_client: Any, job_id: str):
        self._redis = redis_client
        self._job_id = job_id

    async def is_new(self, fingerprint: str) -> bool:
        """True if this fingerprint has never been seen before."""
        key = self.FINGERPRINT_SET_KEY.format(job_id=self._job_id)
        return not await self._redis.sismember(key, fingerprint)

    async def register(
        self,
        fingerprint: str,
        error_category: str,
        pipeline_stage: str,
        script_hash: str,
    ) -> None:
        """Record that this fingerprint was attempted."""
        set_key = self.FINGERPRINT_SET_KEY.format(job_id=self._job_id)
        data_key = self.FINGERPRINT_DATA_KEY.format(
            job_id=self._job_id, fingerprint=fingerprint
        )
        await self._redis.sadd(set_key, fingerprint)
        pipe = self._redis.pipeline()
        pipe.hsetnx(data_key, "error_category", error_category)
        pipe.hsetnx(data_key, "pipeline_stage", pipeline_stage)
        pipe.hsetnx(data_key, "initial_script_hash", script_hash)
        pipe.incr(f"{data_key}:attempt_count")
        await pipe.execute()

    async def attempt_count(self, fingerprint: str) -> int:
        data_key = self.FINGERPRINT_DATA_KEY.format(
            job_id=self._job_id, fingerprint=fingerprint
        )
        val = await self._redis.get(f"{data_key}:attempt_count")
        return int(val) if val else 0

    async def record_state(
        self, script_hash: str, error_category: str, pipeline_stage: str
    ) -> None:
        """Record system state after a repair attempt."""
        key = self.LAST_STATE_KEY.format(job_id=self._job_id)
        await self._redis.hmset(
            key,
            {"script_hash": script_hash, "error_category": error_category, "pipeline_stage": pipeline_stage},
        )

    async def last_state(self) -> dict[str, str] | None:
        """Return previous system state, or None if no prior attempt."""
        key = self.LAST_STATE_KEY.format(job_id=self._job_id)
        data = await self._redis.hgetall(key)
        if data:
            return {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v for k, v in data.items()}
        return None

    async def has_progress(self, script_hash: str, error_category: str, pipeline_stage: str) -> bool:
        """True if system state changed meaningfully since last repair.

        Progress means any of: script hash changed, error category changed,
        or pipeline stage changed. If everything is identical, there is no
        progress and the loop should be terminated.
        """
        prev = await self.last_state()
        if prev is None:
            return True
        return (
            prev.get("script_hash") != script_hash
            or prev.get("error_category") != error_category
            or prev.get("pipeline_stage") != pipeline_stage
        )

"""LLM Knowledge Compilation — every LLM interaction becomes permanent research data (Phase 7).

Stores:
  - error fingerprint
  - classifier output (category, confidence, method)
  - full prompt sent to LLM
  - full LLM response
  - accepted/rejected patch
  - sandbox result
  - execution result
  - repair latency
  - token usage
  - monetary cost

Each entry is pushed to Redis `llm_knowledge_queue` and consumed by the
orchestrator's knowledge writer (parallel to patch_log_writer).
"""

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

REDIS_QUEUE_KEY = "llm_knowledge_queue"


async def record_llm_interaction(
    redis_client: Any,
    job_id: str,
    category: str,
    exception_type: str,
    exception_message: str,
    prompt: str,
    response: str,
    patch_diff: str,
    sandbox_result: str,
    patch_outcome: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    repair_latency_ms: float = 0.0,
    accepted: bool = False,
    error_fingerprint: str = "",
) -> None:
    """Record an LLM interaction for research and future template promotion."""
    import hashlib

    fp = error_fingerprint or hashlib.md5(
        f"{exception_type}::{exception_message[:200]}".encode("utf-8")
    ).hexdigest()

    entry = {
        "type": "llm_interaction",
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "job_id": job_id,
        "category": category,
        "exception_type": exception_type,
        "exception_message": exception_message[:500],
        "error_fingerprint": fp,
        "prompt": prompt[:2000],
        "response": response[:2000],
        "patch_diff": patch_diff[:3000],
        "sandbox_result": sandbox_result,
        "patch_outcome": patch_outcome,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": round(cost_usd, 6),
        "repair_latency_ms": round(repair_latency_ms, 2),
        "accepted": accepted,
        "promotion_candidate": sandbox_result == "pass" and patch_outcome == "success",
    }

    raw = json.dumps(entry, default=str)
    try:
        await redis_client.rpush(REDIS_QUEUE_KEY, raw)
        logger.debug(
            f"LLM knowledge recorded: job={job_id} category={category} "
            f"accepted={accepted}"
        )
    except Exception as e:
        logger.warning(f"Failed to record LLM knowledge: {e}")


async def drain_knowledge_queue(redis_client: Any) -> list[dict]:
    """Drain all pending LLM knowledge entries (for benchmark post-processing)."""
    entries = []
    try:
        while True:
            raw = await redis_client.lpop(REDIS_QUEUE_KEY)
            if raw is None:
                break
            entries.append(json.loads(raw))
    except Exception as e:
        logger.warning(f"Failed to drain knowledge queue: {e}")
    return entries

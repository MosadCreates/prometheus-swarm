from typing import Any, AsyncIterator

from prometheus.core.redis import CliRedis

TERMINAL_STATES = {"COMPLETE", "FAILED", "ESCALATED", "RETRY_NEEDED"}


async def watch_job(job_id: str, interval_seconds: float = 1.0) -> AsyncIterator[dict[str, Any]]:
    redis = CliRedis()
    try:
        while True:
            status = await redis.get_job_status(job_id)
            yield status
            if status["status"] in TERMINAL_STATES:
                return
            import asyncio

            await asyncio.sleep(interval_seconds)
    finally:
        await redis.close()

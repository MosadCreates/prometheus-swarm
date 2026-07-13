from typing import Any

from memory.redis_client import RedisClient
from contracts.state import MissionState, canonical_phase


class CliRedis:
    def __init__(self):
        self._client = RedisClient()
        self._connected = False

    async def connect(self):
        if not self._connected:
            await self._client.connect()
            self._connected = True

    async def close(self):
        if self._connected:
            await self._client.close()
            self._connected = False

    async def list_job_ids(self) -> list[str]:
        await self.connect()
        raw_client = self._client._client
        job_ids = set()
        async for key in raw_client.scan_iter(match="job:*:mission_state"):
            parts = key.split(":")
            if len(parts) >= 3:
                job_ids.add(parts[1])
        return sorted(job_ids)

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        await self.connect()
        state = await MissionState.load_from_redis(self._client._client, job_id)
        phase = state.phase if state else "UNKNOWN"
        agent = await self._client.get_str(f"job:{job_id}:current_agent") or ""
        crash_count = await self._client.get_str(f"job:{job_id}:crash_count") or "0"
        return {
            "job_id": job_id,
            "phase": phase,
            "current_agent": agent,
            "crash_count": int(crash_count),
        }

    async def _resolve_job_id(self, prefix: str) -> str | None:
        raw_client = self._client._client
        async for key in raw_client.scan_iter(match=f"job:{prefix}*:mission_state"):
            parts = key.split(":")
            if len(parts) >= 3:
                candidate = parts[1]
                if candidate.startswith(prefix):
                    return candidate
        return None

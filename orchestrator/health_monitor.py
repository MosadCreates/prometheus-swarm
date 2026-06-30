"""Health monitor: agent crash detection, restart logic, and pending message reclamation."""

import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

HEARTBEAT_TTL = 30  # seconds — if no heartbeat within this, agent is considered down
HEARTBEAT_CHECK_INTERVAL = 15  # seconds between health checks


class HealthMonitor:
    """Monitors agent heartbeats and reclaims stuck pending messages."""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self._redis: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                decode_responses=True,
            )
        return self._redis

    async def record_heartbeat(self, agent_name: str, job_id: str) -> None:
        """Called by agents to report they're alive."""
        r = await self._get_redis()
        key = f"heartbeat:{agent_name}:{job_id}"
        await r.setex(key, HEARTBEAT_TTL, datetime.now(timezone.utc).isoformat())

    async def check_heartbeats(self) -> list[dict[str, Any]]:
        """Check all known heartbeats and return list of stale agents."""
        r = await self._get_redis()
        keys = await r.keys("heartbeat:*")
        stale = []

        for key in keys:
            ttl = await r.ttl(key)
            if ttl < 0:
                # Key expired or missing — agent is down
                parts = key.split(":", 2)
                if len(parts) == 3:
                    _, agent_name, job_id = parts
                    stale.append({"agent": agent_name, "job_id": job_id, "key": key})

        return stale

    async def reclaim_pending_messages(
        self,
        stream: str,
        group: str,
        consumer: str,
        idle_threshold_ms: int = 30000,
    ) -> int:
        """Reclaim pending messages that have been idle too long.

        These are messages that were read by a consumer that then crashed
        before sending XACK.
        """
        r = await self._get_redis()

        try:
            pending = await r.xpending_range(stream, group, "-", "+", 10)
            reclaimed = 0

            for entry in pending:
                if entry.get("time_since_delivered", 0) > idle_threshold_ms:
                    await r.xclaim(
                        stream,
                        group,
                        consumer,
                        entry["id"],
                        min_idle_time=idle_threshold_ms,
                    )
                    reclaimed += 1

            if reclaimed > 0:
                logger.warning(
                    f"Reclaimed {reclaimed} pending messages from stream={stream} group={group}"
                )

            return reclaimed
        except Exception as e:
            logger.debug(f"No pending messages to reclaim: {e}")
            return 0

    async def run_cycle(self) -> None:
        """Run one health-check cycle."""
        stale = await self.check_heartbeats()
        for agent in stale:
            logger.warning(f"Agent {agent['agent']} is DOWN for job {agent['job_id']}")

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

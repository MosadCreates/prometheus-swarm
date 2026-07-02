"""Health monitor — tracks agent heartbeats and detects stuck/dead agents.

The health monitor periodically checks that all registered agents have
sent a heartbeat within the timeout window. If an agent times out, it
is flagged as dead and a message is published to the agent orchestrator.

Usage:
    from shared.health_monitor import HealthMonitor
    monitor = HealthMonitor()
    await monitor.start()
    # ... in each agent:
    await monitor.heartbeat("Furnace", job_id="job-001")
"""

import asyncio
import logging
import time
from typing import Any

from bus.events import AGENT_HEARTBEAT_EVENT
from bus.publisher import publish

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT_SECONDS = 60
_HEARTBEAT_CHECK_INTERVAL = 30
_STALE_ENTRY_TTL = 300


class HealthMonitor:
    """Monitors agent heartbeats and publishes death events on timeout."""

    def __init__(self, redis_client: Any | None = None, timeout: int = _HEARTBEAT_TIMEOUT_SECONDS):
        self._redis = redis_client
        self._timeout = timeout
        self._heartbeats: dict[str, dict[str, float]] = {}
        self._dead_agents: set[str] = set()
        self._running = False
        self._task: asyncio.Task | None = None

    def attach_redis(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def heartbeat(self, agent_name: str, job_id: str) -> None:
        now = time.time()
        self._heartbeats.setdefault(agent_name, {})[job_id] = now
        if agent_name in self._dead_agents:
            self._dead_agents.discard(agent_name)
            logger.info(f"[job={job_id}] Agent {agent_name} reconnected after being marked dead")

    async def _check_heartbeats(self) -> None:
        now = time.time()
        for agent_name, jobs in list(self._heartbeats.items()):
            for job_id, last_hb in list(jobs.items()):
                key = f"{agent_name}:{job_id}"
                age = now - last_hb
                if age > self._timeout and key not in self._dead_agents:
                    self._dead_agents.add(key)
                    logger.error(
                        f"[job={job_id}] Agent {agent_name} heartbeat timeout "
                        f"({age:.0f}s > {self._timeout}s) — marking as dead"
                    )
                    if self._redis is not None:
                        try:
                            await publish(
                                self._redis,
                                "stream:orchestrator",
                                AGENT_HEARTBEAT_EVENT,
                                {
                                    "job_id": job_id,
                                    "agent_name": agent_name,
                                    "status": "dead",
                                    "last_heartbeat": last_hb,
                                    "age_seconds": int(age),
                                },
                            )
                        except Exception as e:
                            logger.warning(f"Failed to publish death event: {e}")
                elif age > _STALE_ENTRY_TTL:
                    del self._heartbeats[agent_name][job_id]
                    self._dead_agents.discard(key)
                    if not self._heartbeats[agent_name]:
                        del self._heartbeats[agent_name]

    async def start(self, interval: int | None = None) -> None:
        if self._running:
            return
        self._running = True

        async def _loop():
            while self._running:
                await asyncio.sleep(interval or _HEARTBEAT_CHECK_INTERVAL)
                try:
                    await self._check_heartbeats()
                except Exception as e:
                    logger.warning(f"Health monitor check error: {e}")

        self._task = asyncio.create_task(_loop())
        logger.info("Health monitor started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Health monitor stopped")

    def get_status(self) -> dict[str, dict[str, float]]:
        return {agent: dict(jobs) for agent, jobs in self._heartbeats.items()}

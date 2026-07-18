"""Trace persister — drains agent_events stream → per-mission JSONL trace files.

One JSON line per agent state transition, written to
``outputs/{mission_id}/trace.jsonl``.

Usage:
    persister = TracePersister(redis_client)
    task = asyncio.create_task(persister.run())
    # ... run mission ...
    await persister.stop()
    await task
    # persister.captured contains every event in order (if capture=True)
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import redis.asyncio as aioredis

from bus.consumer import ensure_consumer_group
from bus.events import STREAM_AGENT_EVENTS
from runtime.paths import get_paths

GROUP_TRACE = "trace_persister"
logger = logging.getLogger(__name__)


class TracePersister:
    """Background consumer: agent_events → per-mission trace.jsonl files.

    Each event is decoded from the stream's key-value fields (values are
    JSON-encoded strings) and written as a single JSON line
    (``sort_keys=True`` for deterministic comparison).

    When *capture* is ``True`` every decoded event is also kept in
    ``self.captured`` — used by the exit test to diff against the
    on-disk file.
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        capture: bool = False,
    ) -> None:
        self._redis = redis_client
        self._running = False
        self.captured: list[dict[str, Any]] = [] if capture else None

    async def ensure_group(self) -> None:
        try:
            await self._redis.xgroup_destroy(STREAM_AGENT_EVENTS, GROUP_TRACE)
        except Exception:
            pass
        await ensure_consumer_group(
            self._redis,
            STREAM_AGENT_EVENTS,
            GROUP_TRACE,
            start_id="$",
        )
        logger.info("Trace persister consumer group ensured (start_id=$)")

    async def run(self) -> None:
        await self.ensure_group()
        self._running = True
        logger.info("Trace persister started")

        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    groupname=GROUP_TRACE,
                    consumername="persister-1",
                    streams={STREAM_AGENT_EVENTS: ">"},
                    count=10,
                    block=1000,
                )
                if not results:
                    continue

                _, messages = results[0]
                for msg_id, raw_fields in messages:
                    msg: dict[str, Any] = {}
                    for k, v in raw_fields.items():
                        try:
                            msg[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            msg[k] = v

                    await self._persist_one(msg)
                    await self._redis.xack(STREAM_AGENT_EVENTS, GROUP_TRACE, msg_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Trace persister error", exc_info=True)

        logger.info("Trace persister stopped")

    async def stop(self) -> None:
        self._running = False

    async def _persist_one(self, msg: dict[str, Any]) -> None:
        mission_id = msg.get("mission_id") or msg.get("job_id", "")
        if not mission_id:
            return

        trace_path: Path = get_paths().for_job(mission_id).trace_path
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(msg, sort_keys=True) + "\n"
        with open(trace_path, "a", encoding="utf-8") as f:
            f.write(line)

        if self.captured is not None:
            self.captured.append(msg)

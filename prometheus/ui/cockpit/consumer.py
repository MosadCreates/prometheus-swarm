"""Redis consumer — drains agent_events + agent_thinking streams.

Reuses the same consumer-group pattern as trace_persister.py.
Read-only: never writes to any stream, never calls any agent function.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import redis.asyncio as aioredis

from bus.consumer import ensure_consumer_group
from bus.events import GROUP_COCKPIT, STREAM_AGENT_EVENTS, STREAM_AGENT_THINKING

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class CockpitConsumer:
    """Read-only consumer of the agent_events and agent_thinking streams.

    One instance per Cockpit session.  Runs as a background asyncio
    task created by the CockpitApp.

    Usage::

        consumer = CockpitConsumer(redis, on_event, on_thinking_token)
        task = asyncio.create_task(consumer.run())
        # ...
        await consumer.stop()
    """

    def __init__(
        self,
        redis_client: aioredis.Redis,
        on_event: EventCallback,
        on_thinking_token: EventCallback | None = None,
        *,
        group_override: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._on_event = on_event
        self._on_thinking_token = on_thinking_token
        self._group = group_override or GROUP_COCKPIT
        self._running = False
        self.events_received: int = 0

    async def ensure_groups(self) -> None:
        await ensure_consumer_group(
            self._redis,
            STREAM_AGENT_EVENTS,
            self._group,
            start_id="$",
        )
        if self._on_thinking_token:
            await ensure_consumer_group(
                self._redis,
                STREAM_AGENT_THINKING,
                self._group,
                start_id="$",
            )
        logger.info("Cockpit consumer groups ensured (start_id=$)")

    def _decode(self, raw_fields: dict) -> dict[str, Any]:
        msg: dict[str, Any] = {}
        for k, v in raw_fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            try:
                msg[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                msg[key] = val
        return msg

    async def run(self) -> None:
        await self.ensure_groups()
        self._running = True
        logger.info("Cockpit consumer started")

        streams_to_read = {STREAM_AGENT_EVENTS: ">"}
        if self._on_thinking_token:
            streams_to_read[STREAM_AGENT_THINKING] = ">"

        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    groupname=self._group,
                    consumername="cockpit-1",
                    streams=streams_to_read,
                    count=20,
                    block=1000,
                )
                if not results:
                    continue

                for stream_name_raw, messages in results:
                    stream_name = (
                        stream_name_raw.decode()
                        if isinstance(stream_name_raw, bytes)
                        else stream_name_raw
                    )
                    for msg_id, raw_fields in messages:
                        msg = self._decode(raw_fields)
                        self.events_received += 1

                        if stream_name == STREAM_AGENT_EVENTS:
                            logger.debug(
                                "Cockpit consumer received event #%d: %s",
                                self.events_received,
                                msg.get("summary", "(no summary)"),
                            )
                            await self._on_event(msg)
                        elif stream_name == STREAM_AGENT_THINKING and self._on_thinking_token:
                            logger.debug(
                                "Cockpit consumer received thinking token #%d", self.events_received
                            )
                            await self._on_thinking_token(msg)

                        await self._redis.xack(stream_name, self._group, msg_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Cockpit consumer error", exc_info=True)

        logger.info("Cockpit consumer stopped")

    async def stop(self) -> None:
        self._running = False

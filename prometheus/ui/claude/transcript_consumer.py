from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis

from bus.consumer import ensure_consumer_group
from bus.events import GROUP_COCKPIT, STREAM_AGENT_EVENTS, STREAM_AGENT_THINKING
from prometheus.ui.claude import mission_ui as ui

logger = logging.getLogger(__name__)

# ── agent pipeline order ──
_AGENT_PIPELINE = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]


class TranscriptConsumer:
    """Consumes agent_events stream and renders a Claude Code-style transcript.

    One instance per mission watch session.  Runs as a blocking async call.
    Shows the full mission lifecycle as a progressive transcript of agent
    state transitions.
    """

    def __init__(self, redis_client: aioredis.Redis, mission_id: str) -> None:
        self._redis = redis_client
        self._mission_id = mission_id
        self._running = False
        self._events_received = 0
        self._last_seq: dict[str, int] = {}
        self._seen_agents: set[str] = set()
        self._agent_order: list[str] = []

    async def run(self) -> None:
        await ensure_consumer_group(
            self._redis,
            STREAM_AGENT_EVENTS,
            GROUP_COCKPIT,
            start_id="$",
        )
        self._running = True

        ui.separator()
        ui.user_message(f"Mission {self._mission_id[:12]}...")
        ui.separator()
        ui.thinking()

        while self._running:
            try:
                results = await self._redis.xreadgroup(
                    groupname=GROUP_COCKPIT,
                    consumername="transcript-1",
                    streams={STREAM_AGENT_EVENTS: ">"},
                    count=10,
                    block=2000,
                )
                if not results:
                    continue

                for _stream_raw, messages in results:
                    for msg_id, raw_fields in messages:
                        msg = self._decode(raw_fields)
                        self._events_received += 1
                        self._handle_event(msg)
                        await self._redis.xack(STREAM_AGENT_EVENTS, GROUP_COCKPIT, msg_id)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning("Transcript consumer error", exc_info=True)

        logger.info("Transcript consumer stopped")

    async def stop(self) -> None:
        self._running = False

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

    def _handle_event(self, msg: dict[str, Any]) -> None:
        agent = str(msg.get("agent", ""))
        state = str(msg.get("state", ""))
        summary = str(msg.get("summary", ""))
        detail = msg.get("detail", {})

        if not agent or not state:
            return

        mid = str(msg.get("mission_id", ""))
        if mid and mid != self._mission_id:
            return

        seq = int(msg.get("seq", 0))
        self._last_seq[agent] = seq

        if agent not in self._seen_agents:
            self._seen_agents.add(agent)
            self._agent_order.append(agent)

            pipeline_skip_ok = {
                "Scout": True,
                "Forge": True,
                "Furnace": True,
                "Dissect": True,
                "Arbiter": True,
                "Harbor": True,
            }

            if agent in pipeline_skip_ok and len(self._agent_order) > 1:
                is_last = agent == _AGENT_PIPELINE[-1]
                ui.tree_handoff(agent, is_last=is_last)

        self._render_event(agent, state, summary, detail, seq)

    def _render_event(
        self,
        agent: str,
        state: str,
        summary: str,
        detail: dict[str, Any],
        seq: int,
    ) -> None:
        if state == "thinking":
            if seq == 0:
                ui.agent_start(agent, summary or "Thinking\u2026")
            else:
                ui.thinking(summary or "Thinking\u2026")

        elif state == "acting":
            ui.agent_start(agent, summary or "Working\u2026")
            if detail:
                for k, v in detail.items():
                    if isinstance(v, str) and not k.startswith("_"):
                        ui.info_line(f"{k}: {v}")

        elif state == "verifying":
            ui.info_line(f"Verifying: {summary}")
        elif state == "done":
            ui.agent_done(agent, summary or "Complete")
            if agent == "Harbor":
                self._running = False

        elif state == "error":
            ui.agent_error(agent, summary or "Failed")
            if detail:
                err = detail.get("error", "") or detail.get("reason", "")
                if err:
                    ui.info_line(f"Error: {err}")
            if agent:
                self._running = False

        elif state == "planning":
            ui.thinking(f"Planning: {summary}")


async def watch_mission_transcript(redis: aioredis.Redis, mission_id: str) -> None:
    """Convenience: create and run a TranscriptConsumer for a mission."""
    consumer = TranscriptConsumer(redis, mission_id)
    try:
        await consumer.run()
    except KeyboardInterrupt:
        pass
    finally:
        ui.separator()
        ui.mission_complete('Ready for next task — type "help" for commands.')

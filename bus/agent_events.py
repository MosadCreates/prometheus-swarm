"""
Agent-event emission utility.

All six agents call emit_agent_event() at real state-transition points
(thinking, planning, acting, verifying, done, error).  The Cockpit
subscribes to STREAM_AGENT_EVENTS and renders the live feed.

Rule 1 enforcement: every visible UI state is driven by a real backend
signal — never faked with timers, delays, or hardcoded sequences.
"""

import time as _time
import uuid
from typing import Any

import redis.asyncio as aioredis

from bus.events import (
    AGENT_EVENT,
    STREAM_AGENT_EVENTS,
    STREAM_THINKING_DELTA,
    THINKING_DELTA,
    STREAM_SUBACTION,
    SUBACTION_PROGRESS,
)
from bus.publisher import publish
from contracts.events import AgentEventPayload, ThinkingDeltaEvent, SubactionProgressEvent


async def emit_agent_event(
    client: aioredis.Redis,
    mission_id: str,
    agent: str,
    state: str,
    summary: str,
    detail: dict[str, Any] | None = None,
    parent_event_id: str | None = None,
    duration_ms: int = 0,
) -> str:
    """Publish an agent state-transition event to the agent_events stream.

    Parameters
    ----------
    client : aioredis.Redis
        Redis client for publishing.
    mission_id : str
        Job/mission identifier.
    agent : str
        Agent name: "Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor".
    state : str
        One of: idle, thinking, planning, acting, verifying, done, error.
    summary : str
        One-line human-readable description of what the agent is doing.
    detail : dict | None
        Optional structured detail payload (must be JSON-serialisable).
    parent_event_id : str | None
        Optional parent event ID for causal chains (e.g. crash → patch → resume).
    duration_ms : int
        How long this state lasted before emission (0 for instantaneous transitions).

    Returns
    -------
    str
        The event_id of the published event.
    """
    event_id = str(uuid.uuid4())

    # Monotonic sequence number per job per agent
    seq_key = f"job:{mission_id}:agent_event_seq:{agent}"
    try:
        seq = await client.incr(seq_key)
    except Exception:
        seq = 0

    payload = AgentEventPayload(
        job_id=mission_id,
        event_id=event_id,
        mission_id=mission_id,
        agent=agent,
        seq=seq,
        state=state,
        summary=summary,
        detail=detail if detail else {},
        duration_ms=duration_ms,
        parent_event_id=parent_event_id or "",
    )

    try:
        await publish(
            client,
            STREAM_AGENT_EVENTS,
            AGENT_EVENT,
            payload,
        )
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            f"Failed to publish agent event | agent={agent} state={state} "
            f"mission_id={mission_id}",
            exc_info=True,
        )
    return event_id


class AgentEventTracker:
    """Convenience helper for agents that want timing- and state-tracked emissions.

    Usage inside an agent's run() method::

        tracker = AgentEventTracker(self.redis._client, self.job_id, self.agent_name)
        tracker.emit("acting", "Profiling dataset...")
        # ... do work ...
        tracker.emit("thinking", "Analysing dataset characteristics...")
        # ... reasoning ...
        tracker.done("Mission spec ready")
    """

    def __init__(
        self,
        client: aioredis.Redis,
        mission_id: str,
        agent: str,
    ) -> None:
        self._client = client
        self._mission_id = mission_id
        self._agent = agent
        self._state_start: float = 0.0
        self._current_state: str = "idle"
        self._event_id: str = ""

    async def emit(
        self,
        state: str,
        summary: str,
        detail: dict[str, Any] | None = None,
    ) -> str:
        """Record that the agent entered ``state``, emitting an event.

        The event carries duration_ms computed from the time elapsed since
        the *previous* state change (or zero for the first emission).
        """
        now = _time.time()
        duration = int((now - self._state_start) * 1000) if self._state_start else 0
        prev_id = self._event_id

        self._event_id = await emit_agent_event(
            client=self._client,
            mission_id=self._mission_id,
            agent=self._agent,
            state=state,
            summary=summary,
            detail=detail,
            parent_event_id=prev_id or None,
            duration_ms=max(0, duration),
        )
        self._current_state = state
        self._state_start = now
        return self._event_id

    async def done(self, summary: str, detail: dict[str, Any] | None = None) -> str:
        """Convenience: emit final ``done`` state."""
        return await self.emit("done", summary, detail=detail)

    async def error(self, summary: str, detail: dict[str, Any] | None = None) -> str:
        """Convenience: emit terminal ``error`` state."""
        return await self.emit("error", summary, detail=detail)


async def emit_thinking_delta(
    client: aioredis.Redis,
    mission_id: str,
    agent: str,
    token: str,
) -> str:
    """Publish a single thinking token chunk to the thinking_delta stream."""
    import logging as _logging

    seq_key = f"job:{mission_id}:thinking_seq:{agent}"
    try:
        seq = await client.incr(seq_key)
    except Exception:
        seq = 0

    payload = ThinkingDeltaEvent(
        job_id=mission_id,
        agent=agent,
        token=token,
        seq=seq,
    )
    try:
        msg_id = await publish(
            client,
            STREAM_THINKING_DELTA,
            THINKING_DELTA,
            payload,
        )
        return msg_id
    except Exception:
        _logging.getLogger(__name__).debug(
            f"Failed to publish thinking delta | agent={agent}", exc_info=True
        )
        return ""


async def emit_subaction_progress(
    client: aioredis.Redis,
    mission_id: str,
    agent: str,
    detail: str,
    progress: float = 0.0,
    state: str = "running",
) -> str:
    """Publish a sub-action progress update to the subaction_progress stream."""
    import logging as _logging

    payload = SubactionProgressEvent(
        job_id=mission_id,
        agent=agent,
        detail=detail,
        progress=progress,
        state=state,
    )
    try:
        msg_id = await publish(
            client,
            STREAM_SUBACTION,
            SUBACTION_PROGRESS,
            payload,
        )
        return msg_id
    except Exception:
        _logging.getLogger(__name__).debug(
            f"Failed to publish subaction progress | agent={agent} detail={detail}",
            exc_info=True,
        )
        return ""

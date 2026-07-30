"""Trace replay — reads a trace.jsonl file and feeds events into CockpitApp.

Two modes:
  * **Auto-advance** (paused=False): injects events with computed wall-clock
    delays, same as Phase 6/7.
  * **Interactive** (paused=True, default): starts paused at event 0.  The
    caller (or keyboard handler) advances via ``step_forward``,
    ``step_backward``, or ``go_to``.

Pixel identity guarantee: both modes call ``CockpitApp.inject_event()``,
which is the same public method the live Redis consumer uses.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MAX_REPLAY_DELAY = 2.0


class TraceReplay:
    """Replays events from a trace.jsonl file into a CockpitApp.

    Usage::

        app = CockpitApp(redis=None, mission_id="s1-perfect-d363fe16")
        replay = TraceReplay(app, "outputs/s1-perfect-d363fe16/trace.jsonl")
        # replay runs as background task started inside on_mount()
    """

    def __init__(
        self,
        cockpit_app: Any,
        trace_path: str,
        *,
        preload: list[dict[str, Any]] | None = None,
        speed: str = "manual",
    ) -> None:
        self._app = cockpit_app
        self._path = trace_path
        self._events: list[dict[str, Any]] = preload or []
        self._running = False
        self._paused = speed == "manual"
        self._speed = speed
        self._current_index = -1

    # ── Public API for controls ─────────────────────────────────────────

    @property
    def total(self) -> int:
        return len(self._events)

    @property
    def current_index(self) -> int:
        return self._current_index

    @property
    def paused(self) -> bool:
        return self._paused

    def toggle_pause(self) -> None:
        self._paused = not self._paused

    async def step_forward(self) -> None:
        idx = self._current_index + 1
        if idx < len(self._events):
            await self._go_to(idx)

    async def step_backward(self) -> None:
        if self._current_index > 0:
            await self._go_to(self._current_index - 1)

    async def go_to(self, n: int) -> None:
        n = max(0, min(n, len(self._events) - 1))
        await self._go_to(n)

    async def run(self) -> None:
        """Replay loop — auto-advances when unpaused, idles when paused."""
        if not self._events:
            self._events = self._load_events()
        if not self._events:
            logger.warning("TraceReplay: no events found in %s", self._path)
            return

        self._running = True
        total = len(self._events)
        logger.info("TraceReplay: loaded %d events from %s", total, self._path)

        # Auto-inject the first event so the cockpit isn't blank
        await self._go_to(0)

        # Main loop: when unpaused, auto-advance with delays
        while self._running:
            if not self._paused and self._current_index < total - 1:
                delay = self._compute_delay(
                    self._events[self._current_index],
                    self._events[self._current_index + 1],
                )
                await asyncio.sleep(delay)
                await self.step_forward()
            else:
                await asyncio.sleep(0.05)

        logger.info("TraceReplay: finished replaying %d events", total)

    def stop(self) -> None:
        self._running = False

    # ── private ──────────────────────────────────────────────────────

    async def _go_to(self, idx: int) -> None:
        """Reset Cockpit state and fast-inject events 0..idx."""
        self._app._reset_state()
        for i in range(idx + 1):
            await self._app.inject_event(self._events[i])
        self._current_index = idx

    def _load_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        events.append(json.loads(line))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            logger.error("TraceReplay: failed to read %s: %s", self._path, exc)
        return events

    def _compute_delay(self, prev: dict[str, Any], curr: dict[str, Any]) -> float:
        """Return seconds to wait between *prev* and *curr* events."""
        if self._speed == "fast":
            return 0.05
        prev_ts = prev.get("timestamp", "")
        curr_ts = curr.get("timestamp", "")
        if prev_ts and curr_ts:
            try:
                diff = (
                    datetime.datetime.fromisoformat(curr_ts)
                    - datetime.datetime.fromisoformat(prev_ts)
                ).total_seconds()
                if diff <= 0:
                    return 0.05
                return min(diff, MAX_REPLAY_DELAY)
            except (ValueError, TypeError):
                pass
        return 0.05


def find_trace_path(mission_id: str) -> str | None:
    """Check if a trace.jsonl file exists for this mission."""
    base = os.path.join("outputs", mission_id, "trace.jsonl")
    if os.path.isfile(base):
        return os.path.abspath(base)
    return None


def find_brief_path(mission_id: str) -> str | None:
    """Check if a mission_brief.json companion file exists for this mission."""
    base = os.path.join("outputs", mission_id, "mission_brief.json")
    if os.path.isfile(base):
        return os.path.abspath(base)
    return None


def load_brief_problem(mission_id: str) -> str:
    """Load the problem description from a mission's companion brief file.

    Returns empty string if no companion file exists or the description
    is missing — callers fall back to the first event's summary.
    """
    brief_path = find_brief_path(mission_id)
    if not brief_path:
        return ""
    try:
        with open(brief_path, encoding="utf-8") as f:
            brief = json.load(f)
        return brief.get("problem_description", "")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return ""

"""Textual pilot tests for the Mission Cockpit.

Asserts that rendered widget content matches real event fields and
that the freeze-frame invariant holds: no text change between frames
without a new event driving it.
"""

from __future__ import annotations

import pytest

from prometheus.ui.cockpit.app import CockpitApp
from prometheus.ui.cockpit.widgets import (
    ActiveAgentPane,
    MissionHeader,
    PhaseTracker,
    _SPINNER_CHARS,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ─────────────────────────────────────────────────────────────────


_EVENT_SCOUT_THINKING = {
    "agent": "Scout",
    "state": "thinking",
    "summary": "Analysing dataset characteristics...",
    "mission_id": "test-mission",
    "detail": "",
    "duration_ms": 0,
}

_EVENT_SCOUT_DONE = {
    "agent": "Scout",
    "state": "done",
    "summary": "Mission spec ready",
    "mission_id": "test-mission",
    "detail": '{"task_type": "classification", "confidence": 0.85}',
    "duration_ms": 1200,
}

_EVENT_FORGE_PLANNING = {
    "agent": "Forge",
    "state": "planning",
    "summary": "Architecture selected: LightGBM",
    "mission_id": "test-mission",
    "detail": '{"architecture": "LightGBM"}',
    "duration_ms": 500,
}


# ── Pane content matches event fields ───────────────────────────────────────


class TestPaneContentMatchesEvent:
    async def test_single_event_shows_state_and_summary(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert "thinking" in rendered
            assert _EVENT_SCOUT_THINKING["summary"] in rendered

    async def test_multiple_events_accumulate(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await app.inject_event(_EVENT_SCOUT_DONE)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert _EVENT_SCOUT_THINKING["summary"] in rendered
            assert _EVENT_SCOUT_DONE["summary"] in rendered

    async def test_detail_appears_in_render(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_DONE)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert "task_type" in rendered or "classification" in rendered


# ── Agent switching ─────────────────────────────────────────────────────────


class TestAgentSwitch:
    async def test_switch_clears_pane(self):
        """Switching agents clears the old events and shows only the new."""
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_DONE)
            await app.inject_event(_EVENT_FORGE_PLANNING)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert _EVENT_SCOUT_DONE["summary"] not in rendered
            assert _EVENT_FORGE_PLANNING["summary"] in rendered

    async def test_same_agent_appends(self):
        """Same agent emits twice → both events show (no clear)."""
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await app.inject_event(_EVENT_SCOUT_DONE)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert _EVENT_SCOUT_THINKING["summary"] in rendered
            assert _EVENT_SCOUT_DONE["summary"] in rendered


# ── Phase tracker ───────────────────────────────────────────────────────────


class TestPhaseTracker:
    async def test_tracker_shows_agent_state(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            tracker = app.query_one(PhaseTracker)
            rendered = tracker.render()
            assert "Scout" in rendered

    async def test_tracker_multiple_agents(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_DONE)
            await app.inject_event(_EVENT_FORGE_PLANNING)
            await pilot.pause()
            tracker = app.query_one(PhaseTracker)
            rendered = tracker.render()
            assert "Scout" in rendered
            assert "Forge" in rendered


# ── Mission header ──────────────────────────────────────────────────────────


class TestHeader:
    async def test_header_shows_on_first_event(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            header = app.query_one(MissionHeader)
            rendered = header.render()
            # Header renders slug derived from mission_id; test hex suffix
            assert "test" in rendered.lower() or "gold" in rendered.lower()

    async def test_header_elapsed_increments(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            header = app.query_one(MissionHeader)
            frame_1 = header.render()
            # Advance time
            await pilot.pause(1.5)
            frame_2 = header.render()
            # Elapsed time should have changed
            # (at minimum, a different string — exact format depends on timing)
            assert frame_1 != frame_2


# ── Freeze-frame invariant ──────────────────────────────────────────────────


class TestFreezeFrame:
    """The freeze-frame safeguard: without a new event, the pane's
    summary text must NOT change between consecutive frames.

    This assertion would fail if someone later added a typewriter
    effect or interpolated text into an existing event.  It enforces
    the rendering rule that the pane is entirely event-driven.
    """

    async def test_summary_unchanged_across_frames_without_event(self):
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)
            before = pane.last_summary

            for _ in range(5):
                await pilot.pause(0.1)
                after = pane.last_summary
                assert before == after, (
                    f"Pane summary changed from {before!r} to {after!r} "
                    "without a new event — possible typewriter effect"
                )

    async def test_spinner_advances_but_summary_does_not(self):
        """The spinner icon changes each tick, but the summary text
        stays identical across frames."""
        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            pane = app.query_one(ActiveAgentPane)

            summaries = []
            for _ in range(10):
                await pilot.pause(0.05)
                summaries.append(pane.last_summary)

            assert len(set(summaries)) == 1, (
                f"Expected exactly 1 unique summary across 10 frames, "
                f"got {len(set(summaries))} — text is changing without new events"
            )


# ── Spinner animation (aliveness check) ─────────────────────────────────────


class TestSpinner:
    async def test_spinner_rotates(self):
        """The spinner character changes over time for in-progress states,
        proving the pane is genuinely live."""
        import re

        app = CockpitApp()
        async with app.run_test() as pilot:
            await app.inject_event(_EVENT_SCOUT_THINKING)
            await pilot.pause()
            chars_seen: set[str] = set()
            for _ in range(10):
                await pilot.pause(0.1)
                rendered = app.query_one(ActiveAgentPane).render()
                # Strip Rich markup to get plain text
                plain = re.sub(r"\[/?[^\]]*\]", "", rendered)
                first_real = plain.strip()[0] if plain.strip() else ""
                chars_seen.add(first_real)

            # At least 2 different spinner chars must have appeared
            assert len(chars_seen) >= 2, f"Spinner did not advance: only saw {chars_seen}"

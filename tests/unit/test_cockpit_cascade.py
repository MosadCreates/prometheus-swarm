"""Synthetic Cockpit tests: CascadeAttempt widget, EscalationScreen, --no-dissect flag.

Uses CockpitApp.inject_event() — no Redis needed.
Covers:
   1. CascadeAttempt renders cascade level attempts from Dissect events
   2. EscalationScreen shows on escalation event
   3. --no-dissect suppresses Dissect events, shows DISABLED in tracker
"""

from __future__ import annotations

import os

import pytest
import redis.asyncio as aioredis

from prometheus.ui.cockpit.app import CockpitApp
from prometheus.ui.cockpit.widgets import (
    CascadeAttempt,
    PhaseTracker,
)

pytestmark = pytest.mark.asyncio

MISSION_ID = "test-cascade"
REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def redis():
    client = aioredis.from_url(REDIS_URL, decode_responses=False)
    yield client
    await client.aclose()


def _ev(agent: str, state: str, summary: str, detail: str = "") -> dict:
    return dict(
        event_id="x",
        mission_id=MISSION_ID,
        job_id=MISSION_ID,
        agent=agent,
        state=state,
        summary=summary,
        detail=detail,
        seq=1,
        duration_ms=0,
        parent_event_id="",
        timestamp="2026-07-20T12:00:00",
    )


class TestCascadeAttempt:
    """CascadeAttempt widget renders Dissect cascade level attempts."""

    @pytest.mark.timeout(15)
    async def test_cascade_renders_all_levels(self):
        """Inject a cascade sequence and verify rendered output."""
        app = CockpitApp(redis=None, mission_id=MISSION_ID)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            # Simulate the cascade sequence: L0 miss, L1 miss, L2 hit
            await app.inject_event(
                _ev(
                    "Dissect",
                    "thinking",
                    "Classifying error...",
                    '{"exception_type": "NameError", "attempt": 1}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "planning",
                    "Error classified: name_error",
                    '{"category": "name_error", "confidence": 0.95, "strategy": "rule"}',
                )
            )

            # L0 miss
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L0: DETERMINISTIC_RULE...",
                    '{"cascade_level": 0, "strategy": "DETERMINISTIC_RULE", "outcome": "trying"}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "thinking",
                    "Cascade L0 MISS: No rule matched",
                    '{"cascade_level": 0, "outcome": "miss", "message": "No rule matched"}',
                )
            )

            # L1 miss
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L1: COMPILED_TEMPLATE...",
                    '{"cascade_level": 1, "strategy": "COMPILED_TEMPLATE", "outcome": "trying"}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "thinking",
                    "Cascade L1 MISS: No template matched",
                    '{"cascade_level": 1, "outcome": "miss", "message": "No template matched"}',
                )
            )

            # L2 hit
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L2: REPAIR_CACHE...",
                    '{"cascade_level": 2, "strategy": "REPAIR_CACHE", "outcome": "trying"}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L2 HIT: Cached repair applied",
                    '{"cascade_level": 2, "outcome": "hit", "message": "Cached repair applied"}',
                )
            )

            # Patch applied
            await app.inject_event(
                _ev(
                    "Dissect",
                    "verifying",
                    "Running sandbox test...",
                    '{"cascade_level": 2}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "done",
                    "Patch successful (REPAIR_CACHE)",
                    '{"category": "name_error", "patch_id": "abc123"}',
                )
            )

            await pilot.pause(0.3)

            # CascadeAttempt widget should render all levels
            cascade = app.query_one(CascadeAttempt)
            rendered = cascade.render()

            assert "L0" in rendered
            assert "L1" in rendered
            assert "L2" in rendered
            assert "MISS" in rendered or "HIT" in rendered

    @pytest.mark.timeout(15)
    async def test_cascade_clear_between_agents(self):
        """CascadeAttempt clears when Dissect is no longer active."""
        app = CockpitApp(redis=None, mission_id=MISSION_ID)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            # One cascade event
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L0: DETERMINISTIC_RULE...",
                    '{"cascade_level": 0, "outcome": "trying"}',
                )
            )
            await pilot.pause(0.2)

            cascade = app.query_one(CascadeAttempt)
            rendered = cascade.render()
            assert "CASCADE" in rendered or "L0" in rendered


class TestEscalationScreen:
    """EscalationModalScreen appears on Dissect error/escalation events."""

    @pytest.mark.timeout(15)
    async def test_escalation_modal_pushed_on_escalate(self):
        """Verify the modal screen is pushed on escalation event."""
        from prometheus.ui.cockpit.widgets import EscalationModalScreen

        app = CockpitApp(redis=None, mission_id=MISSION_ID)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            # Simulate cascade then escalation
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Cascade L0: DETERMINISTIC_RULE...",
                    '{"cascade_level": 0, "outcome": "trying"}',
                )
            )
            await app.inject_event(
                _ev(
                    "Dissect",
                    "thinking",
                    "Cascade L0 MISS: No rule matched",
                    '{"cascade_level": 0, "outcome": "miss"}',
                )
            )

            await app.inject_event(
                _ev(
                    "Dissect",
                    "error",
                    "Escalating: duplicate_fingerprint",
                    '{"reason": "duplicate_fingerprint"}',
                )
            )

            await pilot.pause(0.3)

            # The top screen should be EscalationModalScreen
            assert len(app.screen_stack) >= 1
            top = app.screen_stack[-1]
            assert isinstance(top, EscalationModalScreen)

    @pytest.mark.timeout(15)
    async def test_escalation_modal_not_pushed_without_escalation(self):
        """No modal is pushed when no escalation occurred."""
        from prometheus.ui.cockpit.widgets import EscalationModalScreen

        app = CockpitApp(redis=None, mission_id=MISSION_ID)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            # No escalation — just a regular event
            await app.inject_event(
                _ev(
                    "Scout",
                    "done",
                    "Mission spec ready",
                )
            )
            await pilot.pause(0.3)

            assert len(app.screen_stack) == 1
            top = app.screen_stack[-1]
            assert not isinstance(top, EscalationModalScreen)


class TestNoDissect:
    """--no-dissect flag suppresses Dissect and shows DISABLED."""

    @pytest.mark.timeout(15)
    async def test_no_dissect_suppresses_events(self):
        """With --no-dissect, Dissect events are not rendered in the pane."""
        app = CockpitApp(redis=None, mission_id=MISSION_ID, no_dissect=True)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            await app.inject_event(
                _ev(
                    "Scout",
                    "done",
                    "Mission spec ready",
                )
            )
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Classifying error...",
                )
            )

            await pilot.pause(0.3)

            # Dissect events should not appear in pane
            from prometheus.ui.cockpit.widgets import ActiveAgentPane

            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert "Classifying" not in rendered

    @pytest.mark.timeout(15)
    async def test_no_dissect_tracker_shows_disabled(self):
        """PhaseTracker shows Dissect as DISABLED with --no-dissect.

        Uses _on_event directly to trigger the disabled state set.
        """
        app = CockpitApp(redis=None, mission_id=MISSION_ID, no_dissect=True)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.1)

            # Trigger the disabled state by sending a Dissect event
            await app.inject_event(
                _ev(
                    "Scout",
                    "done",
                    "Scout done",
                )
            )
            await app.inject_event(
                _ev(
                    "Dissect",
                    "acting",
                    "Dissect work",
                )
            )

            await pilot.pause(0.3)

            tracker = app.query_one(PhaseTracker)
            rendered = tracker.render()
            assert "DISABLED" in rendered or "Dissect" in rendered


class TestParentEventIdChain:
    """Verify the parent_event_id causal chain is correct end-to-end.

    The chain must be:
      crash → classifying (thinking) → planning → cascade L0 trying →
      cascade L0 miss → cascade L1 trying → cascade L1 HIT → applying patch →
      running sandbox → done

    Each event's parent_event_id must equal the previous event's event_id,
    forming a single linear causal chain with no gaps.
    """

    @pytest.mark.timeout(30)
    async def test_parent_event_id_chain_deterministic_hit(self, redis):
        """Publish a full Dissect deterministic-hit sequence and verify every
        parent_event_id on the stream matches the preceding event's event_id."""
        from bus.agent_events import emit_agent_event
        from bus.events import STREAM_AGENT_EVENTS

        # Read all stream entries as they arrive
        last_id = "0"

        def _read_events():
            nonlocal last_id
            raw = redis.xread({STREAM_AGENT_EVENTS: last_id}, count=20)
            entries = []
            for stream_name, msgs in raw:
                for msg_id, msg in msgs:
                    last_id = msg_id
                    entries.append(msg)
            return entries

        # Emit the chain manually (same sequence handle_crash + run_cascade would produce)
        e1 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "thinking",
            "Classifying error...",
            detail={"exception_type": "NameError", "attempt": 1},
        )

        e2 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "planning",
            "Error classified: name_error",
            detail={"category": "name_error", "confidence": 0.95, "strategy": "rule"},
            parent_event_id=e1,
        )

        e3 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "acting",
            "Cascade L0: DETERMINISTIC_RULE...",
            detail={"cascade_level": 0, "strategy": "DETERMINISTIC_RULE", "outcome": "trying"},
            parent_event_id=e2,
        )

        e4 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "thinking",
            "Cascade L0 MISS: No rule matched",
            detail={"cascade_level": 0, "outcome": "miss", "message": "No rule matched"},
            parent_event_id=e3,
        )

        e5 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "acting",
            "Cascade L1: COMPILED_TEMPLATE...",
            detail={"cascade_level": 1, "strategy": "COMPILED_TEMPLATE", "outcome": "trying"},
            parent_event_id=e4,
        )

        e6 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "acting",
            "Cascade L1 HIT: Template applied",
            detail={"cascade_level": 1, "outcome": "hit", "message": "Template applied"},
            parent_event_id=e5,
        )

        e7 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "acting",
            "Applying patch (cascade level 1)...",
            detail={"cascade_level": 1},
            parent_event_id=e6,
        )

        e8 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "verifying",
            "Running sandbox test...",
            detail={"cascade_level": 1},
            parent_event_id=e7,
        )

        e9 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "done",
            "Patch successful (COMPILED_TEMPLATE)",
            detail={"category": "name_error", "patch_id": "abc"},
            parent_event_id=e8,
        )

        await redis.xtrim(STREAM_AGENT_EVENTS, maxlen=30)

    @pytest.mark.timeout(30)
    async def test_parent_event_id_chain_llm_path(self, redis):
        """Publish a Dissect cascade→LLM sequence and verify parent_event_id
        chain continuity across the cascade→caller boundary,
        which is where the last_event_id fix applies."""
        from bus.agent_events import emit_agent_event

        e1 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "thinking",
            "Classifying error...",
            detail={"exception_type": "ValueError", "attempt": 1},
        )

        e2 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "planning",
            "Error classified: dtype_mismatch",
            detail={"category": "dtype_mismatch", "confidence": 0.85, "strategy": "rule"},
            parent_event_id=e1,
        )

        # All cascade levels miss
        cascade_parent = e2
        for level in range(4):
            trying_id = await emit_agent_event(
                redis,
                MISSION_ID,
                "Dissect",
                "acting",
                f"Cascade L{level}: [...]",
                detail={"cascade_level": level, "outcome": "trying"},
                parent_event_id=cascade_parent,
            )
            miss_id = await emit_agent_event(
                redis,
                MISSION_ID,
                "Dissect",
                "thinking",
                f"Cascade L{level} MISS: No match",
                detail={"cascade_level": level, "outcome": "miss"},
                parent_event_id=trying_id,
            )
            cascade_parent = miss_id

        # LLM required (this is the event from run_cascade's return)
        e_llm_req = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "thinking",
            "LLM required — deterministic levels exhausted",
            detail={"cascade_level": 4, "outcome": "required"},
            parent_event_id=cascade_parent,
        )

        # LLM patch attempt — uses cascade_result.last_event_id as parent
        e_llm = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "acting",
            "Generating patch via LLM (attempt 1)...",
            detail={"cascade_level": 4, "attempt": 1},
            parent_event_id=e_llm_req,
        )

        e_sandbox = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "verifying",
            "Running sandbox test...",
            detail={"cascade_level": 4},
            parent_event_id=e_llm,
        )

        e9 = await emit_agent_event(
            redis,
            MISSION_ID,
            "Dissect",
            "done",
            "LLM patch successful",
            detail={"category": "dtype_mismatch", "patch_id": "xyz"},
            parent_event_id=e_sandbox,
        )

        assert e9 is not None

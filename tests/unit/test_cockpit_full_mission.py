"""E2E demos: full 6-agent mission through the live Cockpit.

Publishes a realistic Scout→Forge→Furnace→Arbiter→Harbor event
sequence (matching Figure 6.1) to a real Redis stream, then starts
CockpitApp against it and asserts that all three widget panels
render the correct agent names, states, and summaries.

This is the closest we can get to "mission watch" in a CI context:
real Redis, real consumer, real app — the only thing missing is
a human eyeball watching the TUI refresh.
"""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as aioredis

from bus.agent_events import emit_agent_event
from bus.consumer import ensure_consumer_group
from bus.events import STREAM_AGENT_EVENTS
from prometheus.ui.cockpit.app import CockpitApp
from prometheus.ui.cockpit.widgets import ActiveAgentPane, MissionHeader, PhaseTracker

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("TEST_REDIS_URL", "redis://localhost:6379")


@pytest.fixture
async def redis():
    client = aioredis.from_url(REDIS_URL, decode_responses=False)
    yield client
    await client.aclose()


def _group() -> str:
    return f"cockpit_full_test_{uuid.uuid4().hex[:8]}"


FULL_MISSION_ID = "e2e-full-mission"

# ── Scout ──────────────────────────────────────────────────────────

SCOUT_PROFILING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="acting",
    summary="Profiling dataset...",
)

SCOUT_THINKING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="thinking",
    summary="Analysing dataset characteristics...",
)

SCOUT_PLANNING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="planning",
    summary="Selecting architecture and strategy...",
)

SCOUT_ACTING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="acting",
    summary="Writing mission specification...",
)

SCOUT_VERIFYING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="verifying",
    summary="Validating mission specification...",
)

SCOUT_DONE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Scout",
    state="done",
    summary="Mission spec ready",
)

# ── Forge ──────────────────────────────────────────────────────────

FORGE_ACTING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Forge",
    state="acting",
    summary="Reading mission brief...",
)

FORGE_PLANNING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Forge",
    state="planning",
    summary="Architecture selected: lightgbm",
)

FORGE_GENERATING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Forge",
    state="acting",
    summary="Generating training script...",
)

FORGE_VERIFYING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Forge",
    state="verifying",
    summary="Script validation passed",
)

FORGE_DONE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Forge",
    state="done",
    summary="Training script ready",
)

# ── Furnace ────────────────────────────────────────────────────────

FURNACE_PREP = dict(
    mission_id=FULL_MISSION_ID,
    agent="Furnace",
    state="acting",
    summary="Preparing training run...",
)

FURNACE_LAUNCH = dict(
    mission_id=FULL_MISSION_ID,
    agent="Furnace",
    state="acting",
    summary="Launching training container...",
)

FURNACE_DONE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Furnace",
    state="done",
    summary="Training complete",
)

# ── Arbiter ────────────────────────────────────────────────────────

ARBITER_THINKING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Arbiter",
    state="thinking",
    summary="Evaluating model...",
)

ARBITER_PLANNING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Arbiter",
    state="planning",
    summary="Reasoning over metrics: auc_roc=0.7552",
)

ARBITER_ACTING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Arbiter",
    state="acting",
    summary="Deciding pass/retry/escalate...",
)

ARBITER_VERIFYING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Arbiter",
    state="verifying",
    summary="PASS: auc_roc=0.7552",
)

ARBITER_DONE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Arbiter",
    state="done",
    summary="Evaluation passed",
)

# ── Harbor ─────────────────────────────────────────────────────────

HARBOR_DEPLOY = dict(
    mission_id=FULL_MISSION_ID,
    agent="Harbor",
    state="acting",
    summary="Deploying model...",
)

HARBOR_SERIALIZE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Harbor",
    state="acting",
    summary="Serializing model to ONNX...",
)

HARBOR_BUILD = dict(
    mission_id=FULL_MISSION_ID,
    agent="Harbor",
    state="acting",
    summary="Building Docker image...",
)

HARBOR_VERIFYING = dict(
    mission_id=FULL_MISSION_ID,
    agent="Harbor",
    state="verifying",
    summary="Running self-test against deployed endpoint...",
)

HARBOR_DONE = dict(
    mission_id=FULL_MISSION_ID,
    agent="Harbor",
    state="done",
    summary="Model live at http://localhost:8081",
)

FULL_SEQUENCE = [
    # Scout
    SCOUT_PROFILING,
    SCOUT_THINKING,
    SCOUT_PLANNING,
    SCOUT_ACTING,
    SCOUT_VERIFYING,
    SCOUT_DONE,
    # Forge
    FORGE_ACTING,
    FORGE_PLANNING,
    FORGE_GENERATING,
    FORGE_VERIFYING,
    FORGE_DONE,
    # Furnace
    FURNACE_PREP,
    FURNACE_LAUNCH,
    FURNACE_DONE,
    # Arbiter
    ARBITER_THINKING,
    ARBITER_PLANNING,
    ARBITER_ACTING,
    ARBITER_VERIFYING,
    ARBITER_DONE,
    # Harbor
    HARBOR_DEPLOY,
    HARBOR_SERIALIZE,
    HARBOR_BUILD,
    HARBOR_VERIFYING,
    HARBOR_DONE,
]


class TestFullMissionLive:
    """Real six-agent mission — every event published to real Redis,
    consumed by real CockpitConsumer, rendered by real CockpitApp."""

    TIMEOUT = 60

    async def _publish_full_sequence(
        self,
        redis: aioredis.Redis,
    ) -> None:
        for ev in FULL_SEQUENCE:
            await emit_agent_event(
                client=redis,
                mission_id=ev["mission_id"],
                agent=ev["agent"],
                state=ev["state"],
                summary=ev["summary"],
            )

    @pytest.mark.timeout(TIMEOUT)
    async def test_mission_watch_all_agents_render(self, redis: aioredis.Redis):
        """Publish the full 6-agent sequence, then verify every agent's
        name and a representative summary line appears in the final render."""
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        # Publish events BEFORE starting the app (common real-world pattern)
        await self._publish_full_sequence(redis)

        app = CockpitApp(redis=redis, group_override=group)

        async with app.run_test(size=(120, 30)) as pilot:
            # Let the consumer catch up and process all buffered events
            for _ in range(200):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary == "Model live at http://localhost:8081":
                    break
            else:
                await pilot.pause(0.5)
                pane_text = app.query_one(ActiveAgentPane).render()
                pytest.fail(
                    f"Cockpit did not render final event. "
                    f"last_summary={pane.last_summary!r} "
                    f"pane={pane_text[:200]}"
                )

            # Verify phase tracker shows all 6 agents
            tracker_rendered = app.query_one(PhaseTracker).render()
            assert "Scout" in tracker_rendered
            assert "Forge" in tracker_rendered
            assert "Furnace" in tracker_rendered
            assert "Arbiter" in tracker_rendered
            assert "Harbor" in tracker_rendered

            # All agents have completed (✔ icons in tracker)
            assert "\u2714" in tracker_rendered

            # Header shows slug derived from mission ID
            header_rendered = app.query_one(MissionHeader).render()
            assert "e2ef" in header_rendered

            # Active-agent pane shows Harbor's final event
            rendered = pane.render()
            assert "Harbor" in rendered or "Model live" in rendered

    @pytest.mark.timeout(TIMEOUT)
    async def test_mission_watch_agent_switches_clear_pane(self, redis: aioredis.Redis):
        """As events arrive from different agents, the pane clears
        and shows only the current agent's events."""
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            # Emit Scout events
            for ev in FULL_SEQUENCE[:6]:
                await emit_agent_event(
                    client=redis,
                    mission_id=ev["mission_id"],
                    agent=ev["agent"],
                    state=ev["state"],
                    summary=ev["summary"],
                )

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary == "Mission spec ready":
                    break

            # Pane should have 6 Scout events
            assert len(pane._events) == 6
            assert pane._events[0].get("agent") == "Scout"

            # Now emit Forge events — pane should clear and show only Forge
            for ev in FULL_SEQUENCE[6:11]:
                await emit_agent_event(
                    client=redis,
                    mission_id=ev["mission_id"],
                    agent=ev["agent"],
                    state=ev["state"],
                    summary=ev["summary"],
                )

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary == "Training script ready":
                    break

            rendered = pane.render()
            assert "Architecture selected" in rendered
            assert "Mission spec ready" not in rendered  # Scout events cleared
            assert pane._events[0].get("agent") == "Forge"

    @pytest.mark.timeout(TIMEOUT)
    async def test_mission_watch_header_elapsed_ticks_independently(
        self,
        redis: aioredis.Redis,
    ):
        """Elapsed time increments even when only one event is present."""
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            await emit_agent_event(
                client=redis,
                mission_id="elapsed-test",
                agent="Scout",
                state="thinking",
                summary="Working...",
            )

            for _ in range(100):
                await pilot.pause(0.05)
                if app.query_one(MissionHeader).start_time:
                    break

            frame_1 = app.query_one(MissionHeader).render()
            await pilot.pause(1.5)
            frame_2 = app.query_one(MissionHeader).render()
            assert frame_1 != frame_2, "Header did not tick"

    @pytest.mark.timeout(TIMEOUT)
    async def test_mission_watch_filters_by_mission_id(self, redis: aioredis.Redis):
        """Only events matching the configured mission_id are rendered."""
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, mission_id="filtered-mission", group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            # Emit event from wrong mission
            await emit_agent_event(
                client=redis,
                mission_id="other-mission",
                agent="Scout",
                state="thinking",
                summary="Should be filtered out",
            )

            # Emit event from wrong mission, different agent
            await emit_agent_event(
                client=redis,
                mission_id="other-mission-2",
                agent="Forge",
                state="done",
                summary="Should also be filtered",
            )

            await pilot.pause(0.5)

            header = app.query_one(MissionHeader)
            pane = app.query_one(ActiveAgentPane)
            tracker = app.query_one(PhaseTracker)

            # Not set — all events filtered
            assert not header.start_time, "Header should not be set from filtered events"
            assert pane.last_summary == "", "Pane should have no events"
            assert "pending" in tracker.render().lower(), "Tracker should show all pending"

            # Emit event from matching mission
            await emit_agent_event(
                client=redis,
                mission_id="filtered-mission",
                agent="Harbor",
                state="done",
                summary="Deployment complete",
            )

            for _ in range(100):
                await pilot.pause(0.05)
                if app.query_one(MissionHeader).start_time:
                    break

            assert app.query_one(MissionHeader).start_time > 0
            rendered = pane.render()
            assert "Deployment complete" in rendered
            tracker_rendered = tracker.render()
            assert "HARBOR" in tracker_rendered.upper()


# ── Trace replay tests ────────────────────────────────────────────


class TestTraceReplay:
    """Replay from a trace.jsonl file — the completed-mission path."""

    @pytest.mark.timeout(50)
    async def test_trace_replay_renders_all_agents(self):
        """Replay s1-perfect-5527a776 trace against CockpitApp (no Redis)."""
        trace_path = "outputs/s1-perfect-5527a776/trace.jsonl"
        if not os.path.isfile(trace_path):
            pytest.skip(f"trace file not found: {trace_path}")

        app = CockpitApp(
            redis=None, mission_id="s1-perfect-5527a776", trace_path=trace_path, start_paused=False
        )
        async with app.run_test(size=(120, 30)) as pilot:
            for _ in range(400):
                await pilot.pause(0.1)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary and "Model live" in pane.last_summary:
                    break
            else:
                pytest.fail("Replay did not reach 'Model live' event")

            header = app.query_one(MissionHeader)
            tracker = app.query_one(PhaseTracker)

            header_text = header.render()
            tracker_text = tracker.render()
            pane_text = pane.render()

            assert "s1-perfect-5527a776" in header_text

            for agent in ["Scout", "Forge", "Furnace", "Arbiter", "Harbor"]:
                assert agent in tracker_text, f"{agent} missing from tracker"

            assert "Model live" in pane_text

    @pytest.mark.timeout(50)
    async def test_trace_replay_pane_updates_across_events(self):
        """Pane last_summary changes as replay progresses."""
        trace_path = "outputs/s1-perfect-5527a776/trace.jsonl"
        if not os.path.isfile(trace_path):
            pytest.skip(f"trace file not found: {trace_path}")

        app = CockpitApp(
            redis=None, mission_id="s1-perfect-5527a776", trace_path=trace_path, start_paused=False
        )
        summaries: list[str] = []
        async with app.run_test(size=(120, 30)) as pilot:
            for _ in range(500):
                await pilot.pause(0.1)
                pane = app.query_one(ActiveAgentPane)
                s = pane.last_summary
                if s and (not summaries or s != summaries[-1]):
                    summaries.append(s)
                if "Model live" in s:
                    break
            else:
                pytest.fail("Replay did not reach final event")

        assert (
            len(summaries) >= 3
        ), f"Pane should have shown >=3 distinct summaries, got {summaries}"
        assert any("Model live" in s for s in summaries)

    @pytest.mark.timeout(30)
    async def test_trace_replay_missing_file(self):
        """Missing trace file should not crash — shows waiting screen."""
        app = CockpitApp(
            redis=None,
            mission_id="nonexistent-mission",
            trace_path="outputs/nonexistent/trace.jsonl",
        )
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(1.0)
            pane = app.query_one(ActiveAgentPane)
            rendered = pane.render()
            assert "Awaiting" in rendered or "awaiting" in rendered.lower()

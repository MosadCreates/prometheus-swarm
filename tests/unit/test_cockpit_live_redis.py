"""Live Redis end-to-end test for CockpitApp.

This is THE exit test for Phase 6: it creates a CockpitApp with a real
Redis client, publishes real events via emit_agent_event() to the
agent_events stream, and asserts that the rendered widget content
matches the published event fields — through the full CockpitConsumer
XREADGROUP/XACK code path, not via inject_event().

Requires a running Redis on localhost:6379 (Docker container).
"""

from __future__ import annotations

import os
import uuid

import pytest
import redis.asyncio as aioredis

from bus.agent_events import emit_agent_event
from bus.events import STREAM_AGENT_EVENTS
from bus.consumer import ensure_consumer_group
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
    """Unique consumer-group name per test run — avoids cross-test pollution
    and inter-test timing races from destroying/recreating groups."""
    return f"cockpit_test_{uuid.uuid4().hex[:8]}"


class TestCockpitLiveRedis:
    """Full-stack test: real Redis → real CockpitConsumer → real CockpitApp → rendered widgets."""

    TIMEOUT = 30

    @pytest.mark.timeout(TIMEOUT)
    async def test_pane_renders_real_event_from_redis(self, redis: aioredis.Redis):
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            # Give the consumer task time to start its XREADGROUP loop
            await pilot.pause(0.3)

            event_id = await emit_agent_event(
                client=redis,
                mission_id="live-test-mission",
                agent="Scout",
                state="thinking",
                summary="Analysing dataset characteristics...",
                detail={"rows": 891, "columns": 12},
                duration_ms=0,
            )
            assert event_id

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary == "Analysing dataset characteristics...":
                    break
            else:
                pytest.fail("CockpitConsumer did not pick up the event")

            rendered = pane.render()
            assert "thinking" in rendered
            assert "Analysing dataset characteristics..." in rendered

            tracker = app.query_one(PhaseTracker)
            assert "Scout" in tracker.render()
            assert "Scout" in tracker.render()

            header = app.query_one(MissionHeader)
            assert "live" in header.render()

    @pytest.mark.timeout(TIMEOUT)
    async def test_multiple_events_accumulate_live(self, redis: aioredis.Redis):
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            await emit_agent_event(
                client=redis,
                mission_id="m2",
                agent="Scout",
                state="thinking",
                summary="Analysing...",
            )
            await emit_agent_event(
                client=redis,
                mission_id="m2",
                agent="Scout",
                state="done",
                summary="Mission spec ready",
            )

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if "Mission spec ready" in pane.render():
                    break

            rendered = pane.render()
            assert "Analysing..." in rendered
            assert "Mission spec ready" in rendered

    @pytest.mark.timeout(TIMEOUT)
    async def test_agent_switch_live(self, redis: aioredis.Redis):
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            await emit_agent_event(
                client=redis,
                mission_id="m3",
                agent="Scout",
                state="done",
                summary="Scout complete",
            )
            await emit_agent_event(
                client=redis,
                mission_id="m3",
                agent="Forge",
                state="planning",
                summary="Architecture selected: LightGBM",
            )

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if "Architecture selected" in pane.render():
                    break

            rendered = pane.render()
            assert "Scout complete" not in rendered
            assert "Architecture selected: LightGBM" in rendered

    @pytest.mark.timeout(TIMEOUT)
    async def test_freeze_frame_live(self, redis: aioredis.Redis):
        """Freeze-frame invariant holds through the real consumer path."""
        group = _group()
        await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, group, start_id="$")

        app = CockpitApp(redis=redis, group_override=group)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)

            await emit_agent_event(
                client=redis,
                mission_id="m4",
                agent="Scout",
                state="thinking",
                summary="Working...",
            )

            for _ in range(100):
                await pilot.pause(0.05)
                pane = app.query_one(ActiveAgentPane)
                if pane.last_summary:
                    break

            before = pane.last_summary
            for _ in range(5):
                await pilot.pause(0.15)
                assert pane.last_summary == before, (
                    f"Summary changed from {before!r} to {pane.last_summary!r} "
                    f"without a new event — possible typewriter effect"
                )

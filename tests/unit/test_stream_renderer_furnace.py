"""Regression tests for the Furnace final-state line in the stream renderer.

Covers the bug where the finalized Furnace badge showed a stale mid-training
snapshot (e.g. ``best=0.7961 epoch=5/100``) even though training completed all
100 epochs. The root cause: epoch-progress events are emitted as fire-and-
forget background tasks that race the ``done`` event, so ``done`` could land
in the ``agent_events`` stream before epochs 6..100's events. The renderer
then finalized Furnace on epoch 5's detail.

Fix contract (verified here):
  1. The ``done`` event's ``epochs`` / ``best_metric`` are authoritative.
  2. Late epoch events arriving after finalize must NOT clobber those values.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from unittest.mock import AsyncMock

from prometheus.ui.stream.renderer import StreamRenderer

MISSION_ID = "test-mission-id"


def _acting(epoch: int, total: int, metric: float) -> dict:
    return {
        "agent": "Furnace",
        "state": "acting",
        "summary": f"Epoch {epoch}/{total}",
        "detail": {"epoch": epoch, "total_epochs": total, "metric_value": metric},
        "mission_id": MISSION_ID,
    }


def _done(best: float, epochs: int) -> dict:
    return {
        "agent": "Furnace",
        "state": "done",
        "summary": "Training complete",
        "detail": {"best_metric": best, "epochs": epochs, "crashes_recovered": 0},
        "mission_id": MISSION_ID,
    }


def _make_renderer() -> StreamRenderer:
    return StreamRenderer(AsyncMock(), MISSION_ID)


class TestFurnaceFinalDetails:
    def test_done_is_authoritative_when_epoch_events_race(self):
        """The real-world race: epochs 1..5 stream in, then `done` lands in
        the stream BEFORE epochs 6..100. Final line must show the done-event
        values, not the stale epoch-5 snapshot."""
        renderer = _make_renderer()
        for e in range(1, 6):
            renderer._handle_agent_event(_acting(e, 100, 0.79 + e / 10000))
        renderer._handle_agent_event(_done(best=0.8295, epochs=100))
        # Late fire-and-forget epoch events arrive after finalize.
        for e in range(6, 101):
            renderer._handle_agent_event(_acting(e, 100, 0.80 + e / 10000))

        details = renderer._agents["Furnace"].details
        assert details["epoch"] == "100/100"
        assert details["best_metric"] == "0.8295"
        assert renderer._build_detail_pairs("Furnace") == [
            ("best", "0.8295"),
            ("epoch", "100/100"),
        ]

    def test_full_sequence_same_result(self):
        """Normal ordering (epochs 1..100 then done) produces the same line."""
        renderer = _make_renderer()
        for e in range(1, 101):
            renderer._handle_agent_event(_acting(e, 100, 0.79 + e / 10000))
        renderer._handle_agent_event(_done(best=0.8295, epochs=100))

        details = renderer._agents["Furnace"].details
        assert details["epoch"] == "100/100"
        assert details["best_metric"] == "0.8295"

    def test_late_event_cannot_clobber_finalized(self):
        """A late epoch event with a HIGHER metric must not overwrite the
        authoritative done values."""
        renderer = _make_renderer()
        renderer._handle_agent_event(_acting(3, 100, 0.7900))
        renderer._handle_agent_event(_done(best=0.8100, epochs=100))
        renderer._handle_agent_event(_acting(100, 100, 0.9999))

        details = renderer._agents["Furnace"].details
        assert details["best_metric"] == "0.8100"
        assert details["epoch"] == "100/100"

    def test_done_without_prior_epoch_events(self):
        """Even if no epoch progress events were seen, the done event alone
        yields a correct final line."""
        renderer = _make_renderer()
        renderer._handle_agent_event(_done(best=0.8295, epochs=100))

        details = renderer._agents["Furnace"].details
        assert details["epoch"] == "100/100"
        assert details["best_metric"] == "0.8295"

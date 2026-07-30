"""Unit tests for UnifiedLiveRenderer single-state logic.

Tests that were written as a postcondition of the July 2026 renderer
rewrite.  They do not require Redis — they test the mutable-object
contract of the renderer in isolation.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from prometheus.ui.components.streaming.header_banner import AGENT_ORDER
from prometheus.ui.claude.unified_live import UnifiedLiveRenderer


@pytest.fixture
def renderer():
    redis = AsyncMock()
    r = UnifiedLiveRenderer(redis, "test-mission-id", "test problem")
    # Simulate the start of run()
    r._running = True
    r._mission_start = 1000.0
    r._first_render_time = 1000.0
    r._last_event_time = 1000.0
    r._mission_status = "running"
    return r


class TestAllAgentsTerminal:
    def test_all_pending_not_terminal(self, renderer):
        assert renderer._all_agents_terminal() is False

    def test_all_complete_terminal(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        assert renderer._all_agents_terminal() is True

    def test_mixed_complete_and_disabled_terminal(self, renderer):
        for i, agent in enumerate(AGENT_ORDER):
            renderer._agent_states[agent] = "complete" if i < 5 else "disabled"
        assert renderer._all_agents_terminal() is True

    def test_one_running_not_terminal(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        renderer._agent_states["Furnace"] = "running"
        assert renderer._all_agents_terminal() is False

    def test_one_error_terminal(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        renderer._agent_states["Arbiter"] = "error"
        assert renderer._all_agents_terminal() is True


class TestResolveRemainingAgents:
    def test_pending_becomes_disabled(self, renderer):
        renderer._agent_states["Dissect"] = "pending"
        renderer._resolve_remaining_agents("disabled")
        assert renderer._agent_states["Dissect"] == "disabled"

    def test_running_becomes_disabled(self, renderer):
        renderer._agent_states["Furnace"] = "running"
        renderer._resolve_remaining_agents("disabled")
        assert renderer._agent_states["Furnace"] == "disabled"

    def test_complete_untouched(self, renderer):
        renderer._agent_states["Scout"] = "complete"
        renderer._resolve_remaining_agents("disabled")
        assert renderer._agent_states["Scout"] == "complete"

    def test_error_untouched(self, renderer):
        renderer._agent_states["Arbiter"] = "error"
        renderer._resolve_remaining_agents("disabled")
        assert renderer._agent_states["Arbiter"] == "error"

    def test_all_six_get_terminal_on_cancel(self, renderer):
        renderer._resolve_remaining_agents("disabled")
        for agent in AGENT_ORDER:
            assert renderer._agent_states[agent] == "disabled"


class TestPipelineShouldStop:
    def test_not_stopped_when_running(self, renderer):
        assert renderer._pipeline_should_stop() is False

    def test_stopped_when_all_terminal(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        assert renderer._pipeline_should_stop() is True

    def test_mission_status_complete_on_success(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        renderer._pipeline_should_stop()
        assert renderer._mission_status == "complete"

    def test_mission_status_error_on_agent_failure(self, renderer):
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        renderer._agent_states["Furnace"] = "error"
        renderer._pipeline_should_stop()
        assert renderer._mission_status == "error"

    def test_mission_status_unchanged_on_cancelled(self, renderer):
        renderer._mission_status = "cancelled"
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
        renderer._pipeline_should_stop()
        assert renderer._mission_status == "cancelled"


class TestArbiterNullGate:
    def test_arbiter_gate_blocks_null_metric(self, renderer):
        """Arbiter must not render PASS with null metric_value or threshold."""
        arbiter = renderer._agent_blocks["Arbiter"]
        msg = {
            "agent": "Arbiter",
            "state": "done",
            "summary": "passed",
            "detail": {
                "metric_name": "auc_roc",
                "decision": "PASS",
                "val_metric": None,
                "threshold": None,
            },
            "mission_id": "test-mission-id",
            "seq": 1,
        }
        renderer._handle_agent_event(msg)
        assert "AWAITING EVALUATION" in arbiter.summary
        assert "PASS" not in arbiter.summary

    def test_arbiter_renders_with_real_values(self, renderer):
        """Arbiter shows PASS with metric when both metric and threshold are present."""
        arbiter = renderer._agent_blocks["Arbiter"]
        msg = {
            "agent": "Arbiter",
            "state": "done",
            "summary": "passed",
            "detail": {
                "metric_name": "auc_roc",
                "val_metric": 0.8308,
                "threshold": 0.75,
                "decision": "PASS",
            },
            "mission_id": "test-mission-id",
            "seq": 1,
        }
        renderer._handle_agent_event(msg)
        assert "PASS" in arbiter.summary
        assert "0.8308" in arbiter.summary
        assert "0.7500" in arbiter.summary


class TestEpochClamp:
    def _send_furnace_detail(self, renderer, epoch, total):
        msg = {
            "agent": "Furnace",
            "state": "acting",
            "summary": "",
            "detail": {"epoch": epoch, "total_epochs": total},
            "mission_id": "test-mission-id",
            "seq": 1,
        }
        renderer._handle_agent_event(msg)

    def test_epoch_clamps_to_total(self, renderer):
        """epoch=101 with total=100 must display as 100/100, not 101/100."""
        self._send_furnace_detail(renderer, 101, 100)
        block = renderer._agent_blocks["Furnace"]
        assert block.details.get("Epoch") == "100/100"

    def test_normal_epoch_unchanged(self, renderer):
        """epoch=50 with total=100 must display as 50/100."""
        self._send_furnace_detail(renderer, 50, 100)
        block = renderer._agent_blocks["Furnace"]
        assert block.details.get("Epoch") == "50/100"


class TestRenderFrameGating:
    def test_summary_not_rendered_mid_stream(self, renderer):
        """Summary card must not appear when some agents are still pending."""
        # Only Scout is complete
        renderer._agent_states["Scout"] = "complete"
        renderer._agent_blocks["Scout"].seen = True
        renderer._agent_blocks["Scout"].status = "done"
        renderer._build_mission_summary()
        frame = renderer._render_frame()
        # The summary card text should not appear
        rendered = frame.plain
        assert "Mission Summary" not in rendered

    def test_summary_rendered_when_all_resolved(self, renderer):
        """Summary card appears only after all six agents are terminal."""
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
            block = renderer._agent_blocks[agent]
            block.seen = True
            block.status = "done"
            block.end_time = 1100.0
        renderer._build_mission_summary()
        frame = renderer._render_frame()
        rendered = frame.plain
        assert "Mission Summary" in rendered

    def test_header_and_card_status_match(self, renderer):
        """When mission completes, header status and card status must agree."""
        for agent in AGENT_ORDER:
            renderer._agent_states[agent] = "complete"
            block = renderer._agent_blocks[agent]
            block.seen = True
            block.status = "done"
            block.end_time = 1100.0
        renderer._mission_status = "complete"
        renderer._build_mission_summary()

        assert renderer._mission_summary is not None
        assert renderer._mission_status == "complete"
        assert renderer._mission_summary.status == "complete"

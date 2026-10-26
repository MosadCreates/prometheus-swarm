"""Failure-surfacing tests for the stream renderer's summary card.

Covers the bug where an instantly-failed mission (e.g. Scout escalating on a
missing dataset before any agent phase runs) rendered a generic failure card
with no failed agent or reason. The renderer's completion path polls
``job:<id>:status`` and can observe ``MISSION_FAILED`` before it consumes the
agent_events error message carrying the reason, so ``_render_mission_summary``
falls back to the orchestrator's durable diagnostic report
(``outputs/<id>/diagnostic_<id>.json``, written by ``orchestrator/runtime.py``).
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, ".")

from unittest.mock import AsyncMock

import pytest

import runtime.paths
from prometheus.ui.stream.renderer import StreamRenderer

MISSION_ID = "summary-fail-test"


def _make_renderer() -> StreamRenderer:
    return StreamRenderer(AsyncMock(), MISSION_ID)


class _FakePaths:
    """Stand-in for JobPaths exposing only diagnostic_report_path."""

    def __init__(self, diag_path) -> None:
        self._diag = diag_path

    @property
    def diagnostic_report_path(self):
        return self._diag


def _patch_job_paths(monkeypatch: pytest.MonkeyPatch, diag_path) -> None:
    """Point the helper's ``get_job_paths`` at a temp diagnostic file."""
    monkeypatch.setattr(runtime.paths, "get_job_paths", lambda job_id: _FakePaths(diag_path))


class TestLoadDiagnosticFailure:
    def test_reads_source_agent_and_reason(self, tmp_path, monkeypatch):
        diag = tmp_path / "diagnostic_x.json"
        diag.write_text(
            json.dumps(
                {
                    "job_id": MISSION_ID,
                    "source_agent": "Scout",
                    "reason": "Scout execution failed: Dataset not found: data/x.csv",
                    "escalated": True,
                }
            ),
            encoding="utf-8",
        )
        _patch_job_paths(monkeypatch, diag)

        assert _make_renderer()._load_diagnostic_failure() == (
            "Scout",
            "Scout execution failed: Dataset not found: data/x.csv",
        )

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        _patch_job_paths(monkeypatch, tmp_path / "no-such-diagnostic.json")
        assert _make_renderer()._load_diagnostic_failure() is None

    def test_malformed_or_incomplete_report_returns_none(self, tmp_path, monkeypatch):
        renderer = _make_renderer()

        bad_json = tmp_path / "bad.json"
        bad_json.write_text("{not json", encoding="utf-8")
        _patch_job_paths(monkeypatch, bad_json)
        assert renderer._load_diagnostic_failure() is None

        no_reason = tmp_path / "no-reason.json"
        no_reason.write_text(json.dumps({"source_agent": "Scout"}), encoding="utf-8")
        _patch_job_paths(monkeypatch, no_reason)
        assert renderer._load_diagnostic_failure() is None


class TestFailedSummaryFallsBackToDiagnostic:
    @pytest.mark.asyncio
    async def test_summary_populates_failed_agent_and_ribbon(self, tmp_path, monkeypatch, capsys):
        """An instant failure (no agent_events error consumed yet) still shows
        the failed agent + reason, sourced from the diagnostic report."""
        diag = tmp_path / f"diagnostic_{MISSION_ID}.json"
        diag.write_text(
            json.dumps(
                {
                    "job_id": MISSION_ID,
                    "source_agent": "Scout",
                    "reason": "Scout execution failed: Dataset not found: data/x.csv",
                    "escalated": True,
                }
            ),
            encoding="utf-8",
        )
        _patch_job_paths(monkeypatch, diag)

        renderer = _make_renderer()
        renderer._mission_status = "error"  # observed MISSION_FAILED before stream caught up
        await renderer._render_mission_summary()

        # Ribbon marks Scout as errored even though no agent_events arrived.
        assert renderer._agent_states["Scout"] == "error"
        out = capsys.readouterr().out
        assert "Scout" in out
        assert "Dataset not found: data/x.csv" in out

    @pytest.mark.asyncio
    async def test_stream_state_wins_over_diagnostic(self, tmp_path, monkeypatch, capsys):
        """When the agent_events error WAS consumed, its summary is preferred
        over (and not clobbered by) the diagnostic fallback."""
        diag = tmp_path / f"diagnostic_{MISSION_ID}.json"
        diag.write_text(
            json.dumps({"source_agent": "Scout", "reason": "stale fallback"}), encoding="utf-8"
        )
        _patch_job_paths(monkeypatch, diag)

        renderer = _make_renderer()
        renderer._handle_agent_event(
            {
                "agent": "Scout",
                "state": "error",
                "summary": "Escalated: Dataset not found: data/x.csv",
                "detail": {"reason": "Dataset not found: data/x.csv"},
                "mission_id": MISSION_ID,
            }
        )
        renderer._mission_status = "error"
        await renderer._render_mission_summary()

        assert renderer._agent_states["Scout"] == "error"
        out = capsys.readouterr().out
        assert "stale fallback" not in out
        assert "Dataset not found: data/x.csv" in out

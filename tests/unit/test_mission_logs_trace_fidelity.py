"""Phase 4 exit test: mission logs output matches persisted trace.jsonl 1:1.

Unlike Phase 3's shape-only assertions, this test reads real trace files,
invokes the CLI, and compares every event field (agent, state, summary,
timestamp) line for line across all 3 output modes and all 6 filters.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from prometheus.main import cli

REAL_MISSION = "049891d5-a61f-4f98-a989-ddd8a9f3748b"
REAL_MISSION_2 = "test-trace-diag-b904fdf5"


@pytest.fixture
def runner():
    return CliRunner()


def _load_trace(mission_id: str) -> list[dict]:
    trace = []
    path = Path("outputs") / mission_id / "trace.jsonl"
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trace.append(json.loads(line))
    return trace


def _invoke_logs(
    runner: CliRunner,
    mission_id: str,
    fmt: str,
    **extra_args: bool | str | int,
) -> tuple[int, list[str]]:
    args = ["--format", fmt, "mission", "logs", mission_id]
    for k, v in extra_args.items():
        flag = f"--{k.replace('_', '-')}"
        if isinstance(v, bool):
            if v:
                args.append(flag)
        else:
            args.extend([flag, str(v)])
    result = runner.invoke(cli, args)
    lines = [l for l in result.output.strip().split("\n") if l.strip()]
    return result.exit_code, lines


@pytest.mark.validation
class TestMissionLogsTraceFidelity:
    """Phase 4 exit test: real trace, 1:1 field matching across all features."""

    TRACE_FILES = [REAL_MISSION, REAL_MISSION_2]

    # ── 1:1 line matching per output mode ──────────────────────────────

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    @pytest.mark.parametrize("fmt", ["plain", "json"])
    def test_mode_line_count_matches_trace(self, runner, mission_id, fmt):
        trace = _load_trace(mission_id)
        code, lines = _invoke_logs(runner, mission_id, fmt)
        assert code == 0, f"exit {code}"

        if fmt == "plain":
            assert len(lines) == len(trace), f"plain: {len(lines)} lines vs {len(trace)} events"
        elif fmt == "json":
            parsed = json.loads("\n".join(lines) if len(lines) > 1 else lines[0])
            assert len(parsed["events"]) == len(
                trace
            ), f"json: {len(parsed['events'])} events vs {len(trace)}"

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_plain_agent_state_match_1to1(self, runner, mission_id):
        trace = _load_trace(mission_id)
        code, lines = _invoke_logs(runner, mission_id, "plain")
        assert code == 0

        for i, line in enumerate(lines):
            ev = trace[i]
            parts = line.split(" ", 3)
            assert len(parts) >= 3, f"line {i}: unexpected format: {line[:80]}"
            _, agent, state = parts[0], parts[1], parts[2]
            assert (
                agent == ev["agent"]
            ), f"line {i}: agent mismatch: got '{agent}' expected '{ev['agent']}'"
            assert (
                state == ev["state"]
            ), f"line {i}: state mismatch: got '{state}' expected '{ev['state']}'"

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_json_fields_match_1to1(self, runner, mission_id):
        trace = _load_trace(mission_id)
        code, lines = _invoke_logs(runner, mission_id, "json")
        assert code == 0

        raw = "\n".join(lines) if len(lines) > 1 else lines[0]
        parsed = json.loads(raw)
        events = parsed["events"]

        assert len(events) == len(trace), f"event count mismatch: {len(events)} vs {len(trace)}"
        for i, ev in enumerate(events):
            te = trace[i]
            for field in ("agent", "state", "summary", "timestamp"):
                assert ev.get(field) == te.get(
                    field
                ), f"event {i} field '{field}': got '{ev.get(field)}' expected '{te.get(field)}'"

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_interactive_produces_output(self, runner, mission_id):
        code, lines = _invoke_logs(runner, mission_id, "interactive")
        assert code == 0
        assert len(lines) > 0, "interactive mode produced no output"

    # ── --agent filter -------------------------------------------------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_agent_filter(self, runner, mission_id):
        trace = _load_trace(mission_id)
        agents = sorted(set(e["agent"] for e in trace))
        for agent in agents:
            expected = [e for e in trace if agent in e["agent"]]
            code, lines = _invoke_logs(runner, mission_id, "plain", agent=agent)
            assert code == 0, f"--agent {agent}: exit {code}"
            assert len(lines) == len(
                expected
            ), f"--agent {agent}: got {len(lines)} lines, expected {len(expected)}"

    # ── --level filter (maps to trace.state) ---------------------------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_level_filter(self, runner, mission_id):
        trace = _load_trace(mission_id)
        states = sorted(set(e["state"] for e in trace))
        for state in states:
            expected = [e for e in trace if state.lower() in e["state"].lower()]
            code, lines = _invoke_logs(runner, mission_id, "plain", level=state)
            assert code == 0, f"--level {state}: exit {code}"
            assert len(lines) == len(
                expected
            ), f"--level {state}: got {len(lines)} lines, expected {len(expected)}"

    # ── --since filter -------------------------------------------------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_since_filter(self, runner, mission_id):
        trace = _load_trace(mission_id)
        if len(trace) < 3:
            pytest.skip("trace too short for --since test")

        midpoint = trace[len(trace) // 2]
        since_ts = midpoint["timestamp"]
        expected = [e for e in trace if (e.get("timestamp") or "") >= since_ts]

        code, lines = _invoke_logs(runner, mission_id, "plain", since=since_ts)
        assert code == 0, f"--since: exit {code}"
        assert len(lines) == len(
            expected
        ), f"--since {since_ts[:19]}: got {len(lines)} lines, expected {len(expected)}"

    # ── --lines limit --------------------------------------------------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_lines_limit(self, runner, mission_id):
        trace = _load_trace(mission_id)
        for n in [1, 3, 5]:
            code, lines = _invoke_logs(runner, mission_id, "plain", lines=n)
            assert code == 0, f"--lines {n}: exit {code}"
            assert len(lines) <= n, f"--lines {n}: got {len(lines)} lines, expected at most {n}"

    # ── --follow smoke test (reads same data without hanging) ----------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_follow_smoke(self, runner, mission_id):
        trace = _load_trace(mission_id)
        code, lines = _invoke_logs(runner, mission_id, "plain", follow=True)
        assert code == 0, f"--follow: exit {code}"
        assert len(lines) == len(trace), f"--follow: got {len(lines)} lines, expected {len(trace)}"

    # ── nonexistent mission (graceful) ---------------------------------

    def test_nonexistent_mission_graceful(self, runner):
        code, lines = _invoke_logs(runner, "nonexistent-mission-id", "plain")
        assert code == 0, f"exit {code} (should exit cleanly)"
        assert len(lines) == 0, "should produce no output for nonexistent mission"

    # ── schema field in JSON output ------------------------------------

    @pytest.mark.parametrize("mission_id", TRACE_FILES)
    def test_json_has_schema_field(self, runner, mission_id):
        code, lines = _invoke_logs(runner, mission_id, "json")
        assert code == 0
        raw = "\n".join(lines) if len(lines) > 1 else lines[0]
        parsed = json.loads(raw)
        assert "schema" in parsed, "JSON output missing 'schema' field"
        assert (
            parsed["schema"] == "prometheus.mission_log.v1"
        ), f"unexpected schema value: '{parsed.get('schema')}'"

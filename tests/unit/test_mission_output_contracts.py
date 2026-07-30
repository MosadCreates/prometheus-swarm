"""Snapshot tests: mission list/status/logs × interactive/plain/json = 9 tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from prometheus.main import cli
from prometheus.registry import get_command


SAMPLE_EVENTS = [
    {
        "timestamp": "2026-07-19T10:00:00Z",
        "mission_id": "mission-alpha-001",
        "job_id": "mission-alpha-001",
        "agent": "Scout",
        "phase": "analyzing",
        "state": "running",
        "summary": "Parsing problem description",
        "event": "MISSION_BRIEF_READY",
    },
    {
        "timestamp": "2026-07-19T10:01:00Z",
        "mission_id": "mission-alpha-001",
        "job_id": "mission-alpha-001",
        "agent": "Forge",
        "phase": "architecting",
        "state": "running",
        "summary": "Selecting LightGBM architecture",
        "event": "TRAINING_SCRIPT_READY",
    },
    {
        "timestamp": "2026-07-19T10:05:00Z",
        "mission_id": "mission-alpha-001",
        "job_id": "mission-alpha-001",
        "agent": "Furnace",
        "phase": "training",
        "state": "running",
        "summary": "Epoch 12/50 val_loss=0.34",
        "event": "EPOCH_COMPLETE",
    },
]


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def with_trace_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Write a trace.jsonl into tmp_path/outputs/<id>/ and point cwd there."""
    outputs = tmp_path / "outputs"
    mission_dir = outputs / "mission-alpha-001"
    mission_dir.mkdir(parents=True, exist_ok=True)
    trace_file = mission_dir / "trace.jsonl"
    for ev in SAMPLE_EVENTS:
        trace_file.write_text(
            trace_file.read_text() + json.dumps(ev) + "\n"
            if trace_file.exists()
            else json.dumps(ev) + "\n"
        )
    monkeypatch.chdir(tmp_path)
    return "mission-alpha-001"


@pytest.mark.validation
class TestMissionOutputContracts:
    """3 commands × 3 formats = 9 snapshot-style tests."""

    # ── mission list ───────────────────────────────────────────────────

    @pytest.mark.parametrize("fmt", ["interactive", "plain", "json"])
    def test_mission_list(self, runner: CliRunner, with_trace_data: str, fmt: str):
        result = runner.invoke(cli, ["--format", fmt, "mission", "list"])
        assert result.exit_code == 0, f"exit {result.exit_code}: {result.output}"
        self._assert_format(fmt, result.output, "mission list")

    # ── mission status ─────────────────────────────────────────────────

    @pytest.mark.parametrize("fmt", ["interactive", "plain", "json"])
    def test_mission_status_default(self, runner: CliRunner, with_trace_data: str, fmt: str):
        result = runner.invoke(cli, ["--format", fmt, "mission", "status"])
        assert result.exit_code == 0, f"exit {result.exit_code}: {result.output}"
        self._assert_format(fmt, result.output, "mission status")

    # ── mission logs ───────────────────────────────────────────────────

    @pytest.mark.parametrize("fmt", ["interactive", "plain", "json"])
    def test_mission_logs_default(self, runner: CliRunner, with_trace_data: str, fmt: str):
        result = runner.invoke(cli, ["--format", fmt, "mission", "logs"])
        assert result.exit_code == 0, f"exit {result.exit_code}: {result.output}"
        self._assert_format(fmt, result.output, "mission logs")

    # ── format assertions ──────────────────────────────────────────────

    @staticmethod
    def _assert_format(fmt: str, output: str, command: str) -> None:
        assert output, f"{command} / {fmt}: output was empty"
        if fmt == "json":
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError as e:
                pytest.fail(f"{command} / json: not valid JSON — {e}")
            assert isinstance(parsed, dict), f"expected dict, got {type(parsed).__name__}"
            if command == "mission list":
                assert "schema" in parsed, f"{command}: missing schema in JSON output"
            elif command == "mission status":
                assert "mission_id" in parsed, f"{command}: missing mission_id in JSON output"
            elif command == "mission logs":
                assert (
                    "schema" in parsed or "events" in parsed
                ), f"{command}: missing schema/events in JSON output"
        elif fmt == "plain":
            # plain: one of "ID\tPROBLEM\tPHASE..." (list) or "key=value" (status) or "ts agent state summary" (logs)
            assert len(output.splitlines()) > 0, f"{command} / plain: no lines"
        elif fmt == "interactive":
            # interactive: ANSI-rich output — at minimum non-empty
            pass

    # ── registry parity smoke ──────────────────────────────────────────

    def test_registry_has_mission_commands(self):
        for name in ("mission new", "mission list", "mission status", "mission logs"):
            cmd = get_command(name)
            assert cmd is not None, f"{name} missing from registry"
            assert cmd.implemented, f"{name} not marked implemented"

    def test_registry_has_model_commands(self):
        for name in ("model list", "model export", "model inspect"):
            cmd = get_command(name)
            assert cmd is not None, f"{name} missing from registry"
            assert cmd.implemented, f"{name} not marked implemented"

    @staticmethod
    def test_help_generates_for_mission():
        for name in ("mission list", "mission status", "mission logs", "mission new"):
            cmd = get_command(name)
            assert cmd is not None
            from click import Context
            from prometheus.main import cli

            click_cmd = cli.commands.get("mission")
            assert click_cmd is not None
            sub = click_cmd.commands.get(name.split()[1])
            assert sub is not None, f"No Click subcommand for {name}"
            ctx = Context(sub, info_name=name)
            help_text = sub.get_help(ctx)
            assert isinstance(help_text, str) and len(help_text) > 0

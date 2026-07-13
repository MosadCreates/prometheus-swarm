"""Unit tests for prometheus swarm CLI commands (solve, explain, replay, report)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from prometheus.main import cli

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_job_status():
    return {
        "job_id": "abc12345-0000-0000-0000-000000000000",
        "status": "COMPLETED",
        "current_agent": "Harbor",
        "crash_count": 0,
    }


@pytest.fixture
def sample_mission_brief():
    return {
        "problem_description": "Predict survival on Titanic dataset",
        "task_type": "classification",
        "modality": "tabular",
        "evaluation_metric": "auc_roc",
        "dataset": {"file_path": "/data/titanic.csv", "num_rows": 891, "num_columns": 12},
    }


@pytest.fixture
def sample_engineering_plan():
    return {
        "architecture_selected": {
            "name": "lightgbm",
            "expected_training_minutes": 5,
            "expected_ram_mb": 256,
            "expected_metric_range": [0.75, 0.88],
            "reason_for_selection": "Fast and robust for small tabular data",
        },
        "preprocessing_pipeline": [{"name": "median_imputation", "library": "sklearn"}],
    }


# ===================================================================
# prometheus solve
# ===================================================================


@patch("orchestrator.job_queue.submit_job", new_callable=AsyncMock)
def test_solve_submits_job(mock_submit, runner, tmp_path):
    """solve submits a dataset and returns a job_id."""
    mock_submit.return_value = "abc12345-0000-0000-0000-000000000000"
    dataset = tmp_path / "test.csv"
    dataset.write_text("a,b,c\n1,2,3\n")

    result = runner.invoke(
        cli,
        ["solve", str(dataset), "--description", "Test problem", "--target-column", "c"],
    )
    assert result.exit_code == 0
    mock_submit.assert_awaited_once()
    args, _ = mock_submit.await_args
    assert args[0] == "Test problem"
    assert "test.csv" in args[1]
    assert "abc12345" in result.output


def test_solve_requires_description(runner, tmp_path):
    """solve fails with a clear error when --description is missing."""
    dataset = tmp_path / "test.csv"
    dataset.write_text("a,b,c\n1,2,3\n")
    result = runner.invoke(cli, ["solve", str(dataset)])
    assert result.exit_code != 0
    assert "description" in result.output.lower()


def test_solve_requires_existing_dataset(runner):
    """solve fails with a clear error when dataset does not exist."""
    result = runner.invoke(cli, ["solve", "/nonexistent/path.csv", "--description", "test"])
    assert result.exit_code != 0
    assert "does not exist" in result.output.lower() or "path" in result.output.lower()


@patch("orchestrator.job_queue.submit_job", new_callable=AsyncMock)
def test_solve_handles_submission_failure(mock_submit, runner, tmp_path):
    """solve gracefully reports an error when submission fails."""
    mock_submit.side_effect = RuntimeError("Redis connection failed")
    dataset = tmp_path / "test.csv"
    dataset.write_text("a,b,c\n1,2,3\n")

    result = runner.invoke(cli, ["solve", str(dataset), "--description", "Test problem"])
    assert result.exit_code != 0
    assert "Redis" in result.output or "failed" in result.output


# ===================================================================
# prometheus explain
# ===================================================================


@patch("prometheus.cli.explain.asyncio.run")
def test_explain_shows_job_status(mock_asyncio_run, runner):
    """explain renders job status and mission brief for an existing job."""
    mock_asyncio_run.return_value = {
        "status": {
            "job_id": "abc12345-0000-0000-0000-000000000000",
            "status": "COMPLETED",
            "current_agent": "Harbor",
            "crash_count": 0,
        },
        "mission_brief": {
            "problem_description": "Predict survival on Titanic dataset",
            "task_type": "classification",
            "modality": "tabular",
        },
        "engineering_plan": {
            "architecture_selected": {"name": "lightgbm"},
        },
        "training_complete": {
            "best_val_metric": 0.854,
            "total_epochs": 50,
            "total_crashes": 0,
        },
    }

    result = runner.invoke(cli, ["explain", "abc12345"])
    assert result.exit_code == 0
    assert "COMPLETED" in result.output
    assert "lightgbm" in result.output
    assert "0.854" in result.output
    assert "Harbor" in result.output


@patch("prometheus.cli.explain.asyncio.run")
def test_explain_job_not_found(mock_asyncio_run, runner):
    """explain returns a clear error for an unknown job_id."""
    mock_asyncio_run.return_value = None

    result = runner.invoke(cli, ["explain", "nonexistent"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower()


@patch("prometheus.cli.explain.asyncio.run")
def test_explain_shows_patch_history(mock_asyncio_run, runner, tmp_path):
    """explain renders patch entries from patch_log.jsonl for the job."""
    job_id = "abc12345-0000-0000-0000-000000000000"
    mock_asyncio_run.return_value = {
        "status": {
            "job_id": job_id,
            "status": "COMPLETED",
            "current_agent": "Arbiter",
            "crash_count": 1,
        },
        "mission_brief": {},
        "engineering_plan": {},
        "training_complete": {},
    }

    patch_data = (
        json.dumps(
            {
                "patch_id": "p1",
                "job_id": job_id,
                "exception_type": "ValueError",
                "error_category": "shape_mismatch",
                "repair_strategy_used": "Re-align feature list",
                "patch_outcome": "success",
            }
        )
        + "\n"
        + json.dumps(
            {
                "patch_id": "p2",
                "job_id": job_id,
                "exception_type": "MemoryError",
                "error_category": "oom",
                "repair_strategy_used": "Reduce batch size",
                "patch_outcome": "rollback",
            }
        )
        + "\n"
    )

    # Write test patch data to the actual patch_log.jsonl, saving original
    patch_path = Path("research") / "patch_log.jsonl"
    original = patch_path.read_text() if patch_path.exists() else None
    patch_path.write_text(patch_data)

    try:
        result = runner.invoke(cli, ["explain", job_id[:8]])
        assert result.exit_code == 0
        assert "ValueError" in result.output or "Patch History" in result.output
    finally:
        if original is not None:
            patch_path.write_text(original)
        else:
            patch_path.unlink(missing_ok=True)


# ===================================================================
# prometheus replay
# ===================================================================


@patch("prometheus.cli.replay.asyncio.run")
def test_replay_shows_events(mock_asyncio_run, runner):
    """replay renders agent events for a given job_id."""
    mock_asyncio_run.return_value = 1  # event count

    result = runner.invoke(cli, ["replay", "abc12345"])
    assert result.exit_code == 0
    assert "event" in result.output.lower()


# ===================================================================
# prometheus report
# ===================================================================


@patch("orchestrator.mission_report.generate_mission_report", new_callable=AsyncMock)
@patch("memory.redis_client.RedisClient.connect", new_callable=AsyncMock)
@patch("memory.redis_client.RedisClient.close", new_callable=AsyncMock)
def test_report_generates(mock_close, mock_connect, mock_generate, runner, tmp_path, monkeypatch):
    """report generates the mission report and confirms success."""
    monkeypatch.chdir(tmp_path)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    json_path = outputs_dir / "mission_report_abc12345.json"
    json_path.write_text(json.dumps({"status": "COMPLETED", "job_id": "abc12345"}))
    mock_generate.return_value = str(json_path)

    result = runner.invoke(cli, ["report", "abc12345"])
    assert result.exit_code == 0
    assert "generated" in result.output.lower()


@patch("orchestrator.mission_report.generate_mission_report", new_callable=AsyncMock)
@patch("memory.redis_client.RedisClient.connect", new_callable=AsyncMock)
@patch("memory.redis_client.RedisClient.close", new_callable=AsyncMock)
def test_report_view_markdown(
    mock_close, mock_connect, mock_generate, runner, tmp_path, monkeypatch
):
    """report --view renders the markdown report in the terminal."""
    monkeypatch.chdir(tmp_path)
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    md_path = outputs_dir / "mission_report_abc12345.md"
    md_path.write_text("# Mission Report\n\nTest report content")
    json_path = outputs_dir / "mission_report_abc12345.json"
    json_path.write_text("{}")
    mock_generate.return_value = str(json_path)

    result = runner.invoke(cli, ["report", "abc12345", "--view"])
    assert result.exit_code == 0
    assert "Mission Report" in result.output


@patch("orchestrator.mission_report.generate_mission_report", new_callable=AsyncMock)
def test_report_handles_generation_failure(mock_generate, runner):
    """report gracefully handles a generation error."""
    mock_generate.side_effect = RuntimeError("Redis not available")

    result = runner.invoke(cli, ["report", "abc12345"])
    assert result.exit_code != 0
    assert "Redis" in result.output or "failed" in result.output


# ===================================================================
# CLI aliases
# ===================================================================


def test_cli_aliases_help_shows_all(runner):
    """--help lists the new commands and their aliases."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd_name in ("solve", "explain", "replay", "report"):
        assert cmd_name in result.output

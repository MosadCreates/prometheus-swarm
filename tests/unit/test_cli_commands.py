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
# CLI help and redirect stubs
# ===================================================================


def test_cli_help_shows_current_commands(runner):
    """--help lists the current visible commands."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd_name in ("mission", "agent", "workspace", "model", "config", "doctor", "version"):
        assert cmd_name in result.output

"""Tests for research/validation/runner.py — lightweight, no actual benchmark execution."""

import pytest

from research.validation.models import (
    ExperimentRun,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)
from research.validation.runner import (
    _cleanup,
    _ensure_dataset,
    _make_failed_run,
    _raw_to_run,
    run_benchmark_batch,
)


class TestRawToRun:
    def test_pass_result(self):
        raw = {
            "status": "pass",
            "decision": "pass",
            "best_val_metric": 0.92,
            "architecture": "lightgbm",
            "duration_seconds": 15.0,
        }
        run = _raw_to_run({"id": "P1"}, "job-123", ResearchHypothesis.H2, raw, t0=100.0)
        assert run.problem_id == "P1"
        assert run.job_id == "job-123"
        assert run.hypothesis == ResearchHypothesis.H2
        assert run.research_metrics.deployment_success is True
        assert run.research_metrics.final_metric == 0.92
        assert run.system_metrics.duration_seconds == 15.0

    def test_fail_result(self):
        raw = {
            "status": "crash",
            "decision": "",
            "error": "ValueError: shape mismatch",
            "crash_count": 1,
        }
        run = _raw_to_run({"id": "P2"}, "job-456", ResearchHypothesis.H2, raw, t0=100.0)
        assert run.research_metrics.deployment_success is False
        assert run.execution_outcome["status"] == "crash"
        assert "shape mismatch" in run.execution_outcome["error"]

    def test_with_h3_patches(self):
        raw = {
            "status": "pass",
            "decision": "pass",
            "best_val_metric": 0.88,
            "crash_count": 2,
            "patch_successes": 1,
        }
        run = _raw_to_run({"id": "P3"}, "job-789", ResearchHypothesis.H3, raw, t0=100.0)
        assert run.system_metrics.crashes == 2
        assert run.system_metrics.crashes_recovered == 1

    def test_with_wall_clock(self):
        import time

        t0 = time.time()
        import time as time_module

        raw = {"status": "pass", "decision": "pass", "duration_seconds": 5.0}
        run = _raw_to_run({"id": "P4"}, "job-wall", ResearchHypothesis.H1, raw, t0)
        assert run.system_metrics.wall_clock_time_s >= 0


class TestMakeFailedRun:
    def test_creates_failed_run(self):
        import time

        t0 = time.time()
        run = _make_failed_run(
            {"id": "P1"}, "job-fail", ResearchHypothesis.H2, "Something broke", t0
        )
        assert run.execution_outcome["status"] == "failed"
        assert run.execution_outcome["error"] == "Something broke"
        assert run.system_metrics.wall_clock_time_s >= 0


class TestEnsureDataset:
    @pytest.mark.asyncio
    async def test_no_dataset_returns_false(self):
        # With no actual dataset, should return False
        result = await _ensure_dataset(
            {"id": "NOEXIST", "dataset": {"source": "custom", "path": "/nonexistent.csv"}}
        )
        assert result is False


class TestCleanup:
    def test_cleanup_nonexistent_files(self, tmp_path):
        # Should not raise for nonexistent files
        _cleanup("/nonexistent/script.py", "nonexistent-job")


class TestRunBenchmarkBatch:
    @pytest.mark.asyncio
    async def test_empty_problems(self):
        result = await run_benchmark_batch([], conditions="B", experiment_name="empty_test")
        assert result.name == "empty_test"
        assert len(result.experiments) == 1

    @pytest.mark.asyncio
    async def test_no_dataset(self):
        problems = [
            {
                "id": "TEST",
                "problem_description": "test",
                "dataset": {"source": "custom", "path": "/notfound.csv", "name": "test"},
                "task_type": "classification",
                "modality": "tabular",
                "target_column": "target",
                "difficulty": "easy",
            }
        ]
        result = await run_benchmark_batch(
            problems, conditions="B", experiment_name="no_dataset_test"
        )
        assert result.name == "no_dataset_test"

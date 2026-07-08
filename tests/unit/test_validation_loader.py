"""Tests for research/validation/loader.py."""

import json
from pathlib import Path

import pytest

from research.validation.models import ExperimentRun

from research.validation.loader import (
    load_all_experiments_from_directory,
    load_from_baseline,
    load_from_batch_file,
    merge_into_set,
    runtime_run_from_dict,
)
from research.validation.models import (
    Experiment,
    ExperimentSet,
    FailureCategory,
    ResearchHypothesis,
)


class TestLoadFromBaseline:
    def test_load_baseline_b(self, tmp_path: Path):
        baseline = _make_baseline({"pass": 2, "crash": 1})
        path = _write_json(tmp_path, "baseline_v1.json", baseline)

        exp = load_from_baseline(str(path), "condition_b", ResearchHypothesis.H2)
        assert exp.hypothesis == ResearchHypothesis.H2
        assert len(exp.runs) == 3
        assert sum(1 for r in exp.runs if r.execution_outcome["decision"] == "pass") == 2

    def test_load_baseline_c(self, tmp_path: Path):
        baseline = _make_baseline({"pass": 1, "retry": 1, "escalate": 1})
        path = _write_json(tmp_path, "baseline_c.json", baseline)

        exp = load_from_baseline(str(path), "condition_c", ResearchHypothesis.H3)
        assert exp.hypothesis == ResearchHypothesis.H3
        assert len(exp.runs) == 3

    def test_load_baseline_creates_system_metrics(self, tmp_path: Path):
        baseline = _make_baseline({"pass": 1})
        baseline["condition_b"]["results"][0]["duration_seconds"] = 42.5
        path = _write_json(tmp_path, "baseline.json", baseline)

        exp = load_from_baseline(str(path))
        assert exp.runs[0].system_metrics.duration_seconds == 42.5

    def test_load_baseline_failure_category(self, tmp_path: Path):
        baseline = _make_baseline({"crash": 1})
        path = _write_json(tmp_path, "baseline.json", baseline)

        exp = load_from_baseline(str(path), "condition_b", ResearchHypothesis.H2)
        assert exp.runs[0].failure_category == FailureCategory.TRAINING

    def test_load_baseline_escalate_category(self, tmp_path: Path):
        baseline = _make_baseline({"escalate": 1})
        path = _write_json(tmp_path, "baseline.json", baseline)

        exp = load_from_baseline(str(path), "condition_b", ResearchHypothesis.H2)
        assert exp.runs[0].failure_category == FailureCategory.UNKNOWN


class TestLoadFromBatchFile:
    def test_load_batch_simple(self, tmp_path: Path):
        data = {
            "results": [
                {
                    "problem_id": "P1",
                    "status": "pass",
                    "decision": "pass",
                    "best_val_metric": 0.9,
                    "duration_seconds": 10,
                },
                {"problem_id": "P2", "status": "crash", "error": "CUDA OOM"},
            ]
        }
        path = _write_json(tmp_path, "batch_P1.json", data)
        exp = load_from_batch_file(str(path), ResearchHypothesis.H3)
        assert len(exp.runs) == 2
        assert exp.runs[0].research_metrics.deployment_success is True
        assert exp.runs[1].research_metrics.deployment_success is False

    def test_load_empty_batch(self, tmp_path: Path):
        data = {"results": []}
        path = _write_json(tmp_path, "empty.json", data)
        exp = load_from_batch_file(str(path))
        assert len(exp.runs) == 0

    def test_load_batch_with_metrics(self, tmp_path: Path):
        data = {
            "runs": [
                {"problem_id": "P1", "status": "pass", "best_val_metric": 0.92, "crash_count": 0},
            ]
        }
        path = _write_json(tmp_path, "batch.json", data)
        exp = load_from_batch_file(str(path))
        assert exp.runs[0].research_metrics.final_metric == 0.92


class TestLoadAllFromDirectory:
    def test_load_mixed_format(self, tmp_path: Path):
        # Baseline
        _write_json(tmp_path, "baseline.json", _make_baseline({"pass": 2, "crash": 1}))
        # Batch
        _write_json(tmp_path, "batch.json", {"results": [{"problem_id": "P1", "status": "pass"}]})
        # Non-experiment JSON (should be ignored or gracefully handled)
        _write_json(tmp_path, "not_experiment.json", {"key": "value"})

        exps = load_all_experiments_from_directory(str(tmp_path))
        assert len(exps) >= 1  # at least 1 experiment loaded

    def test_load_nonexistent_dir(self):
        exps = load_all_experiments_from_directory("/nonexistent/xyz")
        assert exps == []


class TestMergeIntoSet:
    def test_merge_same_hypothesis(self):
        e1 = Experiment(hypothesis=ResearchHypothesis.H2, runs=[ExperimentRun()])
        e2 = Experiment(hypothesis=ResearchHypothesis.H2, runs=[ExperimentRun()])
        merged = merge_into_set([e1, e2], "merged")
        assert "H2" in merged.experiments
        assert len(merged.experiments["H2"].runs) == 2

    def test_merge_different_hypotheses(self):
        e1 = Experiment(hypothesis=ResearchHypothesis.H1, runs=[ExperimentRun(problem_id="P1")])
        e2 = Experiment(hypothesis=ResearchHypothesis.H2, runs=[ExperimentRun(problem_id="P1")])
        merged = merge_into_set([e1, e2], "multi")
        assert len(merged.experiments) == 2

    def test_merge_empty(self):
        merged = merge_into_set([], "empty")
        assert len(merged.experiments) == 0


class TestRuntimeRunFromDict:
    def test_minimal_dict(self):
        run = runtime_run_from_dict({"job_id": "test-123"})
        assert run.job_id == "test-123"
        assert run.hypothesis == ResearchHypothesis.H2
        assert run.system_metrics.duration_seconds == 0

    def test_full_dict(self):
        data = {
            "job_id": "test-456",
            "problem_id": "TX01",
            "system_metrics": {
                "duration_seconds": 30.0,
                "crashes": 2,
                "crashes_recovered": 1,
                "wall_clock_time_s": 35.0,
            },
            "research_metrics": {
                "final_metric": 0.87,
                "deployment_success": True,
            },
            "calibration": {
                "predicted_duration_minutes": 5,
                "actual_duration_minutes": 4.2,
                "planner_confidence": 0.85,
                "actual_deployment_success": True,
            },
        }
        run = runtime_run_from_dict(data, hypothesis=ResearchHypothesis.H3)
        assert run.hypothesis == ResearchHypothesis.H3
        assert run.system_metrics.duration_seconds == 30.0
        assert run.system_metrics.crashes == 2
        assert run.research_metrics.final_metric == 0.87
        assert run.calibration is not None
        assert run.calibration.predicted_duration_minutes == 5

    def test_with_learning_curve(self):
        data = {
            "job_id": "lc-test",
            "learning_curve": [
                {"evidence_count": 5, "prediction_error_pct": 10.0, "metric": "duration"},
                {"evidence_count": 10, "prediction_error_pct": 7.5, "metric": "duration"},
            ],
        }
        run = runtime_run_from_dict(data)
        assert len(run.learning_curve) == 2
        assert run.learning_curve[0].evidence_count == 5
        assert run.learning_curve[1].prediction_error_pct == 7.5

    def test_with_architecture_accuracy(self):
        data = {
            "architecture_accuracy": {
                "planner_chosen_architecture": "lightgbm",
                "historical_best_architecture": "xgboost",
                "planner_achieved_metric": 0.82,
                "historical_best_metric": 0.88,
                "selection_gap": 0.06,
            }
        }
        run = runtime_run_from_dict(data)
        assert run.architecture_accuracy is not None
        assert run.architecture_accuracy.selection_gap == 0.06

    def test_with_failure_category(self):
        data = {"failure_category": "training_failure"}
        run = runtime_run_from_dict(data)
        assert run.failure_category == FailureCategory.TRAINING

    def test_with_invalid_failure_category(self):
        data = {"failure_category": "nonexistent_category"}
        run = runtime_run_from_dict(data)
        assert run.failure_category is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_baseline(stats: dict) -> dict:
    results = []
    for status, count in stats.items():
        for _ in range(count):
            results.append(
                {
                    "problem_id": "P1",
                    "status": status,
                    "best_val_metric": 0.85 if status == "pass" else None,
                    "decision": "pass" if status == "pass" else "retry",
                    "duration_seconds": 10.0,
                    "crash_count": 1 if status == "crash" else 0,
                    "architecture": "lightgbm",
                }
            )
    return {
        "schema_version": "1.0",
        "condition_b": {"results": results},
        "condition_c": {"results": results},
    }


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data))
    return path

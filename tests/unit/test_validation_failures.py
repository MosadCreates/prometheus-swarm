"""Tests for research/validation/failures.py."""

import pytest

from research.validation.failures import (
    classify_all,
    classify_failure,
    generate_failure_report,
)
from research.validation.models import (
    ExperimentRun,
    FailureCategory,
    ResearchHypothesis,
)


class TestClassifyFailure:
    def test_no_failure_for_success(self):
        run = ExperimentRun(execution_outcome={"status": "success"})
        assert classify_failure(run) is None

    def test_no_failure_for_pass(self):
        run = ExperimentRun(execution_outcome={"status": "pass"})
        assert classify_failure(run) is None

    def test_oom_classification(self):
        run = ExperimentRun(
            execution_outcome={"status": "crash", "error": "CUDA out of memory. Tried to allocate"},
        )
        assert classify_failure(run) == FailureCategory.RESOURCE

    def test_training_crash(self):
        run = ExperimentRun(
            execution_outcome={"status": "crash", "error": "ValueError: shape mismatch"},
        )
        # "shape.*mismatch" maps to DATASET
        assert classify_failure(run) == FailureCategory.DATASET

    def test_dataset_error(self):
        run = ExperimentRun(
            execution_outcome={
                "status": "crash",
                "error": "FileNotFoundError: dataset.csv not found",
            },
        )
        assert classify_failure(run) == FailureCategory.DATASET

    def test_infrastructure_timeout(self):
        run = ExperimentRun(
            execution_outcome={"status": "timeout", "error": "Connection refused"},
        )
        assert classify_failure(run) == FailureCategory.INFRASTRUCTURE

    def test_convergence_failure(self):
        run = ExperimentRun(
            execution_outcome={
                "status": "crash",
                "error": "ConvergenceWarning: lbfgs failed to converge",
            },
        )
        assert classify_failure(run) == FailureCategory.CONVERGENCE

    def test_deployment_failure(self):
        run = ExperimentRun(
            execution_outcome={"status": "deploy_failed", "error": "Port 8080 already in use"},
        )
        assert classify_failure(run) == FailureCategory.DEPLOYMENT

    def test_unknown_failure(self):
        run = ExperimentRun(
            execution_outcome={"status": "crash", "error": "Weird obscure error no one has seen"},
        )
        # Falls through to status-based: "crash" => TRAINING
        assert classify_failure(run) == FailureCategory.TRAINING

    def test_import_error_as_planner(self):
        run = ExperimentRun(
            execution_outcome={
                "status": "crash",
                "error": "ModuleNotFoundError: No module named 'lightgbm'",
            },
        )
        assert classify_failure(run) == FailureCategory.PLANNER

    def test_preserves_existing_category(self):
        run = ExperimentRun(
            failure_category=FailureCategory.CONVERGENCE,
            execution_outcome={"status": "crash", "error": "random error"},
        )
        assert classify_failure(run) == FailureCategory.CONVERGENCE

    def test_no_error_text(self):
        run = ExperimentRun(execution_outcome={"status": "escalate"})
        assert classify_failure(run) is not None


class TestClassifyAll:
    def test_classifies_in_place(self):
        runs = [
            ExperimentRun(execution_outcome={"status": "success"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "CUDA OOM"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "some generic error"}),
        ]
        classify_all(runs)
        assert runs[0].failure_category is None
        assert runs[1].failure_category == FailureCategory.RESOURCE
        assert runs[2].failure_category == FailureCategory.TRAINING  # falls to status-based


class TestGenerateFailureReport:
    def test_no_failures(self):
        runs = [
            ExperimentRun(execution_outcome={"status": "success"}),
            ExperimentRun(execution_outcome={"status": "pass"}),
        ]
        report = generate_failure_report(runs)
        assert report.total_failed == 0
        assert report.categories == {}

    def test_mixed_failures(self):
        runs = [
            ExperimentRun(execution_outcome={"status": "crash", "error": "CUDA OOM"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "ValueError"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "CUDA OOM again"}),
            ExperimentRun(execution_outcome={"status": "success"}),
        ]
        report = generate_failure_report(runs)
        assert report.total_failed == 3
        assert report.categories.get("resource_exhaustion", 0) == 2
        assert report.categories.get("training_failure", 0) == 1

    def test_percentages(self):
        runs = [
            ExperimentRun(execution_outcome={"status": "crash", "error": "CUDA OOM"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "CUDA OOM"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "ValueError"}),
            ExperimentRun(execution_outcome={"status": "crash", "error": "Missing column"}),
            ExperimentRun(execution_outcome={"status": "success"}),
        ]
        report = generate_failure_report(runs)
        total = len(runs)
        # CUDA OOM -> RESOURCE (2), Missing column -> DATASET (1), ValueError -> TRAINING (1 - falls to status)
        assert report.category_percentages.get("resource_exhaustion", 0) == pytest.approx(
            2 / total * 100, abs=0.1
        )
        assert report.category_percentages.get("training_failure", 0) == pytest.approx(
            1 / total * 100, abs=0.1
        )

    def test_representative_examples_count(self):
        runs = []
        for i in range(10):
            runs.append(
                ExperimentRun(
                    problem_id=f"P{i}",
                    execution_outcome={"status": "crash", "error": f"Error {i}"},
                )
            )
        report = generate_failure_report(runs)
        assert len(report.representative_examples) <= 5

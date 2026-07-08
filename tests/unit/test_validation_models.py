"""Tests for research/validation/models.py."""

import uuid
from datetime import datetime, timezone

import pytest

from research.validation.models import (
    ArchitectureSelectionAccuracy,
    ComparisonResult,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    FailureCategory,
    FailureReport,
    LearningCurvePoint,
    PlanningCalibration,
    ResearchHypothesis,
    ResearchMetrics,
    ResearchQuestion,
    SystemMetrics,
)


class TestEnums:
    def test_research_hypothesis_values(self):
        assert ResearchHypothesis.H1.value == "H1"
        assert ResearchHypothesis.H2.value == "H2"
        assert ResearchHypothesis.H3.value == "H3"

    def test_research_question_values(self):
        assert ResearchQuestion.RQ1.value == "RQ1"
        assert ResearchQuestion.RQ5.value == "RQ5"

    def test_failure_category_values(self):
        assert FailureCategory.PLANNER.value == "planner_failure"
        assert FailureCategory.UNKNOWN.value == "unknown"


class TestSystemMetrics:
    def test_defaults(self):
        sm = SystemMetrics()
        assert sm.duration_seconds == 0
        assert sm.retries == 0
        assert sm.crashes == 0
        assert sm.crashes_recovered == 0
        assert sm.peak_ram_mb is None
        assert sm.peak_gpu_mb is None

    def test_round_trip(self):
        sm = SystemMetrics(
            duration_seconds=42.5,
            retries=2,
            crashes=1,
            crashes_recovered=1,
            peak_ram_mb=2048.0,
        )
        d = sm.model_dump()
        assert d["duration_seconds"] == 42.5
        assert d["peak_ram_mb"] == 2048.0
        restored = SystemMetrics(**d)
        assert restored.duration_seconds == 42.5


class TestResearchMetrics:
    def test_defaults(self):
        rm = ResearchMetrics()
        assert rm.prediction_error_duration_pct is None
        assert rm.deployment_success is None

    def test_deployment_success(self):
        rm = ResearchMetrics(deployment_success=True, final_metric=0.94)
        assert rm.deployment_success is True
        assert rm.final_metric == 0.94


class TestExperimentRun:
    def test_default_run_id(self):
        run = ExperimentRun()
        assert len(run.run_id) == 8

    def test_hypothesis_error_defaults(self):
        run = ExperimentRun()
        assert run.hypothesis == ResearchHypothesis.H1

    def test_full_construction(self):
        run = ExperimentRun(
            job_id="job-123",
            problem_id="IC01",
            hypothesis=ResearchHypothesis.H2,
            system_metrics=SystemMetrics(duration_seconds=10.0, crashes=1),
            research_metrics=ResearchMetrics(final_metric=0.85, deployment_success=True),
            failure_category=FailureCategory.TRAINING,
        )
        assert run.job_id == "job-123"
        assert run.problem_id == "IC01"
        assert run.hypothesis == ResearchHypothesis.H2
        assert run.system_metrics.duration_seconds == 10.0
        assert run.research_metrics.final_metric == 0.85
        assert run.failure_category == FailureCategory.TRAINING


class TestExperiment:
    def test_default_hypothesis(self):
        exp = Experiment(hypothesis=ResearchHypothesis.H1)
        assert exp.hypothesis == ResearchHypothesis.H1
        assert len(exp.runs) == 0

    def test_add_runs(self):
        exp = Experiment(hypothesis=ResearchHypothesis.H2, name="test")
        run = ExperimentRun(problem_id="P1")
        exp.runs.append(run)
        assert len(exp.runs) == 1


class TestExperimentSet:
    def test_empty_set(self):
        s = ExperimentSet(name="test")
        assert s.name == "test"
        assert s.h1 is None
        assert s.h2 is None
        assert s.h3 is None

    def test_with_experiments(self):
        s = ExperimentSet(name="test")
        s.experiments["H1"] = Experiment(hypothesis=ResearchHypothesis.H1)
        s.experiments["H2"] = Experiment(hypothesis=ResearchHypothesis.H2)
        assert s.h1 is not None
        assert s.h2 is not None
        assert s.h3 is None

    def test_round_trip_serialization(self):
        s = ExperimentSet(name="roundtrip")
        s.experiments["H1"] = Experiment(
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun(problem_id="P1")],
        )
        d = s.model_dump()
        restored = ExperimentSet(**d)
        assert restored.name == "roundtrip"
        assert "H1" in restored.experiments
        assert len(restored.experiments["H1"].runs) == 1


class TestComparisonResult:
    def test_defaults(self):
        cr = ComparisonResult()
        assert cr.metric_name == ""
        assert cr.significant is False

    def test_significance_detection(self):
        cr = ComparisonResult(
            metric_name="duration",
            p_value=0.03,
            effect_size=0.8,
            significant=True,
        )
        assert cr.significant is True
        assert cr.p_value == 0.03


class TestPlanningCalibration:
    def test_fields(self):
        pc = PlanningCalibration(
            predicted_duration_minutes=10,
            actual_duration_minutes=12.5,
            planner_confidence=0.75,
            actual_deployment_success=True,
        )
        assert pc.predicted_duration_minutes == 10
        assert pc.actual_duration_minutes == 12.5
        assert pc.planner_confidence == 0.75


class TestArchitectureSelectionAccuracy:
    def test_defaults(self):
        a = ArchitectureSelectionAccuracy()
        assert a.planner_chosen_architecture == ""
        assert a.selection_gap is None

    def test_gap_computation(self):
        a = ArchitectureSelectionAccuracy(
            planner_chosen_architecture="lightgbm",
            historical_best_architecture="xgboost",
            planner_achieved_metric=0.82,
            historical_best_metric=0.88,
            selection_gap=0.06,
        )
        assert a.selection_gap == 0.06


class TestLearningCurvePoint:
    def test_default_metric(self):
        pt = LearningCurvePoint(evidence_count=10, prediction_error_pct=5.2)
        assert pt.evidence_count == 10
        assert pt.prediction_error_pct == 5.2
        assert pt.metric == "duration"


class TestFailureReport:
    def test_empty(self):
        fr = FailureReport()
        assert fr.total_failed == 0
        assert fr.categories == {}

    def test_with_data(self):
        fr = FailureReport(
            total_failed=5,
            categories={"training": 3, "dataset": 2},
            category_percentages={"training": 60.0, "dataset": 40.0},
        )
        assert fr.total_failed == 5
        assert fr.categories["training"] == 3

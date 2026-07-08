"""Tests for research/validation/metrics.py."""

import pytest

from research.validation.metrics import (
    aggregate_research_metrics,
    aggregate_system_metrics,
    compute_research_metrics,
    compute_system_metrics,
    summarize_experiment,
    summarize_set,
)
from research.validation.models import (
    Experiment,
    ExperimentRun,
    ExperimentSet,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)


class TestComputeSystemMetrics:
    def test_empty_outcome(self):
        sm = compute_system_metrics({})
        assert sm.duration_seconds == 0
        assert sm.retries == 0

    def test_with_data(self):
        outcome = {
            "total_plan_duration_s": 60.0,
            "retry_count": 2,
            "crash_count": 1,
            "crashes_recovered": 1,
            "peak_ram_mb": 1024.0,
        }
        sm = compute_system_metrics(outcome)
        assert sm.duration_seconds == 60.0
        assert sm.retries == 2

    def test_uses_alternative_keys(self):
        outcome = {"duration_seconds": 30.0, "retries": 3}
        sm = compute_system_metrics(outcome)
        assert sm.duration_seconds == 30.0
        assert sm.retries == 3

    def test_handles_none_values(self):
        outcome = {"duration_seconds": None, "crash_count": 0}
        sm = compute_system_metrics(outcome)
        assert sm.duration_seconds == 0
        assert sm.crashes == 0


class TestComputeResearchMetrics:
    def test_pass_decision(self):
        outcome = {"decision": "pass", "best_val_metric": 0.9}
        rm = compute_research_metrics(outcome)
        assert rm.deployment_success is True
        assert rm.actual_success is True
        assert rm.final_metric == 0.9

    def test_fail_decision(self):
        outcome = {"decision": "retry", "best_val_metric": 0.6}
        rm = compute_research_metrics(outcome)
        assert rm.deployment_success is False
        assert rm.actual_success is False

    def test_with_prediction_error(self):
        outcome = {"decision": "pass", "best_val_metric": 0.85}
        pred = {"duration_pct": 12.5, "planner_confidence": 0.75}
        rm = compute_research_metrics(outcome, pred)
        assert rm.prediction_error_duration_pct == 12.5
        assert rm.planner_confidence_score == 0.75

    def test_patch_rate(self):
        outcome = {
            "patch_attempts": 4,
            "patch_successes": 3,
        }
        rm = compute_research_metrics(outcome)
        assert rm.patch_success_rate == 0.75

    def test_no_patches(self):
        outcome = {}
        rm = compute_research_metrics(outcome)
        assert rm.patch_success_rate is None


class TestAggregateSystemMetrics:
    def test_empty_runs(self):
        assert aggregate_system_metrics([]) == {}

    def test_single_run(self):
        runs = [ExperimentRun(system_metrics=SystemMetrics(duration_seconds=10.0))]
        agg = aggregate_system_metrics(runs)
        assert agg["count"] == 1
        assert agg["duration"]["mean"] == 10.0

    def test_multiple_runs(self):
        runs = [
            ExperimentRun(system_metrics=SystemMetrics(duration_seconds=10.0, retries=1)),
            ExperimentRun(system_metrics=SystemMetrics(duration_seconds=20.0, retries=3)),
        ]
        agg = aggregate_system_metrics(runs)
        assert agg["count"] == 2
        assert agg["duration"]["mean"] == 15.0
        assert agg["duration"]["min"] == 10.0
        assert agg["duration"]["max"] == 20.0
        assert agg["retries"]["mean"] == 2.0

    def test_with_peak_ram(self):
        runs = [
            ExperimentRun(system_metrics=SystemMetrics(peak_ram_mb=512.0)),
            ExperimentRun(system_metrics=SystemMetrics(peak_ram_mb=1024.0)),
        ]
        agg = aggregate_system_metrics(runs)
        assert "peak_ram_mb" in agg
        assert agg["peak_ram_mb"]["mean"] == 768.0


class TestAggregateResearchMetrics:
    def test_empty_runs(self):
        assert aggregate_research_metrics([]) == {}

    def test_deployment_success_rate(self):
        runs = [
            ExperimentRun(research_metrics=ResearchMetrics(deployment_success=True)),
            ExperimentRun(research_metrics=ResearchMetrics(deployment_success=True)),
            ExperimentRun(research_metrics=ResearchMetrics(deployment_success=False)),
        ]
        agg = aggregate_research_metrics(runs)
        assert agg["deployment_success_rate"] == 2 / 3

    def test_all_failed(self):
        runs = [
            ExperimentRun(research_metrics=ResearchMetrics(deployment_success=False)),
        ]
        agg = aggregate_research_metrics(runs)
        assert agg["deployment_success_rate"] == 0.0

    def test_final_metric_mean(self):
        runs = [
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.8)),
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.9)),
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.7)),
        ]
        agg = aggregate_research_metrics(runs)
        assert agg["final_metric"]["mean"] == 0.8


class TestSummarize:
    def test_summarize_experiment(self):
        exp = Experiment(
            name="test",
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun(), ExperimentRun()],
        )
        summary = summarize_experiment(exp)
        assert summary["run_count"] == 2
        assert summary["hypothesis"] == "H1"

    def test_summarize_set(self):
        s = ExperimentSet(name="test_set")
        s.experiments["H1"] = Experiment(
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun()],
        )
        summary = summarize_set(s)
        assert "H1" in summary["hypotheses"]
        assert summary["set_id"] == s.set_id

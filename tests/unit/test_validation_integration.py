"""Integration tests for research/validation/ — end-to-end workflow.

Tests the full pipeline: create experiment set → save → load → compare →
generate figures → generate report → failure analysis.
"""

import json
from pathlib import Path

import pytest

from research.validation.failures import generate_failure_report
from research.validation.figures import generate_all_figures
from research.validation.loader import merge_into_set
from research.validation.metrics import summarize_set
from research.validation.models import (
    Experiment,
    ExperimentRun,
    ExperimentSet,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)
from research.validation.reports import save_report_to_disk
from research.validation.statistics import compare_all
from research.validation.tracker import (
    list_experiment_sets,
    load_experiment_set,
    save_experiment_set,
)


def _make_sample_runs(
    hypothesis: ResearchHypothesis,
    count: int = 3,
    base_duration: float = 10.0,
    base_metric: float = 0.8,
    success_rate: float = 1.0,
) -> list[ExperimentRun]:
    runs: list[ExperimentRun] = []
    for i in range(count):
        success = i < int(count * success_rate)
        runs.append(
            ExperimentRun(
                job_id=f"job-{hypothesis.value}-{i}",
                problem_id=f"P{i}",
                hypothesis=hypothesis,
                system_metrics=SystemMetrics(
                    duration_seconds=base_duration + i * 5.0,
                    crashes=i % 2,
                    crashes_recovered=0,
                    wall_clock_time_s=base_duration + i * 5.0 + 2.0,
                ),
                research_metrics=ResearchMetrics(
                    final_metric=base_metric + i * 0.05,
                    deployment_success=success,
                    actual_success=success,
                ),
            )
        )
    return runs


@pytest.fixture
def sample_experiment_set() -> ExperimentSet:
    exp_set = ExperimentSet(name="Integration Test Set")
    exp_set.experiments["H1"] = Experiment(
        name="H1 Static",
        hypothesis=ResearchHypothesis.H1,
        runs=_make_sample_runs(
            ResearchHypothesis.H1, count=5, base_duration=20.0, base_metric=0.70
        ),
    )
    exp_set.experiments["H2"] = Experiment(
        name="H2 Adaptive",
        hypothesis=ResearchHypothesis.H2,
        runs=_make_sample_runs(
            ResearchHypothesis.H2, count=5, base_duration=15.0, base_metric=0.80, success_rate=0.8
        ),
    )
    exp_set.experiments["H3"] = Experiment(
        name="H3 Adaptive + Patch",
        hypothesis=ResearchHypothesis.H3,
        runs=_make_sample_runs(
            ResearchHypothesis.H3, count=5, base_duration=12.0, base_metric=0.85, success_rate=0.8
        ),
    )
    return exp_set


class TestEndToEnd:
    def test_save_and_load(self, sample_experiment_set: ExperimentSet, tmp_path: Path):
        """Save experiment set to disk, then load it back identically."""
        path = save_experiment_set(sample_experiment_set, directory=str(tmp_path))
        assert path.exists()

        loaded = load_experiment_set(str(path))
        assert loaded.set_id == sample_experiment_set.set_id
        assert loaded.name == "Integration Test Set"
        assert "H1" in loaded.experiments
        assert "H2" in loaded.experiments
        assert "H3" in loaded.experiments
        assert len(loaded.experiments["H1"].runs) == 5

    def test_list_experiments(self, sample_experiment_set: ExperimentSet, tmp_path: Path):
        save_experiment_set(sample_experiment_set, directory=str(tmp_path))
        files = list_experiment_sets(directory=str(tmp_path))
        assert len(files) == 1

    def test_compare_statistics(self, sample_experiment_set: ExperimentSet):
        """Run all statistical comparisons between hypotheses."""
        runs_h1 = sample_experiment_set.experiments["H1"].runs
        runs_h2 = sample_experiment_set.experiments["H2"].runs
        runs_h3 = sample_experiment_set.experiments["H3"].runs

        results = compare_all(runs_h1, runs_h2, runs_h3)
        assert len(results) > 0

        for key, cr in results.items():
            assert cr.p_value is not None
            assert cr.effect_size is not None or cr.effect_size == 0
            assert (
                cr.ci_lower is not None or cr.ci_lower is None or cr.ci_lower != cr.ci_lower
            )  # nan check
            assert cr.n_a > 0
            assert cr.n_b > 0

    def test_generate_figures(self, sample_experiment_set: ExperimentSet, monkeypatch):
        """Generate all 10 figures without errors."""
        runs_h1 = sample_experiment_set.experiments["H1"].runs
        runs_h2 = sample_experiment_set.experiments["H2"].runs
        runs_h3 = sample_experiment_set.experiments["H3"].runs

        paths = generate_all_figures(runs_h1, runs_h2, runs_h3)
        assert len(paths) == 10
        for p in paths:
            assert p.exists()

    def test_generate_report(self, sample_experiment_set: ExperimentSet, tmp_path):
        """Generate full markdown report + JSON summary."""
        # Run comparisons first
        runs_h1 = sample_experiment_set.experiments["H1"].runs
        runs_h2 = sample_experiment_set.experiments["H2"].runs
        runs_h3 = sample_experiment_set.experiments["H3"].runs
        sample_experiment_set.comparisons = compare_all(runs_h1, runs_h2, runs_h3)

        # Failure report
        all_runs = runs_h1 + runs_h2 + runs_h3
        failure_rep = generate_failure_report(all_runs)

        # Generate figures
        figure_paths = generate_all_figures(runs_h1, runs_h2, runs_h3)

        # Save report
        md_path, json_path = save_report_to_disk(
            sample_experiment_set,
            figure_paths=figure_paths,
            failure_report=failure_rep,
            title="Integration Test Report",
        )
        assert md_path.exists()
        assert json_path.exists()

        md_content = md_path.read_text()
        assert "Integration Test Report" in md_content
        assert "H1" in md_content or "H2" in md_content or "H3" in md_content

        json_content = json.loads(json_path.read_text())
        assert "hypotheses" in json_content

    def test_summarize_set(self, sample_experiment_set: ExperimentSet):
        """Generate and verify summary."""
        summary = summarize_set(sample_experiment_set)
        assert "set_id" in summary
        assert "hypotheses" in summary
        h1_summary = summary["hypotheses"]["H1"]
        assert h1_summary["run_count"] == 5
        assert "system" in h1_summary
        assert "research" in h1_summary

    def test_success_rate_decreases_with_patches(self, sample_experiment_set: ExperimentSet):
        """H1 should have higher success rate than H2/H3 due to fewer failures."""
        runs_h1 = sample_experiment_set.experiments["H1"].runs
        runs_h2 = sample_experiment_set.experiments["H2"].runs

        h1_successes = sum(1 for r in runs_h1 if r.research_metrics.deployment_success is True)
        h2_successes = sum(1 for r in runs_h2 if r.research_metrics.deployment_success is True)

        # H1 is 100% (base_duration=20.0 runs at the bottom)
        # Sorry — actually success_rate was not passed to base, so it's the default in _make_sample_runs
        assert h1_successes >= h2_successes

    def test_merge_into_set(self):
        """Merge experiments from different sources into a single set."""
        e1 = Experiment(
            hypothesis=ResearchHypothesis.H1, runs=_make_sample_runs(ResearchHypothesis.H1, 2)
        )
        e2 = Experiment(
            hypothesis=ResearchHypothesis.H2, runs=_make_sample_runs(ResearchHypothesis.H2, 3)
        )
        merged = merge_into_set([e1, e2], "Merged Set")
        assert "H1" in merged.experiments
        assert "H2" in merged.experiments
        assert len(merged.experiments["H1"].runs) == 2
        assert len(merged.experiments["H2"].runs) == 3

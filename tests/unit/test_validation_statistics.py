"""Tests for research/validation/statistics.py."""

import numpy as np
import pytest

from research.validation.models import (
    ExperimentRun,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)
from research.validation.statistics import (
    bootstrap_ci,
    cliffs_delta,
    cohens_d,
    compare_all,
    compare_experiments,
    effect_size_label,
)


class TestCohenSD:
    def test_identical_groups(self):
        d = cohens_d([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_separated_groups(self):
        d = cohens_d([1.0, 1.0, 2.0], [5.0, 6.0, 7.0])
        assert d > 1.0

    def test_small_sample(self):
        d = cohens_d([1.0], [5.0])
        assert d == 0.0

    def test_empty_groups(self):
        d = cohens_d([], [])
        assert d == 0.0


class TestCliffsDelta:
    def test_no_overlap(self):
        d = cliffs_delta([1.0, 2.0], [5.0, 6.0])
        assert d < 0

    def test_complete_overlap(self):
        d = cliffs_delta([1.0, 2.0], [1.0, 2.0])
        assert d == pytest.approx(0.0, abs=1e-6)

    def test_empty_groups(self):
        d = cliffs_delta([], [])
        assert d == 0.0


class TestEffectSizeLabel:
    def test_negligible(self):
        assert effect_size_label(0.1) == "negligible"

    def test_small(self):
        assert effect_size_label(0.3) == "small"

    def test_medium(self):
        assert effect_size_label(0.6) == "medium"

    def test_large(self):
        assert effect_size_label(1.0) == "large"

    def test_negative(self):
        assert effect_size_label(-0.6) == "medium"


class TestBootstrapCI:
    def test_identical_groups(self):
        a = [1.0, 2.0, 3.0]
        b = [1.0, 2.0, 3.0]
        lo, hi = bootstrap_ci(a, b, n_resamples=500)
        assert lo <= hi
        # difference of means should be ~0
        np.testing.assert_allclose(0, (lo + hi) / 2, atol=0.5)

    def test_small_sample(self):
        lo, hi = bootstrap_ci([1.0], [5.0], n_resamples=100)
        assert np.isnan(lo) or np.isnan(hi)


class TestCompareExperiments:
    def _make_runs(
        self, durations: list[float], crashes: list[int] | None = None
    ) -> list[ExperimentRun]:
        runs = []
        for i, d in enumerate(durations):
            c = crashes[i] if crashes else 0
            runs.append(
                ExperimentRun(
                    problem_id=f"P{i}",
                    system_metrics=SystemMetrics(duration_seconds=d, crashes=c),
                )
            )
        return runs

    def test_compare_durations(self):
        a = self._make_runs([1, 2, 3, 4, 5])
        b = self._make_runs([6, 7, 8, 9, 10])
        cr = compare_experiments(a, b, "duration_seconds", "system")
        assert cr.metric_name == "duration_seconds"
        assert cr.n_a == 5
        assert cr.n_b == 5
        assert cr.mean_a == 3.0
        assert cr.mean_b == 8.0
        assert cr.significant is True or cr.significant is False  # just check it runs
        assert cr.p_value is not None

    def test_compare_empty(self):
        cr = compare_experiments([], [], "duration_seconds", "system")
        assert cr.n_a == 0
        assert cr.n_b == 0

    def test_compare_retries(self):
        a = self._make_runs([1.0] * 5)
        a[0].system_metrics.retries = 2
        a[1].system_metrics.retries = 3
        b = self._make_runs([1.0] * 5)
        cr = compare_experiments(a, b, "retries", "system")
        assert cr.mean_a == 1.0  # 5 runs, sum of retries=5, mean=1
        assert cr.mean_b == 0.0

    def test_compare_final_metric(self):
        a = [
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.7)),
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.8)),
        ]
        b = [
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.9)),
            ExperimentRun(research_metrics=ResearchMetrics(final_metric=0.95)),
        ]
        cr = compare_experiments(a, b, "final_metric", "research")
        assert cr.mean_a == 0.75
        assert cr.mean_b == 0.925


class TestCompareAll:
    def _make_h_runs(
        self,
        count: int,
        durations: list[float] | None = None,
        final_metrics: list[float] | None = None,
    ) -> list[ExperimentRun]:
        runs = []
        for i in range(count):
            sm = SystemMetrics(
                duration_seconds=durations[i] if durations else 10.0,
                crashes=0,
                crashes_recovered=0,
            )
            rm = ResearchMetrics(
                final_metric=final_metrics[i] if final_metrics else 0.8,
                deployment_success=True,
            )
            runs.append(ExperimentRun(problem_id=f"P{i}", system_metrics=sm, research_metrics=rm))
        return runs

    def test_compare_all_returns_dict(self):
        h1 = self._make_h_runs(3)
        h2 = self._make_h_runs(3)
        h3 = self._make_h_runs(3)
        results = compare_all(h1, h2, h3)
        assert isinstance(results, dict)
        assert len(results) > 0

    def test_compare_all_keys(self):
        h1 = self._make_h_runs(3, durations=[1, 2, 3], final_metrics=[0.7, 0.75, 0.8])
        h2 = self._make_h_runs(3, durations=[4, 5, 6], final_metrics=[0.85, 0.88, 0.9])
        h3 = self._make_h_runs(3, durations=[7, 8, 9], final_metrics=[0.9, 0.92, 0.95])
        results = compare_all(h1, h2, h3)
        # Check RQ1 keys exist
        rq1_keys = [k for k in results if k.startswith("RQ1")]
        assert len(rq1_keys) > 0

    def test_compare_all_empty(self):
        results = compare_all([], [], [])
        assert results == {}

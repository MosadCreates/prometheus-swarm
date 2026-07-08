"""Statistical tests for experiment comparison — MWU, Wilcoxon, Cohen's d, Cliff's Delta, Bootstrap CI."""

from __future__ import annotations

import logging
import math
from typing import Any

import numpy as np
from scipy import stats as scipy_stats

from research.validation.models import (
    ComparisonResult,
    ExperimentRun,
    ResearchHypothesis,
    ResearchQuestion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Effect sizes
# ---------------------------------------------------------------------------


def cohens_d(a: list[float], b: list[float]) -> float:
    """Cohen's d: difference in means divided by pooled std deviation."""
    if len(a) < 2 or len(b) < 2:
        return 0.0
    na, nb = len(a), len(b)
    mean_a, mean_b = np.mean(a), np.mean(b)
    var_a, var_b = np.var(a, ddof=1), np.var(b, ddof=1)
    pooled = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    if pooled == 0:
        return 0.0
    return (mean_b - mean_a) / pooled


def cliffs_delta(a: list[float], b: list[float]) -> float:
    """Cliff's Delta: non-parametric effect size for ordinal data."""
    if not a or not b:
        return 0.0
    a_arr, b_arr = np.array(a), np.array(b)
    n_gt = np.sum(a_arr[:, None] > b_arr[None, :])
    n_lt = np.sum(a_arr[:, None] < b_arr[None, :])
    return (n_gt - n_lt) / (len(a) * len(b))


def effect_size_label(d: float) -> str:
    """Interpret Cohen's d magnitude."""
    ad = abs(d)
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


# ---------------------------------------------------------------------------
# Bootstrap confidence interval
# ---------------------------------------------------------------------------


def bootstrap_ci(
    a: list[float],
    b: list[float],
    n_resamples: int = 10_000,
    ci: float = 0.95,
    random_seed: int = 42,
) -> tuple[float, float]:
    """Bootstrap confidence interval for difference of means (b - a)."""
    if len(a) < 2 or len(b) < 2:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(random_seed)
    diffs = np.zeros(n_resamples)
    mean_a, mean_b = np.mean(a), np.mean(b)

    for i in range(n_resamples):
        boot_a = rng.choice(a, size=len(a), replace=True)
        boot_b = rng.choice(b, size=len(b), replace=True)
        diffs[i] = np.mean(boot_b) - np.mean(boot_a)

    lower = np.percentile(diffs, (1 - ci) / 2 * 100)
    upper = np.percentile(diffs, (1 + ci) / 2 * 100)
    return (float(lower), float(upper))


# ---------------------------------------------------------------------------
# Auto-select test
# ---------------------------------------------------------------------------


def compare_experiments(
    runs_a: list[ExperimentRun],
    runs_b: list[ExperimentRun],
    metric_key: str = "duration_seconds",
    metric_group: str = "system",
    research_question: str = "",
) -> ComparisonResult:
    """Compare two groups of runs on a given metric.

    Auto-selects paired vs unpaired test based on whether problem_ids match.
    Preferred: Mann-Whitney U (independent) or Wilcoxon signed-rank (paired).
    Returns a ComparisonResult with p-value, effect size, CI, and interpretation.
    """
    vals_a = _extract_metric_values(runs_a, metric_key, metric_group)
    vals_b = _extract_metric_values(runs_b, metric_key, metric_group)

    if len(vals_a) == 0 or len(vals_b) == 0:
        return ComparisonResult(
            metric_name=metric_key,
            test_used="none",
            n_a=len(vals_a),
            n_b=len(vals_b),
        )

    mean_a = float(np.mean(vals_a))
    mean_b = float(np.mean(vals_b))
    median_a = float(np.median(vals_a))
    median_b = float(np.median(vals_b))

    # Determine test
    ids_a = {r.problem_id for r in runs_a if r.problem_id}
    ids_b = {r.problem_id for r in runs_b if r.problem_id}
    common_ids = ids_a & ids_b
    is_paired = len(common_ids) >= min(len(vals_a), len(vals_b)) * 0.5 and len(common_ids) >= 3

    if is_paired:
        pivoted_a, pivoted_b = _align_by_problem_id(runs_a, runs_b, metric_key, metric_group)
        pivoted_a_arr = np.array(pivoted_a, dtype=float)
        pivoted_b_arr = np.array(pivoted_b, dtype=float)
        has_varying_diffs = len(pivoted_a) >= 3 and np.any(pivoted_a_arr != pivoted_b_arr)
        if has_varying_diffs:
            test_used = "Wilcoxon signed-rank"
            stat, p_val = scipy_stats.wilcoxon(pivoted_a, pivoted_b, alternative="two-sided")
        else:
            test_used = "Mann-Whitney U"
            stat, p_val = scipy_stats.mannwhitneyu(vals_a, vals_b, alternative="two-sided")
            is_paired = False
    else:
        test_used = "Mann-Whitney U"
        stat, p_val = scipy_stats.mannwhitneyu(vals_a, vals_b, alternative="two-sided")

    p_val = float(p_val)
    significant = bool(p_val < 0.05)

    # Effect size
    cd = cohens_d(vals_a, vals_b)
    cd_label = effect_size_label(cd)

    # Bootstrap CI
    ci_lower, ci_upper = bootstrap_ci(vals_a, vals_b)

    return ComparisonResult(
        metric_name=metric_key,
        mean_a=mean_a,
        mean_b=mean_b,
        median_a=median_a,
        median_b=median_b,
        p_value=p_val,
        effect_size=cd,
        effect_size_name=f"Cohen's d ({cd_label})",
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        test_used=test_used,
        n_a=len(vals_a),
        n_b=len(vals_b),
        significant=significant,
        research_question=research_question,
    )


# ---------------------------------------------------------------------------
# Run all RQ comparisons for an experiment set
# ---------------------------------------------------------------------------


RQ_METRICS: dict[str, list[tuple[str, str, str]]] = {
    ResearchQuestion.RQ1.value: [
        ("duration_seconds", "system", "RQ1: Execution duration"),
        ("wall_clock_time_s", "system", "RQ1: Wall-clock time"),
        ("retries", "system", "RQ1: Retry count"),
    ],
    ResearchQuestion.RQ2.value: [
        ("final_metric", "research", "RQ2: Final metric value"),
        ("deployment_success", "research", "RQ2: Deployment success rate"),
    ],
    ResearchQuestion.RQ3.value: [
        ("crashes", "system", "RQ3: Crash count"),
        ("crashes_recovered", "system", "RQ3: Crashes recovered"),
    ],
    ResearchQuestion.RQ4.value: [
        ("deployment_success", "research", "RQ4: Deployment success rate"),
    ],
}

RQ_PAIRS: list[tuple[ResearchQuestion, ResearchHypothesis, ResearchHypothesis, str]] = [
    (
        ResearchQuestion.RQ1,
        ResearchHypothesis.H1,
        ResearchHypothesis.H2,
        "H1 vs H2: execution cost",
    ),
    (ResearchQuestion.RQ2, ResearchHypothesis.H1, ResearchHypothesis.H2, "H1 vs H2: accuracy"),
    (ResearchQuestion.RQ3, ResearchHypothesis.H2, ResearchHypothesis.H3, "H2 vs H3: recovery"),
    (ResearchQuestion.RQ4, ResearchHypothesis.H1, ResearchHypothesis.H3, "H1 vs H3: deployment"),
]


def compare_all(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> dict[str, ComparisonResult]:
    """Run all pre-defined comparisons between hypotheses.

    Returns a dict keyed by comparison label.
    """
    results: dict[str, ComparisonResult] = {}
    if not any([runs_h1, runs_h2, runs_h3]):
        return results
    for rq, ha, hb, label in RQ_PAIRS:
        group_a = {
            ResearchHypothesis.H1: runs_h1,
            ResearchHypothesis.H2: runs_h2,
            ResearchHypothesis.H3: runs_h3,
        }[ha]
        group_b = {
            ResearchHypothesis.H1: runs_h1,
            ResearchHypothesis.H2: runs_h2,
            ResearchHypothesis.H3: runs_h3,
        }[hb]
        metrics = RQ_METRICS.get(rq.value, [])

        for metric_key, metric_group, desc in metrics:
            result = compare_experiments(
                group_a,
                group_b,
                metric_key=metric_key,
                metric_group=metric_group,
                research_question=desc,
            )
            result_key = f"{rq.value}_{ha.value}_vs_{hb.value}_{metric_key}"
            results[result_key] = result

    return results


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract_metric_values(
    runs: list[ExperimentRun],
    metric_key: str,
    metric_group: str,
) -> list[float]:
    """Extract float values for a metric from a list of runs."""
    vals: list[float] = []
    for run in runs:
        if metric_group == "system":
            val = getattr(run.system_metrics, metric_key, None)
        elif metric_group == "research":
            val = getattr(run.research_metrics, metric_key, None)
        elif metric_group == "calibration":
            val = None
            if run.calibration:
                val = getattr(run.calibration, metric_key, None)
        else:
            val = None

        if val is not None:
            try:
                vals.append(float(val))
            except (TypeError, ValueError):
                pass
    return vals


def _align_by_problem_id(
    runs_a: list[ExperimentRun],
    runs_b: list[ExperimentRun],
    metric_key: str,
    metric_group: str,
) -> tuple[list[float], list[float]]:
    """Align two lists of runs by problem_id for paired testing."""
    lookup_a: dict[str, float] = {}
    for r in runs_a:
        if r.problem_id:
            val = _extract_single_metric(r, metric_key, metric_group)
            if val is not None:
                lookup_a[r.problem_id] = val

    pairs_a: list[float] = []
    pairs_b: list[float] = []
    for r in runs_b:
        if r.problem_id and r.problem_id in lookup_a:
            val_b = _extract_single_metric(r, metric_key, metric_group)
            if val_b is not None:
                pairs_a.append(lookup_a[r.problem_id])
                pairs_b.append(val_b)

    return pairs_a, pairs_b


def _extract_single_metric(
    run: ExperimentRun,
    metric_key: str,
    metric_group: str,
) -> float | None:
    if metric_group == "system":
        val = getattr(run.system_metrics, metric_key, None)
    elif metric_group == "research":
        val = getattr(run.research_metrics, metric_key, None)
    else:
        return None
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None

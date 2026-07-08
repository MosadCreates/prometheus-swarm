"""Publication-quality matplotlib figures for the research validation framework.

All figures use a consistent style: colorblind-friendly palette, vector output,
DejaVu Sans fonts, 600 DPI, no gridlines, numbered deterministic filenames.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

from research.validation.models import (
    ComparisonResult,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    LearningCurvePoint,
    ResearchHypothesis,
    SystemMetrics,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Centralised style configuration
# ---------------------------------------------------------------------------

COLORS = {
    "h1": "#4477AA",
    "h2": "#EE6677",
    "h3": "#228833",
    "pass": "#228833",
    "fail": "#CC3311",
    "retry": "#EE7733",
    "accent": "#AA3377",
    "gray": "#BBBBBB",
    "text": "#333333",
}

HYPOTHESIS_COLORS = {
    ResearchHypothesis.H1.value: COLORS["h1"],
    ResearchHypothesis.H2.value: COLORS["h2"],
    ResearchHypothesis.H3.value: COLORS["h3"],
}

HYPOTHESIS_LABELS = {
    ResearchHypothesis.H1.value: "H1 — Static Planner",
    ResearchHypothesis.H2.value: "H2 — Adaptive Planner",
    ResearchHypothesis.H3.value: "H3 — Adaptive + Patch Memory",
}

# Colorblind-friendly palette (Wong 2011)
_QUALITATIVE = ["#0077BB", "#EE7733", "#228833", "#CC3311", "#AA3377", "#BBBBBB"]

matplotlib.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 120,
        "savefig.dpi": 600,
        "savefig.format": "png",
        "savefig.bbox": "tight",
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

_FIGURE_DIR = Path(__file__).resolve().parent.parent.parent / "figures"
_FIGURE_COUNTER: dict[str, int] = {}


def _next_fig_id(prefix: str) -> str:
    _FIGURE_COUNTER[prefix] = _FIGURE_COUNTER.get(prefix, 0) + 1
    return f"{prefix}_{_FIGURE_COUNTER[prefix]:02d}"


def _ensure_dir() -> Path:
    _FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    return _FIGURE_DIR


def _save_figure(fig: matplotlib.figure.Figure, fig_id: str) -> Path:
    dir_path = _ensure_dir()
    png_path = dir_path / f"{fig_id}.png"
    svg_path = dir_path / f"{fig_id}.svg"
    fig.savefig(png_path, dpi=600)
    fig.savefig(svg_path, format="svg")
    plt.close(fig)
    logger.info(f"Figure saved: {png_path}, {svg_path}")
    return png_path


# ---------------------------------------------------------------------------
# 1. Duration comparison — box plot
# ---------------------------------------------------------------------------


def fig_duration_comparison(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))
    labels = [HYPOTHESIS_LABELS["H1"], HYPOTHESIS_LABELS["H2"], HYPOTHESIS_LABELS["H3"]]
    data = [
        [
            r.system_metrics.duration_seconds
            for r in runs_h1
            if r.system_metrics.duration_seconds > 0
        ],
        [
            r.system_metrics.duration_seconds
            for r in runs_h2
            if r.system_metrics.duration_seconds > 0
        ],
        [
            r.system_metrics.duration_seconds
            for r in runs_h3
            if r.system_metrics.duration_seconds > 0
        ],
    ]
    colors = [COLORS["h1"], COLORS["h2"], COLORS["h3"]]

    bp = ax.boxplot(data, patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    for i, vals in enumerate(data):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(vals))
        ax.scatter(np.full(len(vals), i + 1) + jitter, vals, alpha=0.3, s=15, c=colors[i])

    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Execution duration (s)")
    ax.set_title("RQ1: Execution Duration Across Planning Strategies")
    fig_id = _next_fig_id("fig_duration")

    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 2. Deployment success rate — bar chart
# ---------------------------------------------------------------------------


def fig_deployment_success(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    def _rate(runs: list[ExperimentRun]) -> float:
        successes = sum(1 for r in runs if r.research_metrics.deployment_success is True)
        total = sum(1 for r in runs if r.research_metrics.deployment_success is not None)
        return successes / total if total > 0 else 0

    rates = [_rate(runs_h1), _rate(runs_h2), _rate(runs_h3)]
    labels = [HYPOTHESIS_LABELS["H1"], HYPOTHESIS_LABELS["H2"], HYPOTHESIS_LABELS["H3"]]
    x = np.arange(len(labels))

    bars = ax.bar(x, rates, width=0.5, color=[COLORS["h1"], COLORS["h2"], COLORS["h3"]], alpha=0.85)
    ax.bar_label(bars, fmt="%.1f%%", padding=3)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Deployment success rate")
    ax.set_ylim(0, 1.15)
    ax.set_title("RQ4: Deployment Success Rate Across Planning Strategies")
    fig_id = _next_fig_id("fig_deployment")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 3. Final metric comparison — box plot
# ---------------------------------------------------------------------------


def fig_final_metric(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    data = [
        [
            r.research_metrics.final_metric
            for r in runs_h1
            if r.research_metrics.final_metric is not None
        ],
        [
            r.research_metrics.final_metric
            for r in runs_h2
            if r.research_metrics.final_metric is not None
        ],
        [
            r.research_metrics.final_metric
            for r in runs_h3
            if r.research_metrics.final_metric is not None
        ],
    ]
    labels = [HYPOTHESIS_LABELS["H1"], HYPOTHESIS_LABELS["H2"], HYPOTHESIS_LABELS["H3"]]
    colors = [COLORS["h1"], COLORS["h2"], COLORS["h3"]]

    bp = ax.boxplot(data, patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    for i, vals in enumerate(data):
        jitter = np.random.default_rng(42).uniform(-0.12, 0.12, len(vals))
        ax.scatter(np.full(len(vals), i + 1) + jitter, vals, alpha=0.3, s=15, c=colors[i])

    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Best validation metric")
    ax.set_title("RQ2: Prediction Accuracy Across Planning Strategies")
    fig_id = _next_fig_id("fig_final_metric")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 4. Crash count comparison — box plot
# ---------------------------------------------------------------------------


def fig_crash_comparison(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    data = [
        [float(r.system_metrics.crashes) for r in runs_h1],
        [float(r.system_metrics.crashes) for r in runs_h2],
        [float(r.system_metrics.crashes) for r in runs_h3],
    ]
    labels = [HYPOTHESIS_LABELS["H1"], HYPOTHESIS_LABELS["H2"], HYPOTHESIS_LABELS["H3"]]
    colors = [COLORS["h1"], COLORS["h2"], COLORS["h3"]]

    bp = ax.boxplot(data, patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)

    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("Crash count")
    ax.set_title("RQ3: Training Crashes Across Planning Strategies")
    fig_id = _next_fig_id("fig_crashes")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 5. Planner calibration — scatter: predicted vs actual duration
# ---------------------------------------------------------------------------


def fig_planner_calibration(runs: list[ExperimentRun]) -> Path:
    fig, ax = plt.subplots(figsize=(6, 6))

    predicted: list[float] = []
    actual: list[float] = []
    for r in runs:
        if r.calibration and r.calibration.predicted_duration_minutes is not None:
            predicted.append(float(r.calibration.predicted_duration_minutes))
            actual.append(
                r.calibration.actual_duration_minutes or r.system_metrics.duration_seconds / 60
            )

    if not predicted:
        ax.text(0.5, 0.5, "No calibration data", ha="center", va="center", transform=ax.transAxes)
        fig_id = _next_fig_id("fig_calibration")
        return _save_figure(fig, fig_id)

    max_val = max(max(predicted), max(actual)) * 1.1
    ax.scatter(predicted, actual, alpha=0.6, c=COLORS["accent"], edgecolors="white", linewidths=0.5)
    ax.plot([0, max_val], [0, max_val], "k--", alpha=0.4, label="Perfect calibration")
    ax.set_xlim(0, max_val)
    ax.set_ylim(0, max_val)
    ax.set_xlabel("Predicted duration (min)")
    ax.set_ylabel("Actual duration (min)")
    ax.set_title("Planner Calibration: Predicted vs Actual Duration")
    ax.legend()
    fig_id = _next_fig_id("fig_calibration")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 6. Learning curve — prediction error vs evidence count
# ---------------------------------------------------------------------------


def fig_learning_curve(runs: list[ExperimentRun]) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    points: list[LearningCurvePoint] = []
    for r in runs:
        points.extend(r.learning_curve)

    if not points:
        ax.text(
            0.5, 0.5, "No learning curve data", ha="center", va="center", transform=ax.transAxes
        )
        fig_id = _next_fig_id("fig_learning_curve")
        return _save_figure(fig, fig_id)

    points.sort(key=lambda p: p.evidence_count)
    xs = [p.evidence_count for p in points]
    ys = [p.prediction_error_pct for p in points]
    metric_types = list({p.metric for p in points})

    colors_iter = _QUALITATIVE[: len(metric_types)]
    for mt, color in zip(metric_types, colors_iter):
        filtered = [(x, y) for p, x, y in zip(points, xs, ys) if p.metric == mt]
        if filtered:
            fx, fy = zip(*filtered)
            ax.plot(fx, fy, "o-", color=color, label=mt, markersize=4)

    ax.set_xlabel("Number of historical executions")
    ax.set_ylabel("Prediction error (%)")
    ax.set_title("Learning Curve: Prediction Error Over Planner Experience")
    ax.legend()
    fig_id = _next_fig_id("fig_learning_curve")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 7. Architecture selection accuracy — bar chart
# ---------------------------------------------------------------------------


def fig_architecture_accuracy(runs: list[ExperimentRun]) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    gaps = [
        r.research_metrics.architecture_selection_gap
        for r in runs
        if r.research_metrics.architecture_selection_gap is not None
    ]

    if not gaps:
        ax.text(
            0.5,
            0.5,
            "No architecture accuracy data",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        fig_id = _next_fig_id("fig_architecture")
        return _save_figure(fig, fig_id)

    bins = np.linspace(0, max(gaps) * 1.1, 15)
    ax.hist(gaps, bins=bins, color=COLORS["accent"], alpha=0.7, edgecolor="white", linewidths=0.5)
    mean_gap = np.mean(gaps)
    ax.axvline(mean_gap, color=COLORS["fail"], linestyle="--", label=f"Mean gap = {mean_gap:.3f}")
    ax.set_xlabel("|historical_best_metric - planner_achieved_metric|")
    ax.set_ylabel("Frequency")
    ax.set_title("Architecture Selection Accuracy")
    ax.legend()
    fig_id = _next_fig_id("fig_architecture")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 8. Confidence calibration — reliability diagram
# ---------------------------------------------------------------------------


def fig_confidence_calibration(runs: list[ExperimentRun]) -> Path:
    fig, ax = plt.subplots(figsize=(6, 6))

    confidences = [
        r.research_metrics.planner_confidence_score
        for r in runs
        if r.research_metrics.planner_confidence_score is not None
    ]
    actuals = [
        r.research_metrics.actual_success
        for r in runs
        if r.research_metrics.planner_confidence_score is not None
    ]

    if not confidences:
        ax.text(0.5, 0.5, "No confidence data", ha="center", va="center", transform=ax.transAxes)
        fig_id = _next_fig_id("fig_confidence")
        return _save_figure(fig, fig_id)

    bins = np.linspace(0, 1, 6)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    accuracies = np.zeros(len(bin_centers))
    counts = np.zeros(len(bin_centers))

    for conf, actual in zip(confidences, actuals):
        idx = np.digitize(conf, bins) - 1
        idx = min(idx, len(bin_centers) - 1)
        counts[idx] += 1
        if actual:
            accuracies[idx] += 1

    for i in range(len(accuracies)):
        if counts[i] > 0:
            accuracies[i] /= counts[i]

    valid = counts > 0
    ax.plot([0, 1], [0, 1], "k--", alpha=0.3, label="Perfect calibration")
    ax.plot(
        bin_centers[valid], accuracies[valid], "o-", color=COLORS["h2"], markersize=6, linewidth=2
    )
    ax.set_xlabel("Confidence score")
    ax.set_ylabel("Observed success rate")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Confidence Calibration (Reliability Diagram)")
    ax.legend()
    fig_id = _next_fig_id("fig_confidence")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 9. Failure breakdown — stacked bar
# ---------------------------------------------------------------------------


def fig_failure_breakdown(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    from research.validation.failures import generate_failure_report

    fig, ax = plt.subplots(figsize=(8, 5))

    reports = [
        generate_failure_report(runs_h1),
        generate_failure_report(runs_h2),
        generate_failure_report(runs_h3),
    ]

    all_categories: list[str] = []
    for rep in reports:
        for cat in rep.categories:
            if cat not in all_categories:
                all_categories.append(cat)

    if not all_categories:
        ax.text(0.5, 0.5, "No failures", ha="center", va="center", transform=ax.transAxes)
        fig_id = _next_fig_id("fig_failures")
        return _save_figure(fig, fig_id)

    data_matrix = []
    for rep in reports:
        row = [rep.categories.get(cat, 0) for cat in all_categories]
        data_matrix.append(row)

    x = np.arange(len(all_categories))
    width = 0.25
    for i, (data_row, color) in enumerate(
        zip(data_matrix, [COLORS["h1"], COLORS["h2"], COLORS["h3"]])
    ):
        offset = (i - 1) * width
        bars = ax.bar(
            x + offset,
            data_row,
            width,
            label=HYPOTHESIS_LABELS[list(HYPOTHESIS_LABELS.keys())[i]],
            color=color,
            alpha=0.8,
        )

    ax.set_xticks(x)
    ax.set_xticklabels(all_categories, rotation=25, ha="right")
    ax.set_ylabel("Failure count")
    ax.set_title("Failure Breakdown by Category Across Strategies")
    ax.legend()
    fig_id = _next_fig_id("fig_failures")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# 10. Orchestration overhead — histogram
# ---------------------------------------------------------------------------


def fig_overhead_comparison(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))

    def _overheads(runs: list[ExperimentRun]) -> list[float]:
        return [
            r.system_metrics.orchestration_overhead_s
            for r in runs
            if r.system_metrics.orchestration_overhead_s > 0
        ]

    for data, color, label in [
        (_overheads(runs_h1), COLORS["h1"], HYPOTHESIS_LABELS["H1"]),
        (_overheads(runs_h2), COLORS["h2"], HYPOTHESIS_LABELS["H2"]),
        (_overheads(runs_h3), COLORS["h3"], HYPOTHESIS_LABELS["H3"]),
    ]:
        if data:
            ax.hist(data, bins=12, alpha=0.5, color=color, label=label)

    ax.set_xlabel("Orchestration overhead (s)")
    ax.set_ylabel("Frequency")
    ax.set_title("Orchestration Overhead Distribution")
    ax.legend()
    fig_id = _next_fig_id("fig_overhead")
    return _save_figure(fig, fig_id)


# ---------------------------------------------------------------------------
# Generate all figures at once
# ---------------------------------------------------------------------------


def generate_all_figures(
    runs_h1: list[ExperimentRun],
    runs_h2: list[ExperimentRun],
    runs_h3: list[ExperimentRun],
) -> list[Path]:
    paths: list[Path] = []
    paths.append(fig_duration_comparison(runs_h1, runs_h2, runs_h3))
    paths.append(fig_deployment_success(runs_h1, runs_h2, runs_h3))
    paths.append(fig_final_metric(runs_h1, runs_h2, runs_h3))
    paths.append(fig_crash_comparison(runs_h1, runs_h2, runs_h3))
    paths.append(fig_planner_calibration(runs_h2 + runs_h3))
    paths.append(fig_learning_curve(runs_h2 + runs_h3))
    paths.append(fig_architecture_accuracy(runs_h1 + runs_h2 + runs_h3))
    paths.append(fig_confidence_calibration(runs_h2 + runs_h3))
    paths.append(fig_failure_breakdown(runs_h1, runs_h2, runs_h3))
    paths.append(fig_overhead_comparison(runs_h1, runs_h2, runs_h3))
    return paths

"""Metric computation — system-level and research-level metrics as pure functions."""

from __future__ import annotations

import logging
import statistics
from typing import Any

from research.validation.models import (
    Experiment,
    ExperimentRun,
    ExperimentSet,
    ResearchMetrics,
    SystemMetrics,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# System metrics — from execution data
# ---------------------------------------------------------------------------


def compute_system_metrics(outcome: dict[str, Any]) -> SystemMetrics:
    """Extract SystemMetrics from an execution outcome dict."""
    return SystemMetrics(
        duration_seconds=outcome.get("total_plan_duration_s", 0)
        or outcome.get("duration_seconds", 0)
        or 0,
        retries=outcome.get("retry_count", outcome.get("retries", 0)) or 0,
        crashes=outcome.get("crash_count", 0) or 0,
        crashes_recovered=outcome.get("crashes_recovered", outcome.get("recovered", 0)) or 0,
        peak_ram_mb=outcome.get("peak_ram_mb"),
        peak_gpu_mb=outcome.get("peak_gpu_mb"),
        wall_clock_time_s=outcome.get("wall_clock_time_s", 0) or 0,
        orchestration_overhead_s=outcome.get("orchestration_overhead_s", 0) or 0,
    )


# ---------------------------------------------------------------------------
# Research metrics
# ---------------------------------------------------------------------------


def compute_research_metrics(
    outcome: dict[str, Any],
    prediction_error: dict[str, Any] | None = None,
) -> ResearchMetrics:
    """Compute research-level metrics from execution outcome + prediction error."""
    decision = outcome.get("decision", "")
    deployment_success = decision == "pass"

    pred = prediction_error or {}

    return ResearchMetrics(
        prediction_error_duration_pct=pred.get("duration_pct"),
        prediction_error_ram_pct=pred.get("ram_pct"),
        prediction_bias_duration_pct=pred.get("duration_bias_pct"),
        prediction_bias_ram_pct=pred.get("ram_bias_pct"),
        deployment_success=deployment_success,
        planner_confidence_score=pred.get("planner_confidence"),
        actual_success=deployment_success,
        architecture_selection_gap=pred.get("architecture_gap"),
        patch_success_rate=_compute_patch_rate(outcome),
        fallback_success_rate=_compute_fallback_rate(outcome),
        final_metric=outcome.get("best_val_metric", outcome.get("primary_metric_value")),
    )


def _compute_patch_rate(outcome: dict[str, Any]) -> float | None:
    patches = outcome.get("patch_attempts", 0) or 0
    successes = outcome.get("patch_successes", 0) or 0
    if patches > 0:
        return successes / patches
    return None


def _compute_fallback_rate(outcome: dict[str, Any]) -> float | None:
    fallbacks = outcome.get("fallback_attempts", 0) or 0
    successes = outcome.get("fallback_successes", 0) or 0
    if fallbacks > 0:
        return successes / fallbacks
    return None


# ---------------------------------------------------------------------------
# Aggregate metrics
# ---------------------------------------------------------------------------


def aggregate_system_metrics(
    runs: list[ExperimentRun],
) -> dict[str, float | int | None]:
    """Compute aggregate system metrics across runs.

    Returns mean, median, min, max, std for each numeric metric.
    """
    if not runs:
        return {}

    def _stats(values: list[float]) -> dict[str, float]:
        if not values:
            return {"mean": 0, "median": 0, "min": 0, "max": 0, "std": 0}
        return {
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "min": min(values),
            "max": max(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0,
        }

    durations = [r.system_metrics.duration_seconds for r in runs]
    retries = [float(r.system_metrics.retries) for r in runs]
    crashes = [float(r.system_metrics.crashes) for r in runs]
    wall_clock = [r.system_metrics.wall_clock_time_s for r in runs]
    overhead = [r.system_metrics.orchestration_overhead_s for r in runs]

    result: dict[str, float | int | None] = {
        "count": len(runs),
        "duration": _stats(durations),
        "retries": _stats(retries),
        "crashes": _stats(crashes),
        "wall_clock_time_s": _stats(wall_clock),
        "orchestration_overhead_s": _stats(overhead),
        "total_duration": sum(durations),
    }

    peak_ram = [
        r.system_metrics.peak_ram_mb for r in runs if r.system_metrics.peak_ram_mb is not None
    ]
    if peak_ram:
        result["peak_ram_mb"] = _stats(peak_ram)

    return result


def aggregate_research_metrics(
    runs: list[ExperimentRun],
) -> dict[str, Any]:
    """Compute aggregate research metrics across runs.

    Includes deployment success rate, mean final metric, mean prediction errors.
    """
    if not runs:
        return {}

    deployment_successes = sum(1 for r in runs if r.research_metrics.deployment_success is True)
    deployment_total = sum(1 for r in runs if r.research_metrics.deployment_success is not None)
    success_rate = deployment_successes / deployment_total if deployment_total > 0 else 0

    final_metrics = [
        r.research_metrics.final_metric for r in runs if r.research_metrics.final_metric is not None
    ]
    pred_errors_dur = [
        r.research_metrics.prediction_error_duration_pct
        for r in runs
        if r.research_metrics.prediction_error_duration_pct is not None
    ]
    pred_errors_ram = [
        r.research_metrics.prediction_error_ram_pct
        for r in runs
        if r.research_metrics.prediction_error_ram_pct is not None
    ]
    gaps = [
        r.research_metrics.architecture_selection_gap
        for r in runs
        if r.research_metrics.architecture_selection_gap is not None
    ]
    confidences = [
        r.research_metrics.planner_confidence_score
        for r in runs
        if r.research_metrics.planner_confidence_score is not None
    ]

    result: dict[str, Any] = {
        "count": len(runs),
        "deployment_success_rate": success_rate,
        "deployment_successes": deployment_successes,
        "deployment_total": deployment_total,
        "final_metric": {
            "mean": statistics.mean(final_metrics) if final_metrics else None,
            "median": statistics.median(final_metrics) if final_metrics else None,
        },
        "prediction_error_duration_pct": {
            "mean": statistics.mean(pred_errors_dur) if pred_errors_dur else None,
            "median": statistics.median(pred_errors_dur) if pred_errors_dur else None,
        },
        "prediction_error_ram_pct": {
            "mean": statistics.mean(pred_errors_ram) if pred_errors_ram else None,
            "median": statistics.median(pred_errors_ram) if pred_errors_ram else None,
        },
        "architecture_gap": {
            "mean": statistics.mean(gaps) if gaps else None,
            "median": statistics.median(gaps) if gaps else None,
        },
        "planner_confidence": {
            "mean": statistics.mean(confidences) if confidences else None,
            "median": statistics.median(confidences) if confidences else None,
        },
    }
    return result


# ---------------------------------------------------------------------------
# Experiment-level summaries
# ---------------------------------------------------------------------------


def summarize_experiment(experiment: Experiment) -> dict[str, Any]:
    """Summarize a single experiment (one hypothesis)."""
    sm = aggregate_system_metrics(experiment.runs)
    rm = aggregate_research_metrics(experiment.runs)
    return {
        "hypothesis": experiment.hypothesis.value,
        "name": experiment.name,
        "run_count": len(experiment.runs),
        "system": sm,
        "research": rm,
    }


def summarize_set(exp_set: ExperimentSet) -> dict[str, Any]:
    """Summarize all experiments in a set."""
    return {
        "set_id": exp_set.set_id,
        "name": exp_set.name,
        "hypotheses": {h: summarize_experiment(exp) for h, exp in exp_set.experiments.items()},
        "comparisons": {k: v.model_dump() for k, v in exp_set.comparisons.items()},
    }

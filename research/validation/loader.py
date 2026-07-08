"""Import experiment runs from Redis keys, baseline JSONs, and batch result files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from research.validation.models import (
    ArchitectureSelectionAccuracy,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    FailureCategory,
    LearningCurvePoint,
    PlanningCalibration,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Load from existing baseline JSON file
# ---------------------------------------------------------------------------


def _parse_outcome(status: str) -> str:
    return {"pass": "success", "crash": "failed", "retry": "retry", "escalate": "escalated"}.get(
        status, "unknown"
    )


def _parse_failure_category(status: str) -> FailureCategory | None:
    if status == "crash":
        return FailureCategory.TRAINING
    if status == "escalate":
        return FailureCategory.UNKNOWN
    return None


def load_from_baseline(
    path: str | Path,
    hypothesis_label: str = "condition_b",
    hypothesis: ResearchHypothesis = ResearchHypothesis.H2,
) -> Experiment:
    """Load results from a baseline_v1.json file into an Experiment."""
    path = Path(path)
    data = json.loads(path.read_text())

    runs: list[ExperimentRun] = []
    condition_key = hypothesis_label

    results = data.get(condition_key, {}).get("results", [])

    for entry in results:
        sm = SystemMetrics(
            duration_seconds=entry.get("duration_seconds", 0),
            retries=entry.get("retry_count", 0),
            crashes=1 if entry.get("crash_count", 0) > 0 else 0,
            crashes_recovered=0,
        )
        rm = ResearchMetrics(
            final_metric=entry.get("best_val_metric"),
            deployment_success=entry.get("decision") == "pass",
            actual_success=entry.get("decision") == "pass",
            patch_success_rate=None,
        )
        run = ExperimentRun(
            job_id=entry.get("job_id", ""),
            problem_id=entry.get("problem_id", ""),
            hypothesis=hypothesis,
            system_metrics=sm,
            research_metrics=rm,
            failure_category=_parse_failure_category(entry.get("status", "")),
            execution_outcome={
                "status": entry.get("status", ""),
                "decision": entry.get("decision", ""),
                "architecture": entry.get("architecture", ""),
                "error": entry.get("error"),
            },
        )
        runs.append(run)

    experiment = Experiment(
        name=f"From baseline: {path.name} ({hypothesis.value})",
        hypothesis=hypothesis,
        runs=runs,
    )
    logger.info(f"Loaded {len(runs)} runs from baseline {path.name}")
    return experiment


# ---------------------------------------------------------------------------
# Load from batch result JSON files
# ---------------------------------------------------------------------------


def load_from_batch_file(
    path: str | Path,
    hypothesis: ResearchHypothesis = ResearchHypothesis.H2,
) -> Experiment:
    """Load results from a batch file (research/benchmark/results/batch_*.json)."""
    path = Path(path)
    data = json.loads(path.read_text())

    runs: list[ExperimentRun] = []
    raw_runs = data.get("results", data.get("runs", data.get("experiments", [])))

    if not isinstance(raw_runs, list):
        raw_runs = [raw_runs]

    for entry in raw_runs:
        if isinstance(entry, str):
            continue

        outcome_status = _parse_outcome(entry.get("status", ""))
        # Determine success: deployment success or pass decision
        decision = entry.get("decision", "")
        deployment_success = decision == "pass"
        actual_success = decision == "pass"

        sm = SystemMetrics(
            duration_seconds=entry.get("duration_seconds", 0) or 0,
            retries=entry.get("retry_count", 0) or 0,
            crashes=entry.get("crash_count", 0) or 0,
            crashes_recovered=entry.get("crashes_recovered", 0) or 0,
        )
        rm = ResearchMetrics(
            final_metric=entry.get("best_val_metric") or entry.get("primary_metric_value"),
            deployment_success=deployment_success,
            actual_success=actual_success,
            patch_success_rate=entry.get("patch_success_rate"),
        )
        run = ExperimentRun(
            job_id=entry.get("job_id", ""),
            problem_id=entry.get("problem_id", entry.get("id", "")),
            hypothesis=hypothesis,
            system_metrics=sm,
            research_metrics=rm,
            failure_category=_parse_failure_category(entry.get("status", "")),
            execution_outcome={
                "status": outcome_status,
                "decision": decision,
                "architecture": entry.get("architecture", ""),
                "error": entry.get("error"),
            },
        )
        runs.append(run)

    experiment = Experiment(
        name=f"From batch: {path.name} ({hypothesis.value})",
        hypothesis=hypothesis,
        runs=runs,
    )
    logger.info(f"Loaded {len(runs)} runs from batch file {path.name}")
    return experiment


# ---------------------------------------------------------------------------
# Load from experiment directory (scan *.json files)
# ---------------------------------------------------------------------------


def load_all_experiments_from_directory(
    directory: str | Path,
    hypothesis: ResearchHypothesis | None = None,
) -> list[Experiment]:
    """Scan a directory for baseline/batch JSON files and load all experiments."""
    directory = Path(directory)
    if not directory.exists():
        return []
    experiments: list[Experiment] = []
    h = hypothesis or ResearchHypothesis.H2

    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            base = {}

            # Try several common top-level keys
            for key in ("condition_b", "condition_c", "condition_a", "results", "runs"):
                val = data.get(key)
                if val and isinstance(val, dict | list):
                    base = data
                    break
                if val is not None:
                    base = data
                    break

            has_results = any(
                isinstance(base.get(k), dict | list) for k in ("results", "runs", "experiments")
            )
            if has_results or "condition_b" in data or "condition_c" in data:
                # baseline-like structure
                if "condition_b" in data:
                    experiments.append(load_from_baseline(path, "condition_b", h))
                if "condition_c" in data:
                    experiments.append(
                        load_from_baseline(path, "condition_c", ResearchHypothesis.H3)
                    )
                if "condition_a" in data:
                    experiments.append(
                        load_from_baseline(path, "condition_a", ResearchHypothesis.H1)
                    )
            elif isinstance(data, dict) and "problem_id" in data:
                experiments.append(load_from_batch_file(path, h))
            else:
                experiments.append(load_from_batch_file(path, h))
        except Exception as exc:
            logger.warning(f"Could not load {path.name}: {exc}")

    return experiments


# ---------------------------------------------------------------------------
# Merge experiments into ExperimentSet
# ---------------------------------------------------------------------------


def merge_into_set(
    experiments: list[Experiment],
    name: str = "Auto-merged evaluation",
) -> ExperimentSet:
    """Merge experiments grouped by hypothesis into an ExperimentSet."""
    exp_set = ExperimentSet(name=name)
    by_hypothesis: dict[str, list[Experiment]] = {}

    for exp in experiments:
        key = exp.hypothesis.value
        if key not in by_hypothesis:
            by_hypothesis[key] = []
        by_hypothesis[key].append(exp)

    for h_key, exps in by_hypothesis.items():
        all_runs: list[ExperimentRun] = []
        for e in exps:
            all_runs.extend(e.runs)
        merged = Experiment(
            name=f"{name} - {h_key}",
            hypothesis=exps[0].hypothesis,
            runs=all_runs,
        )
        exp_set.experiments[h_key] = merged

    total = sum(len(e.runs) for e in exp_set.experiments.values())
    logger.info(f"Merged {len(experiments)} experiments into set with {total} total runs")
    return exp_set


# ---------------------------------------------------------------------------
# Import Redis-based runs (lightweight — no Redis dependency in this module)
# ---------------------------------------------------------------------------


def runtime_run_from_dict(
    data: dict[str, Any],
    hypothesis: ResearchHypothesis = ResearchHypothesis.H2,
) -> ExperimentRun:
    """Build an ExperimentRun from a plain dict (e.g. coming from Redis or runner callback)."""
    sm_data = data.get("system_metrics", {})
    rm_data = data.get("research_metrics", {})

    sm = SystemMetrics(
        duration_seconds=sm_data.get("duration_seconds", 0),
        retries=sm_data.get("retries", 0),
        crashes=sm_data.get("crashes", 0),
        crashes_recovered=sm_data.get("crashes_recovered", 0),
        peak_ram_mb=sm_data.get("peak_ram_mb"),
        peak_gpu_mb=sm_data.get("peak_gpu_mb"),
        wall_clock_time_s=sm_data.get("wall_clock_time_s", 0),
        orchestration_overhead_s=sm_data.get("orchestration_overhead_s", 0),
    )
    rm = ResearchMetrics(
        prediction_error_duration_pct=rm_data.get("prediction_error_duration_pct"),
        prediction_error_ram_pct=rm_data.get("prediction_error_ram_pct"),
        prediction_bias_duration_pct=rm_data.get("prediction_bias_duration_pct"),
        prediction_bias_ram_pct=rm_data.get("prediction_bias_ram_pct"),
        deployment_success=rm_data.get("deployment_success"),
        planner_confidence_score=rm_data.get("planner_confidence_score"),
        actual_success=rm_data.get("actual_success"),
        architecture_selection_gap=rm_data.get("architecture_selection_gap"),
        patch_success_rate=rm_data.get("patch_success_rate"),
        fallback_success_rate=rm_data.get("fallback_success_rate"),
        final_metric=rm_data.get("final_metric"),
    )

    calibration_raw = data.get("calibration")
    calibration = None
    if calibration_raw:
        calibration = PlanningCalibration(**calibration_raw)

    arch_raw = data.get("architecture_accuracy")
    arch = None
    if arch_raw:
        arch = ArchitectureSelectionAccuracy(**arch_raw)

    lc_points = []
    for pt in data.get("learning_curve", []):
        if isinstance(pt, dict):
            lc_points.append(LearningCurvePoint(**pt))

    fc = data.get("failure_category")
    if isinstance(fc, str):
        try:
            fc = FailureCategory(fc)
        except ValueError:
            fc = None

    return ExperimentRun(
        job_id=data.get("job_id", ""),
        problem_id=data.get("problem_id", ""),
        hypothesis=hypothesis,
        system_metrics=sm,
        research_metrics=rm,
        calibration=calibration,
        learning_curve=lc_points,
        architecture_accuracy=arch,
        failure_category=fc,
        execution_outcome=data.get("execution_outcome", {}),
        prediction_error=data.get("prediction_error", {}),
        replicability=data.get("replicability", {}),
    )

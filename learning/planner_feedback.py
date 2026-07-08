"""Compute PlanningHints from historical execution outcomes.

This module bridges execution experience back to the Planner.
It queries ChromaDB for similar past outcomes, computes aggregates,
and produces lightweight PlanningHints the Planner consumes.
No LLM calls. Pure aggregation.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timezone
from typing import Any

from evaluation import config as eval_config
from prometheus.planner.models import PlanningHints

logger = logging.getLogger(__name__)

_MIN_EVIDENCE = 3
_MAX_HISTORICAL_WEIGHT = 0.7


async def compute_planning_hints(
    spec: dict[str, Any], redis: Any, job_id: str
) -> PlanningHints:
    """Produce PlanningHints from historical outcomes similar to the given spec.

    Args:
        spec: MissionSpecification dict for the current job.
        redis: Redis async client for reading/writing cached data.
        job_id: The job being planned (used for caching).

    Returns:
        PlanningHints with evidence_count=0 if insufficient data.
    """
    if eval_config.DISABLE_PLANNER:
        logger.info(f"[job={job_id}] Planner disabled — returning empty hints")
        return PlanningHints()

    dataset = spec.get("dataset_analysis", {})
    pipeline = spec.get("recommended_pipeline", {})

    modality = dataset.get("modality", "tabular")
    task_type = dataset.get("task_type", "classification")
    architecture = pipeline.get("architecture", "lightgbm")
    num_rows = dataset.get("num_rows", 0)
    num_columns = dataset.get("num_columns", 0)

    hints = PlanningHints()

    # Query ChromaDB for similar past experiences
    outcomes = await _fetch_similar_outcomes(
        modality=modality,
        task_type=task_type,
        architecture=architecture,
        num_rows=num_rows,
        num_columns=num_columns,
    )

    if not outcomes or len(outcomes) < _MIN_EVIDENCE:
        logger.info(
            f"PlanningHints: insufficient evidence for {architecture} "
            f"(found {len(outcomes) if outcomes else 0}, need {_MIN_EVIDENCE})"
        )
        return hints

    hints.evidence_count = len(outcomes)

    # Duration
    durations = [o.get("actual_training_minutes") or o.get("duration_seconds", 0) / 60.0
                 for o in outcomes if (o.get("actual_training_minutes") or o.get("duration_seconds"))]
    if durations:
        hints.estimated_duration_minutes = round(statistics.median(durations))

    # RAM
    rams = [float(o["peak_ram_mb"]) for o in outcomes
            if o.get("peak_ram_mb") and o["peak_ram_mb"] != "none"]
    if rams:
        hints.estimated_ram_mb = round(statistics.median(rams))

    # VRAM
    vrams = [float(o["peak_gpu_mb"]) for o in outcomes
             if o.get("peak_gpu_mb") and o["peak_gpu_mb"] != "none"]
    if vrams:
        hints.estimated_vram_mb = round(statistics.median(vrams))

    # GPU recommendation
    gpu_counts = [o.get("gpu_used", False) for o in outcomes
                  if o.get("gpu_used") is not None]
    if gpu_counts:
        gpu_ratio = sum(gpu_counts) / len(gpu_counts)
        hints.gpu_recommended = gpu_ratio > 0.5

    # Fallback models ranked by pass rate
    hints.fallback_models = _rank_fallback_models(outcomes, architecture)

    # Prediction error from all available
    errors = [float(o["prediction_error"]) for o in outcomes
              if o.get("prediction_error") is not None]
    if errors:
        hints.last_prediction_error_pct = round(
            statistics.median(errors) * 100, 1
        )

    logger.info(
        f"PlanningHints: {architecture} n={hints.evidence_count} "
        f"dur={hints.estimated_duration_minutes}min "
        f"ram={hints.estimated_ram_mb}MB "
        f"fallback={hints.fallback_models}"
    )

    return hints


async def _fetch_similar_outcomes(
    modality: str,
    task_type: str,
    architecture: str,
    num_rows: int,
    num_columns: int,
    k: int = 50,
) -> list[dict[str, Any]]:
    """Fetch past outcomes from ChromaDB similar to this job's profile."""
    try:
        from memory.collections.experience_memory import query_similar_experiences

        results = query_similar_experiences(
            modality=modality,
            task_type=task_type,
            num_rows=num_rows,
            architecture=architecture,
            k=k,
            num_columns=num_columns,
        )
        return results or []
    except Exception as e:
        logger.warning(f"Failed to query similar experiences: {e}")
        return []


def _rank_fallback_models(
    outcomes: list[dict[str, Any]], current_arch: str
) -> list[str] | None:
    """Rank architectures by pass rate from historical outcomes, excluding current.

    Returns ordered list of architectures with highest pass rate first.
    None if insufficient data.
    """
    arch_stats: dict[str, list[bool]] = {}
    for o in outcomes:
        arch = o.get("architecture", "")
        outcome = o.get("outcome", "")
        if arch and arch != current_arch:
            if arch not in arch_stats:
                arch_stats[arch] = []
            arch_stats[arch].append(outcome == "pass")

    scored = []
    for arch, passes in arch_stats.items():
        if len(passes) >= _MIN_EVIDENCE:
            rate = sum(passes) / len(passes)
            scored.append((rate, arch, len(passes)))

    scored.sort(key=lambda x: (-x[0], -x[2]))
    return [arch for _, arch, _ in scored] if scored else None


def compute_prediction_error(
    predicted_duration_minutes: int | None,
    predicted_ram_mb: int | None,
    predicted_vram_mb: int | None,
    actual_duration_seconds: float,
    actual_ram_mb: float | None,
    actual_vram_mb: float | None,
    actual_retries: int,
    actual_deployment_success: bool | None,
) -> dict[str, Any]:
    """Compare Planner predictions against actual execution outcomes.

    Returns a dict with percentage errors per dimension.
    """
    errors: dict[str, Any] = {}

    actual_duration_min = actual_duration_seconds / 60.0

    if predicted_duration_minutes and actual_duration_min > 0:
        errors["duration_error_pct"] = round(
            abs(actual_duration_min - predicted_duration_minutes)
            / predicted_duration_minutes * 100, 1
        )
        errors["duration_bias"] = round(
            (actual_duration_min - predicted_duration_minutes)
            / predicted_duration_minutes * 100, 1
        )

    if predicted_ram_mb and actual_ram_mb and actual_ram_mb > 0:
        errors["ram_error_pct"] = round(
            abs(actual_ram_mb - predicted_ram_mb)
            / predicted_ram_mb * 100, 1
        )
        errors["ram_bias"] = round(
            (actual_ram_mb - predicted_ram_mb)
            / predicted_ram_mb * 100, 1
        )

    if predicted_vram_mb and actual_vram_mb and actual_vram_mb > 0:
        errors["vram_error_pct"] = round(
            abs(actual_vram_mb - predicted_vram_mb)
            / predicted_vram_mb * 100, 1
        )

    errors["retries_accuracy"] = (
        "exact" if actual_retries == 0
        else "over" if actual_retries > 0
        else "under"
    )

    if actual_deployment_success is not None:
        errors["deployment_accuracy"] = actual_deployment_success

    return errors


async def store_prediction_error(
    redis: Any, job_id: str, errors: dict[str, Any]
) -> None:
    """Store prediction error in Redis for CLI observability."""
    key = f"job:{job_id}:prediction_error"
    try:
        await redis.set(key, json.dumps(errors))
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to store prediction error: {e}")

    # Append to rolling history (last 50)
    history_key = "prometheus:prediction_error_history"
    try:
        entry = {"job_id": job_id, **errors}
        entry["_timestamp"] = datetime.now(timezone.utc).isoformat()
        history_raw = await redis.get(history_key)
        history = json.loads(history_raw) if history_raw else []
        history.append(entry)
        # Keep last 200
        if len(history) > 200:
            history = history[-200:]
        await redis.set(history_key, json.dumps(history))
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to update error history: {e}")


async def get_execution_stats(redis: Any) -> dict[str, Any]:
    """Compute aggregate execution statistics across all architectures.

    Returns a dict keyed by architecture with: count, pass_rate,
    avg_duration_min, avg_ram_mb, avg_prediction_error.
    """
    try:
        from memory.collections.experience_memory import query_similar_experiences

        results = query_similar_experiences(
            modality="", task_type="", num_rows=0, k=200
        )
    except Exception as e:
        logger.warning(f"Failed to query experience memory for stats: {e}")
        return {}

    if not results:
        return {}

    arch_data: dict[str, dict[str, Any]] = {}
    for r in results:
        arch = r.get("architecture", "unknown")
        if arch not in arch_data:
            arch_data[arch] = {
                "count": 0,
                "pass_count": 0,
                "retry_count": 0,
                "escalate_count": 0,
                "durations": [],
                "rams": [],
                "errors": [],
            }
        d = arch_data[arch]
        d["count"] += 1
        outcome = r.get("outcome", "")
        if outcome == "pass":
            d["pass_count"] += 1
        elif outcome == "retry":
            d["retry_count"] += 1
        else:
            d["escalate_count"] += 1

        duration = r.get("actual_training_minutes")
        if duration is not None:
            d["durations"].append(duration)

        ram = r.get("peak_ram_mb")
        if ram is not None and ram != "none":
            try:
                d["rams"].append(float(ram))
            except (ValueError, TypeError):
                pass

        err = r.get("prediction_error")
        if err is not None:
            d["errors"].append(err)

    stats = {}
    for arch, d in arch_data.items():
        s: dict[str, Any] = {
            "count": d["count"],
            "pass_rate": round(d["pass_count"] / d["count"], 4) if d["count"] else 0,
            "retry_rate": round(d["retry_count"] / d["count"], 4) if d["count"] else 0,
            "escalate_rate": round(d["escalate_count"] / d["count"], 4) if d["count"] else 0,
        }
        if d["durations"]:
            s["avg_duration_min"] = round(statistics.mean(d["durations"]), 1)
            s["median_duration_min"] = round(statistics.median(d["durations"]), 1)
        if d["rams"]:
            s["avg_ram_mb"] = round(statistics.mean(d["rams"]), 0)
        if d["errors"]:
            s["avg_prediction_error"] = round(
                statistics.mean([e for e in d["errors"] if e is not None]) * 100, 1
            )
        stats[arch] = s

    return stats

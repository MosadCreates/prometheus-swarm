"""Mission Report Generator.

Produces a structured JSON report + human-readable Markdown summary of a completed job.
Reads all data from Redis keys, event streams, patch log, and experience memory.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any
from runtime.paths import get_job_paths, get_paths

logger = logging.getLogger(__name__)


async def generate_mission_report(
    job_id: str,
    redis_client: Any,
    deploy_data: dict[str, Any] | None = None,
    pipeline_duration_seconds: float | None = None,
) -> str:
    """Generate a mission report for a completed job.

    Reads mission brief, spec, plan, eval report, patch log, epoch events,
    and deployment data from Redis and files. Writes mission_report.json
    and mission_report.md to outputs/{job_id}/.

    Args:
        job_id: UUID of the job
        redis_client: aioredis client for reading Redis keys
        deploy_data: ENDPOINT_LIVE event payload (if deployed)
        pipeline_duration_seconds: Total pipeline wall-clock time

    Returns:
        Path to the generated JSON report file.
    """
    data = await _compile_report_data(job_id, redis_client, deploy_data, pipeline_duration_seconds)
    data = _compute_prediction_vs_actual(data)
    data = _generate_lessons_learned(data)

    jp = get_job_paths(job_id)
    out_dir = jp.job_dir
    os.makedirs(out_dir, exist_ok=True)

    json_path = out_dir / f"mission_report_{job_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

    md_path = out_dir / f"mission_report_{job_id}.md"
    md_content = _render_markdown(data)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    logger.info(f"Mission report written to {json_path} and {md_path}")
    return json_path


# ── Helper: read patch_log entries for a job ────────────────────────────────


def _read_patch_log_for_job(job_id: str) -> list[dict[str, Any]]:
    """Read all patch log entries for the given job from patch_log.jsonl."""
    entries: list[dict[str, Any]] = []
    path = str(get_paths().research / "patch_log.jsonl")
    if not os.path.exists(path):
        return entries
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("job_id") == job_id:
                        entries.append(entry)
                except (json.JSONDecodeError, TypeError):
                    continue
    except OSError:
        pass
    return entries


# ── Helper: read epoch events from furnace_feed stream ─────────────────────


async def _read_epoch_events(
    redis_client: Any, job_id: str, max_samples: int = 20
) -> list[dict[str, Any]]:
    """Read epoch events from the furnace_feed stream for this job.

    Returns a sampled list of epoch events (up to max_samples).
    """
    events: list[dict[str, Any]] = []
    try:
        raw = await redis_client.xrange("furnace_feed", min="-", max="+", count=200)
        for entry_id, fields in raw:
            if isinstance(fields, dict) and fields.get("job_id") == job_id:
                event = {
                    "epoch": fields.get("epoch"),
                    "train_loss": fields.get("train_loss"),
                    "val_loss": fields.get("val_loss"),
                    "eta_seconds": fields.get("eta_seconds"),
                    "timestamp": fields.get("timestamp"),
                }
                events.append(event)
        # Sample if too many
        if len(events) > max_samples:
            step = len(events) // max_samples
            events = events[::step][:max_samples]
    except Exception:
        pass
    return events


# ── Helper: query experience memory for cross-reference ─────────────────────


def _query_experience_comparison(
    modality: str = "",
    task_type: str = "",
    num_rows: int = 0,
    num_columns: int = 0,
    architecture: str = "",
) -> dict[str, Any]:
    """Query experience memory for similar past jobs and return a summary.

    Gracefully returns empty dict if ChromaDB is unreachable.
    """
    try:
        import socket

        host = os.environ.get("CHROMA_HOST", "localhost")
        port = int(os.environ.get("CHROMA_PORT", 8000))
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        available = sock.connect_ex((host, port)) == 0
        sock.close()
        if not available:
            return {}
    except Exception:
        return {}

    try:
        from memory.collections.experience_memory import query_similar_experiences

        experiences = query_similar_experiences(
            modality=modality,
            task_type=task_type,
            num_rows=num_rows,
            k=5,
        )
        if not experiences:
            return {}

        completed = [e for e in experiences if e.get("achieved_metric") is not None]
        if not completed:
            return {"total_similar": len(experiences), "completed": 0}

        metrics = [e["achieved_metric"] for e in completed if e["achieved_metric"] is not None]
        crashes = [e["total_crashes"] for e in completed]
        outcomes = [e["outcome"] for e in completed]
        archs = [e["architecture"] for e in completed]

        return {
            "total_similar": len(experiences),
            "completed": len(completed),
            "avg_metric": round(sum(metrics) / len(metrics), 4) if metrics else None,
            "avg_crashes": round(sum(crashes) / len(crashes), 1) if crashes else 0.0,
            "pass_ratio": round(outcomes.count("pass") / len(outcomes), 2) if outcomes else 0.0,
            "most_common_architecture": max(set(archs), key=archs.count) if archs else "",
            "best_metric": max(metrics) if metrics else None,
        }
    except Exception as exc:
        logger.debug(f"[mission_report] Experience query failed (non-fatal): {exc}")
        return {}


# ── Main data compilation ──────────────────────────────────────────────────


async def _compile_report_data(
    job_id: str,
    redis_client: Any,
    deploy_data: dict[str, Any] | None,
    pipeline_duration_seconds: float | None,
) -> dict[str, Any]:
    """Read all job data from Redis and files, build the raw report dict."""
    report: dict[str, Any] = {
        "report_version": "2.0",
        "job_id": job_id,
        "status": "unknown",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    # ── Read status ──────────────────────────────────────────────────────
    try:
        status = await redis_client.get(f"job:{job_id}:status")
        if status:
            report["status"] = status.decode() if isinstance(status, bytes) else status
    except Exception:
        pass

    # ── Read mission brief + spec ────────────────────────────────────────
    brief: dict = {}
    try:
        raw = await redis_client.get(f"job:{job_id}:mission_brief")
        if raw:
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            brief = json.loads(raw_str) if isinstance(raw_str, str) else raw
    except Exception as e:
        logger.warning(f"[mission_report] Failed to read mission brief: {e}")

    spec: dict = {}
    try:
        raw = await redis_client.get(f"job:{job_id}:mission_spec")
        if raw:
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            spec = json.loads(raw_str) if isinstance(raw_str, str) else raw
    except Exception as e:
        logger.warning(f"[mission_report] Failed to read mission spec: {e}")

    report["overview"] = _build_overview(
        brief if brief else spec.get("objective", {}), pipeline_duration_seconds
    )

    # ── Scout Analysis (enriched from spec, Stage 1+4) ───────────────────
    if spec:
        dq = spec.get("data_quality", {})
        eng_decisions = spec.get("engineering_decisions", {})
        if not eng_decisions:
            eng_decisions = {
                "problem_type": spec.get("objective", {}).get("task_type", "unknown"),
                "data_quality": dq.get("overall_rating", "unknown"),
                "architecture": spec.get("recommended_pipeline", {}).get(
                    "primary_architecture",
                    (
                        spec.get("candidate_models", [None])[0]
                        if spec.get("candidate_models")
                        else "unknown"
                    ),
                ),
            }
        report["scout_analysis"] = {
            "decisions": eng_decisions,
            "risks": spec.get("risks", []),
            "overall_confidence": (
                spec.get("confidence", {}).get("overall")
                if isinstance(spec.get("confidence"), dict)
                else spec.get("overall_confidence")
            ),
            "data_quality_rating": dq.get("overall_rating"),
            "feature_engineering": spec.get("feature_engineering", {}),
            "outlier_strategy": spec.get("outlier_strategy"),
        }
        # Add data quality details
        col_info = _build_column_summary(spec)
        report["scout_analysis"]["data_quality_details"] = {
            "class_imbalance_ratio": dq.get("class_imbalance_ratio"),
            "missing_value_rate": _summarize_missing_rates(dq.get("missing_value_rate", {})),
            "high_missing_columns": dq.get("high_missing_columns", []),
            "high_cardinality_columns": dq.get("high_cardinality_columns", []),
            "duplicate_rows": dq.get("duplicate_rows", 0),
            "outlier_counts": dq.get("outlier_counts", {}),
            "data_warnings": dq.get("data_warnings", []),
            "columns": col_info,
        }
    else:
        reasoning = brief.get("engineering_reasoning", {})
        if reasoning:
            report["scout_analysis"] = {
                "decisions": {
                    k: v for k, v in reasoning.items() if isinstance(v, dict) and "title" in v
                },
                "risks": reasoning.get("risks", []),
                "overall_confidence": reasoning.get("overall_confidence"),
            }

    # ── Forge Plan ───────────────────────────────────────────────────────
    plan: dict = {}
    try:
        raw = await redis_client.get(f"job:{job_id}:engineering_plan")
        if raw:
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            plan = json.loads(raw_str) if isinstance(raw_str, str) else raw
    except Exception:
        pass
    if plan:
        report["forge_plan"] = {
            "architecture_selected": plan.get("architecture_selected"),
            "alternatives": plan.get("alternatives", []),
            "preprocessing_pipeline": plan.get("preprocessing_pipeline", []),
            "hyperparameter_strategy": plan.get("hyperparameter_strategy"),
            "computational_budget": plan.get("computational_budget"),
            "fallback_plan": plan.get("fallback_plan"),
        }

    # ── Training outcome ─────────────────────────────────────────────────
    training: dict = {}
    try:
        raw = await redis_client.get(f"job:{job_id}:training_complete")
        if raw:
            raw_str = raw.decode() if isinstance(raw, bytes) else raw
            training = json.loads(raw_str) if isinstance(raw_str, str) else raw
    except Exception:
        pass

    crash_count = 0
    try:
        crash_raw = await redis_client.get(f"job:{job_id}:crash_count")
        if crash_raw:
            crash_count = int(crash_raw.decode() if isinstance(crash_raw, bytes) else crash_raw)
    except Exception:
        pass

    report["training_outcome"] = {
        "best_val_metric": training.get("best_val_metric"),
        "total_epochs": training.get("total_epochs"),
        "checkpoint_path": training.get(
            "checkpoint_path", str(get_job_paths(job_id).checkpoint_path)
        ),
        "total_crashes": crash_count,
        "crashes_recovered": training.get("total_crashes_recovered", 0),
        "actual_training_minutes": _compute_training_duration(job_id, redis_client),
    }

    # ── Epoch timeline ───────────────────────────────────────────────────
    epoch_events = await _read_epoch_events(redis_client, job_id)
    if epoch_events:
        report["training_outcome"]["epoch_timeline"] = epoch_events

    # ── Failures & Recoveries (from patch_log) ──────────────────────────
    patch_entries = _read_patch_log_for_job(job_id)
    if patch_entries:
        failures = []
        for entry in patch_entries:
            failures.append(
                {
                    "attempt_number": entry.get("attempt_number"),
                    "exception_type": entry.get("exception_type"),
                    "error_category": entry.get("error_taxonomy_category"),
                    "repair_strategy": entry.get("repair_strategy_used"),
                    "sandbox_result": entry.get("sandbox_test_result"),
                    "patch_outcome": entry.get("patch_outcome"),
                    "confidence_score": entry.get("confidence_score"),
                    "lines_changed": entry.get("lines_changed"),
                    "diff_excerpt": (
                        entry.get("diff_applied", "")[:300] if entry.get("diff_applied") else ""
                    ),
                }
            )
        report["failures_and_recoveries"] = {
            "total_patch_attempts": len(patch_entries),
            "successful_patches": sum(
                1 for e in patch_entries if e.get("patch_outcome") == "success"
            ),
            "rollbacks": sum(1 for e in patch_entries if e.get("patch_outcome") == "rollback"),
            "escalations": sum(1 for e in patch_entries if e.get("patch_outcome") == "escalated"),
            "error_categories": list(
                {e.get("error_taxonomy_category", "unknown") for e in patch_entries}
            ),
            "entries": failures,
        }

    # ── Evaluation ───────────────────────────────────────────────────────
    eval_report: dict = {}
    eval_path = str(get_job_paths(job_id).eval_report_path)
    try:
        if os.path.exists(eval_path):
            with open(eval_path, encoding="utf-8") as f:
                eval_report = json.load(f)
    except Exception:
        pass
    if eval_report:
        report["evaluation"] = {
            "primary_metric": eval_report.get("metrics", {}).get(
                "primary_metric", eval_report.get("primary_metric", "auc_roc")
            ),
            "primary_metric_value": eval_report.get("metrics", {}).get(
                eval_report.get("metrics", {}).get("primary_metric", "auc_roc"),
                eval_report.get("primary_metric_value", 0.0),
            ),
            "all_metrics": eval_report.get("metrics", {}),
            "decision": eval_report.get("decision", "unknown"),
            "decision_reason": eval_report.get("reason", ""),
        }
        metrics_dict = eval_report.get("metrics", {})
        for key in ("auc_roc", "f1", "accuracy", "rmse", "mae"):
            if key in metrics_dict:
                report["evaluation"]["primary_metric"] = key
                report["evaluation"]["primary_metric_value"] = metrics_dict[key]
                break

    # ── Deployment ───────────────────────────────────────────────────────
    if deploy_data:
        report["deployment"] = {
            "endpoint_url": deploy_data.get("endpoint_url"),
            "model_format": deploy_data.get("model_format", "onnx"),
            "p95_latency_ms": deploy_data.get("p95_latency_ms"),
            "val_metric": deploy_data.get("val_metric"),
        }

    # ── Experience memory cross-reference (Stage 3+4) ────────────────────
    modality = brief.get("modality", spec.get("objective", {}).get("modality", ""))
    task_type = brief.get("task_type", spec.get("objective", {}).get("task_type", ""))
    ds = brief.get("dataset", spec.get("dataset_analysis", {}))
    num_rows = ds.get("num_rows", 0)
    num_cols = ds.get("num_columns", 0)
    arch = plan.get("architecture_selected", {}).get("name", "")

    exp = _query_experience_comparison(
        modality=modality,
        task_type=task_type,
        num_rows=num_rows,
        num_columns=num_cols,
        architecture=arch,
    )
    if exp:
        report["experience_comparison"] = exp

    return report


def _build_column_summary(spec: dict) -> dict[str, Any]:
    """Extract a human-readable column summary from the mission spec."""
    ds = spec.get("dataset_analysis", {})
    return {
        "total_columns": ds.get("num_columns", 0),
        "numeric": len(ds.get("numeric_columns", [])),
        "categorical": len(ds.get("categorical_columns", [])),
        "text": len(ds.get("text_columns", [])),
        "named_numeric": ds.get("numeric_columns", [])[:10],
        "named_categorical": ds.get("categorical_columns", [])[:10],
    }


def _summarize_missing_rates(rates: dict[str, float]) -> str:
    """Summarize missing value rates for the report."""
    if not rates:
        return "none"
    above_zero = {k: v for k, v in rates.items() if v > 0}
    if not above_zero:
        return "no missing values"
    high = {k: v for k, v in above_zero.items() if v > 0.1}
    if high:
        cols = ", ".join(f"{k}={v:.0%}" for k, v in sorted(high.items(), key=lambda x: -x[1])[:5])
        return f"high in {len(high)} columns: {cols}"
    cols = ", ".join(f"{k}={v:.1%}" for k, v in sorted(above_zero.items(), key=lambda x: -x[1])[:5])
    return f"low in {len(above_zero)} columns: {cols}"


def _build_overview(
    brief_or_objective: dict, pipeline_duration_seconds: float | None
) -> dict[str, Any]:
    dataset = brief_or_objective.get("dataset", {})
    if not dataset and "file_path" in brief_or_objective:
        dataset = brief_or_objective
    return {
        "problem_description": brief_or_objective.get("problem_description", "")[:200],
        "task_type": brief_or_objective.get("task_type", "unknown"),
        "modality": brief_or_objective.get("modality", "unknown"),
        "dataset": {
            "file_path": dataset.get("file_path", ""),
            "num_rows": dataset.get("num_rows", 0),
            "num_columns": dataset.get("num_columns", 0),
        },
        "pipeline_duration_seconds": pipeline_duration_seconds,
    }


def _compute_training_duration(job_id: str, redis_client: Any) -> float | None:
    try:
        raw = redis_client.get(f"job:{job_id}:training_started_at")
        if not raw:
            return None
        started_at = float(raw.decode() if isinstance(raw, bytes) else raw)
        now = datetime.now(timezone.utc).timestamp()
        return round((now - started_at) / 60.0, 1)
    except Exception:
        return None


def _compute_prediction_vs_actual(data: dict[str, Any]) -> dict[str, Any]:
    """Compare estimates from the engineering plan against actual outcomes."""
    comparisons: list[dict[str, Any]] = []
    forge = data.get("forge_plan", {})
    arch = forge.get("architecture_selected", {})
    eval_data = data.get("evaluation", {})
    training = data.get("training_outcome", {})

    # Metric range vs achieved
    expected_range = arch.get("expected_metric_range")
    actual_metric = eval_data.get("primary_metric_value") or training.get("best_val_metric")
    if expected_range and len(expected_range) == 2 and actual_metric is not None:
        mid = (expected_range[0] + expected_range[1]) / 2.0
        error_pct = round(abs(actual_metric - mid) / max(abs(mid), 0.001) * 100, 1)
        comparisons.append(
            {
                "estimate": "metric_range",
                "predicted": f"[{expected_range[0]:.2f}, {expected_range[1]:.2f}]",
                "actual": round(actual_metric, 4),
                "error_pct": error_pct,
                "within_range": expected_range[0] <= actual_metric <= expected_range[1],
            }
        )

    # Training time vs expected
    expected_min = arch.get("expected_training_minutes")
    actual_min = training.get("actual_training_minutes")
    if expected_min and actual_min is not None:
        error_pct = round(abs(actual_min - expected_min) / max(expected_min, 1) * 100, 1)
        comparisons.append(
            {
                "estimate": "training_time",
                "predicted": f"{expected_min} min",
                "actual": round(actual_min, 1),
                "error_pct": error_pct,
            }
        )

    # Confidence calibration
    overall_conf = data.get("scout_analysis", {}).get("overall_confidence")
    outcome = eval_data.get("decision", data.get("status", ""))
    if overall_conf and outcome:
        calibrated = (
            "well_calibrated"
            if (overall_conf >= 0.7 and outcome == "pass")
            or (overall_conf < 0.5 and outcome == "escalate")
            else (
                "overconfident"
                if overall_conf >= 0.7 and outcome in ("escalate", "retry")
                else "underconfident" if overall_conf < 0.5 and outcome == "pass" else "neutral"
            )
        )
        comparisons.append(
            {
                "estimate": "confidence_calibration",
                "predicted": overall_conf,
                "actual": outcome,
                "calibration": calibrated,
            }
        )

    data["prediction_vs_actual"] = comparisons
    return data


def _generate_lessons_learned(data: dict[str, Any]) -> dict[str, Any]:
    """Extract human-readable lessons from the prediction vs actual comparisons."""
    lessons: list[str] = []
    comparisons = data.get("prediction_vs_actual", [])
    arch = data.get("forge_plan", {}).get("architecture_selected", {})
    status = data.get("status", "unknown")
    eval_data = data.get("evaluation", {})

    # Metric accuracy
    for c in comparisons:
        if c["estimate"] == "metric_range":
            arch_name = arch.get("name", "model")
            actual = c["actual"]
            p_low, p_high = c["predicted"].replace("[", "").replace("]", "").split(", ")
            if c.get("within_range"):
                lessons.append(
                    f"{arch_name} achieved metric {actual} within predicted range "
                    f"[{p_low}, {p_high}] (error: {c['error_pct']}%)"
                )
            else:
                lessons.append(
                    f"{arch_name} achieved metric {actual} outside predicted range "
                    f"[{p_low}, {p_high}] (error: {c['error_pct']}%)"
                )

        elif c["estimate"] == "training_time":
            diff = "faster" if c["actual"] < float(c["predicted"].split()[0]) else "slower"
            lessons.append(
                f"Training was {diff} than estimated "
                f"(actual: {c['actual']} min vs predicted: {c['predicted']})"
            )

        elif c["estimate"] == "confidence_calibration":
            cal = c.get("calibration", "neutral")
            if cal == "well_calibrated":
                lessons.append(
                    f"Scout's confidence ({c['predicted']}) aligned with outcome ({c['actual']})"
                )
            elif cal == "overconfident":
                lessons.append(
                    f"Scout was overconfident ({c['predicted']}) given outcome ({c['actual']})"
                )
            elif cal == "underconfident":
                lessons.append(
                    f"Scout was underconfident ({c['predicted']}) given outcome ({c['actual']})"
                )

    # Crashes
    training = data.get("training_outcome", {})
    crashes = training.get("total_crashes", 0)
    recovered = training.get("crashes_recovered", 0)
    if crashes == 0:
        lessons.append("No training crashes occurred")
    elif crashes == recovered:
        lessons.append(f"All {crashes} training crashes were successfully recovered by Dissect")
    else:
        lessons.append(
            f"{recovered}/{crashes} training crashes recovered; {crashes - recovered} required escalation"
        )

    # Patch-specific lessons from Failures & Recoveries
    failures = data.get("failures_and_recoveries", {})
    entries = failures.get("entries", [])
    if entries:
        error_cats = failures.get("error_categories", [])
        if error_cats:
            lessons.append(f"Encountered errors: {', '.join(error_cats)}")
        for entry in entries:
            outcome = entry.get("patch_outcome", "")
            exc = entry.get("exception_type", "?")
            cat = entry.get("error_category", "?")
            strategy = entry.get("repair_strategy", "?")
            if outcome == "success":
                lessons.append(f"Dissect repaired {exc} ({cat}) using {strategy}")
            elif outcome == "rollback":
                lessons.append(f"Patch for {exc} ({cat}) failed sandbox verification — rolled back")
            elif outcome == "escalated":
                lessons.append(f"All patch attempts for {exc} ({cat}) failed — escalated to human")

    # Data quality lessons
    scout = data.get("scout_analysis", {})
    dq = scout.get("data_quality_details", {}) if isinstance(scout, dict) else {}
    if isinstance(dq, dict):
        imbalance = dq.get("class_imbalance_ratio")
        if imbalance and isinstance(imbalance, (int, float)) and imbalance > 5:
            lessons.append(
                f"High class imbalance ({imbalance}:1) — {dq.get('imbalance_strategy', 'strategy applied')}"
            )
        warnings = dq.get("data_warnings", [])
        if warnings and len(warnings) <= 3:
            for w in warnings:
                lessons.append(f"Data warning: {w}")

    # Experience comparison insights
    exp = data.get("experience_comparison", {})
    if exp and exp.get("completed", 0) > 0:
        this_metric = training.get("best_val_metric")
        avg_metric = exp.get("avg_metric")
        if this_metric is not None and avg_metric is not None:
            diff = this_metric - avg_metric
            if diff > 0.02:
                lessons.append(
                    f"This job outperformed similar past jobs by {diff:.3f} ({avg_metric:.3f} avg vs {this_metric:.3f})"
                )
            elif diff < -0.02:
                lessons.append(
                    f"This job underperformed similar past jobs by {abs(diff):.3f} ({avg_metric:.3f} avg vs {this_metric:.3f})"
                )
            else:
                lessons.append(
                    f"This job is in line with similar past jobs ({avg_metric:.3f} avg vs {this_metric:.3f})"
                )
        avg_crashes = exp.get("avg_crashes", 0)
        job_crashes = training.get("total_crashes", 0)
        if avg_crashes > 0 and job_crashes < avg_crashes / 2:
            lessons.append(
                f"Fewer crashes than average ({job_crashes} vs {avg_crashes:.1f} avg across similar jobs)"
            )

    # Outcome summary
    decision = eval_data.get("decision", status)
    if decision == "pass":
        endpoint = data.get("deployment", {}).get("endpoint_url", "")
        if endpoint:
            lessons.append(f"Model deployed at {endpoint}")
        else:
            lessons.append("Model passed evaluation and is ready for deployment")
    elif decision == "retry":
        lessons.append("Evaluation triggered retry — switching to alternative architecture")
    elif decision == "escalate":
        lessons.append("Job escalated to human review — automatic resolution was not possible")

    data["lessons_learned"] = lessons
    return data


def _render_markdown(data: dict[str, Any]) -> str:
    """Render the report data as a human-readable Markdown document."""
    lines: list[str] = []
    overview = data.get("overview", {})
    status = data.get("status", "unknown")
    job_id = data.get("job_id", "?")
    created = data.get("created_at", "")[:19].replace("T", " ")

    status_icon = {"COMPLETED": "✅", "PASS": "✅", "ESCALATED": "❌", "FAILED": "❌", "pass": "✅"}
    icon = "✅" if status in status_icon and status_icon[status] == "✅" else "❌"
    for key, val in status_icon.items():
        if key in status.upper() or key == status:
            icon = val
            break

    lines.append(f"# Mission Report `{job_id[:8]}...`")
    lines.append("")
    lines.append(f"**Status:** {status}")
    lines.append(f"**Created:** {created}")
    lines.append("")

    # 1. Overview
    lines.append("---")
    lines.append("## 1. Overview")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    ds = overview.get("dataset", {})
    lines.append(f"| Problem | {overview.get('problem_description', 'N/A')} |")
    lines.append(f"| Task Type | {overview.get('task_type', 'N/A')} |")
    lines.append(f"| Modality | {overview.get('modality', 'N/A')} |")
    lines.append(
        f"| Dataset | {ds.get('file_path', 'N/A')} ({ds.get('num_rows', 0)} rows, {ds.get('num_columns', 0)} cols) |"
    )
    dur = overview.get("pipeline_duration_seconds")
    if dur:
        lines.append(f"| Pipeline Duration | {dur:.1f}s |")
    lines.append("")

    # 2. Scout Analysis
    scout = data.get("scout_analysis", {})
    if scout:
        lines.append("---")
        lines.append("## 2. Scout Analysis")
        lines.append("")
        lines.append("| Decision | Selection | Confidence |")
        lines.append("|----------|-----------|------------|")
        for key in (
            "problem_type",
            "data_quality",
            "leakage",
            "preprocessing",
            "architecture",
            "validation",
            "imbalance",
        ):
            dec = scout.get("decisions", {}).get(key, {})
            if dec:
                if isinstance(dec, dict) and "selected" in dec:
                    lines.append(
                        f"| {dec.get('title', key)} | {dec.get('selected', '')} | {dec.get('confidence', '')} |"
                    )
                elif isinstance(dec, str):
                    lines.append(f"| {key} | {dec} | |")
        oc = scout.get("overall_confidence")
        if oc is not None:
            lines.append(f"| **Overall** | | **{oc}** |")
        lines.append("")

        # Data quality details
        dq = scout.get("data_quality_details", {})
        if dq:
            lines.append("**Data Quality:**")
            lines.append("")
            imbalance = dq.get("class_imbalance_ratio")
            if imbalance:
                lines.append(f"- Class imbalance ratio: {imbalance}")
            missing = dq.get("missing_value_rate", "none")
            if missing and missing != "none":
                lines.append(f"- Missing values: {missing}")
            high_missing = dq.get("high_missing_columns", [])
            if high_missing:
                lines.append(f"- Columns with >30% missing: {', '.join(high_missing)}")
            hcc = dq.get("high_cardinality_columns", [])
            if hcc:
                lines.append(
                    f"- High cardinality columns: {', '.join(hcc[:5])}"
                    + (f" (+{len(hcc)-5} more)" if len(hcc) > 5 else "")
                )
            dups = dq.get("duplicate_rows", 0)
            if dups:
                lines.append(f"- Duplicate rows: {dups}")
            warnings = dq.get("data_warnings", [])
            if warnings:
                lines.append(f"- Warnings: {'; '.join(warnings[:3])}")
            cols = dq.get("columns", {})
            if cols:
                nc = cols.get("numeric", 0)
                cc = cols.get("categorical", 0)
                tc = cols.get("text", 0)
                lines.append(f"- Columns: {nc} numeric, {cc} categorical, {tc} text")
            lines.append("")

        risks = scout.get("risks", [])
        if risks:
            lines.append("**Risks:**")
            for r in risks:
                lines.append(f"- {r}")
            lines.append("")

        # Feature engineering + outlier strategy
        fe = scout.get("feature_engineering", {})
        if isinstance(fe, dict) and fe.get("recommendations"):
            lines.append("**Feature Engineering:**")
            for rec in fe["recommendations"][:3]:
                lines.append(f"- {rec}")
            lines.append("")
        outlier = scout.get("outlier_strategy", {})
        if isinstance(outlier, dict) and outlier.get("selected", "none") != "none":
            lines.append(f"**Outlier Strategy:** {outlier.get('selected')}")
            lines.append("")

    # 3. Forge Engineering Plan
    forge = data.get("forge_plan", {})
    if forge:
        lines.append("---")
        lines.append("## 3. Forge Engineering Plan")
        lines.append("")
        arch = forge.get("architecture_selected", {})
        if arch:
            lines.append(f"**Primary Architecture:** {arch.get('name', 'N/A')}")
            lines.append(
                f"- Expected training time: ~{arch.get('expected_training_minutes', '?')} min"
            )
            lines.append(f"- Expected peak memory: ~{arch.get('expected_ram_mb', '?')} MB")
            mr = arch.get("expected_metric_range")
            if mr:
                lines.append(f"- Expected metric range: [{mr[0]:.2f}, {mr[1]:.2f}]")
            lines.append(f"- {arch.get('reason_for_selection', '')}")
            lines.append("")

        alts = forge.get("alternatives", [])
        if alts:
            lines.append("**Alternatives Considered:**")
            for a in alts:
                amr = a.get("expected_metric_range")
                amr_str = f" [{amr[0]:.2f}, {amr[1]:.2f}]" if amr else ""
                lines.append(
                    f"- {a.get('name', '?')}: ~{a.get('expected_training_minutes', '?')} min, {a.get('expected_ram_mb', '?')} MB{amr_str}"
                )
            lines.append("")

        pipeline = forge.get("preprocessing_pipeline", [])
        if pipeline:
            lines.append("**Preprocessing Pipeline:**")
            for i, step in enumerate(pipeline, 1):
                lines.append(f"{i}. {step.get('name', '?')} ({step.get('library', '?')})")
            lines.append("")

        hp = forge.get("hyperparameter_strategy", {})
        if hp:
            lines.append(
                f"**Tuning:** {hp.get('approach', 'manual')} ({hp.get('max_trials', 1)} trials)"
            )
            lines.append("")

        budget = forge.get("computational_budget", {})
        if budget:
            lines.append(
                f"**Compute Budget:** {'GPU required' if budget.get('gpu_required') else 'CPU only'}"
            )
            lines.append("")

        fb = forge.get("fallback_plan")
        if fb:
            lines.append(f"**Fallback:** {fb}")
            lines.append("")

    # 4. Training Outcome
    training = data.get("training_outcome", {})
    if training:
        lines.append("---")
        lines.append("## 4. Training Outcome")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        if training.get("actual_training_minutes") is not None:
            lines.append(f"| Actual Training Time | {training['actual_training_minutes']} min |")
        if training.get("total_epochs") is not None:
            lines.append(f"| Total Epochs | {training['total_epochs']} |")
        lines.append(f"| Training Crashes | {training.get('total_crashes', 0)} |")
        lines.append(f"| Crashes Recovered | {training.get('crashes_recovered', 0)} |")
        if training.get("best_val_metric") is not None:
            lines.append(f"| Best Validation Metric | {training['best_val_metric']} |")
        lines.append("")

    # 5. Failures & Recoveries (Stage 4)
    failures = data.get("failures_and_recoveries", {})
    if failures and failures.get("entries"):
        lines.append("---")
        lines.append("## 5. Failures & Recoveries")
        lines.append("")
        lines.append(f"**Total patch attempts:** {failures.get('total_patch_attempts', 0)}")
        lines.append(f"**Successful:** {failures.get('successful_patches', 0)}")
        lines.append(f"**Rollbacks:** {failures.get('rollbacks', 0)}")
        lines.append(f"**Escalations:** {failures.get('escalations', 0)}")
        cats = failures.get("error_categories", [])
        if cats:
            lines.append(f"**Error categories:** {', '.join(cats)}")
        lines.append("")
        lines.append("| # | Error | Category | Repair Strategy | Outcome | Confidence |")
        lines.append("|---|-------|----------|-----------------|---------|------------|")
        for i, entry in enumerate(failures["entries"], 1):
            lines.append(
                f"| {i} | {entry.get('exception_type', '?')} | "
                f"{entry.get('error_category', '?')} | "
                f"{entry.get('repair_strategy', '?')[:40]} | "
                f"{entry.get('patch_outcome', '?')} | "
                f"{entry.get('confidence_score', '?')} |"
            )
        lines.append("")

    # 6. Evaluation
    eval_data = data.get("evaluation", {})
    if eval_data:
        sec_num = "6" if failures else "5"
        lines.append("---")
        lines.append(f"## {sec_num}. Evaluation")
        lines.append("")
        decision = eval_data.get("decision", "unknown")
        dec_icon = "✅" if decision == "pass" else "🔄" if decision == "retry" else "❌"
        lines.append(f"**Decision:** {dec_icon} {decision.upper()}")
        lines.append("")
        metrics = eval_data.get("all_metrics", {})
        if metrics:
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            for k, v in metrics.items():
                if k != "primary_metric":
                    lines.append(f"| {k} | {v} |")
            lines.append("")
        lines.append(f"**Reason:** {eval_data.get('decision_reason', 'N/A')}")
        lines.append("")

    # Dynamic section numbering — next available after Evaluation
    # Evaluation is sec 5 (no failures) or 6 (with failures)
    sec = 7 if failures else 6
    has_comparisons = bool(data.get("prediction_vs_actual"))
    has_experience_val = bool(data.get("experience_comparison"))

    # Deployment
    deploy = data.get("deployment")
    if deploy:
        lines.append("---")
        lines.append(f"## {sec}. Deployment")
        sec += 1
        lines.append("")
        lines.append(f"**Endpoint:** `{deploy.get('endpoint_url', 'N/A')}`")
        lines.append(f"**Model Format:** {deploy.get('model_format', 'N/A')}")
        lat = deploy.get("p95_latency_ms")
        if lat is not None:
            lines.append(f"**P95 Latency:** {lat} ms")
        val_metric = deploy.get("val_metric")
        if val_metric is not None:
            lines.append(f"**Validation Metric:** {val_metric}")
        lines.append("")

        # Prediction vs Actual
        if has_comparisons:
            comps = data.get("prediction_vs_actual", [])
            lines.append("---")
            lines.append(f"## {sec}. Prediction vs Actual")
            sec += 1
            lines.append("")
            lines.append("| Estimate | Predicted | Actual | Error |")
            lines.append("|----------|-----------|--------|-------|")
            for c in comps:
                p = c.get("predicted", "")
                a = c.get("actual", "")
                err = f"{c.get('error_pct', '')}%" if "error_pct" in c else c.get("calibration", "")
                lines.append(f"| {c.get('estimate', '')} | {p} | {a} | {err} |")
        lines.append("")

    # Experience Comparison (Stage 3+4)
    exp = data.get("experience_comparison", {})
    if exp:
        lines.append("---")
        lines.append(f"## {sec}. Experience Comparison")
        sec += 1
        lines.append("")
        if exp.get("total_similar", 0) > 0:
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            lines.append(f"| Similar past jobs | {exp.get('total_similar', 0)} |")
            if exp.get("completed", 0) > 0:
                lines.append(f"| Completed | {exp['completed']} |")
                lines.append(f"| Avg achieved metric | {exp.get('avg_metric', 'N/A')} |")
                lines.append(f"| Best metric | {exp.get('best_metric', 'N/A')} |")
                lines.append(f"| Avg crashes per job | {exp.get('avg_crashes', 0):.1f} |")
                lines.append(f"| Historical pass ratio | {exp.get('pass_ratio', 0):.0%} |")
                lines.append(
                    f"| Most common architecture | {exp.get('most_common_architecture', 'N/A')} |"
                )
            lines.append("")
        else:
            lines.append("No similar past jobs found in experience memory.")
            lines.append("")

    # Lessons Learned
    lessons = data.get("lessons_learned", [])
    if lessons:
        lines.append("---")
        lines.append(f"## {sec}. Lessons Learned")
        lines.append("")
        for l in lessons:
            lines.append(f"- {l}")
        lines.append("")

    lines.append("---")
    lines.append(f"*Report generated by Prometheus Swarm — {created}*")
    lines.append("")

    return "\n".join(lines)

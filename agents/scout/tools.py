"""
Scout tools. Each function is independently unit-testable.
All functions are pure ? no side effects except Redis writes (marked explicitly).
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _infer_modality_from_content(file_path: str) -> str:
    try:
        df = pd.read_csv(file_path, nrows=100)
    except Exception:
        return "tabular"

    for col in df.columns:
        lower = col.lower()
        if any(kw in lower for kw in ("path", "file", "image")):
            return "image"

    for col in df.select_dtypes(include="object").columns:
        avg_len = df[col].dropna().astype(str).str.len().mean()
        if avg_len > 50:
            return "text"

    return "tabular"


def detect_modality(file_path: str, modality_override: str | None = None) -> str:
    if modality_override is not None:
        return modality_override
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in {".parquet", ".tsv", ".xlsx", ".xls"}:
        return "tabular"
    elif ext in {".txt", ".jsonl", ".json"}:
        return "text"
    elif ext in {".jpg", ".jpeg", ".png", ".zip"}:
        return "image"
    elif ext == ".csv":
        return _infer_modality_from_content(file_path)
    else:
        try:
            pd.read_csv(file_path, nrows=5)
            return "tabular"
        except Exception:
            return "tabular"


def _detect_outliers(series: pd.Series) -> int:
    try:
        q1, q3 = series.quantile(0.25), series.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return int(series.between(lower, upper, inclusive="both").sum())
    except Exception:
        return 0


def _detect_delimiter(file_path: str) -> str:
    """Detect CSV delimiter by inspecting the first 2 lines of the file.

    Tries common delimiters: comma, semicolon, tab, pipe.
    Falls back to comma if detection is ambiguous.
    """
    delimiters = [",", ";", "\t", "|"]
    try:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            first_lines = [f.readline() for _ in range(2)]
    except Exception:
        return ","

    best_delim = ","
    best_count = 0
    for delim in delimiters:
        count = sum(line.count(delim) for line in first_lines if line)
        if count > best_count:
            best_count = count
            best_delim = delim
    return best_delim


def run_eda(file_path: str, target_column: str | None = None) -> dict[str, Any]:
    delimiter = _detect_delimiter(file_path)
    try:
        df = pd.read_csv(file_path, sep=delimiter)
    except Exception as e:
        return {"error": str(e), "delimiter": delimiter}

    num_rows, num_cols = df.shape
    warnings = []

    column_types = {}
    numeric_cols_list = []
    categorical_cols_list = []
    text_cols_list = []
    for col in df.columns:
        if col == target_column:
            column_types[col] = "target"
        elif pd.api.types.is_numeric_dtype(df[col]):
            column_types[col] = "numeric"
            numeric_cols_list.append(col)
        elif df[col].dtype == object:
            avg_len = df[col].dropna().astype(str).str.len().mean()
            if avg_len > 50:
                column_types[col] = "text"
                text_cols_list.append(col)
            else:
                column_types[col] = "categorical"
                categorical_cols_list.append(col)
        else:
            column_types[col] = "categorical"
            categorical_cols_list.append(col)

    missing_rate = {col: float(df[col].isna().mean()) for col in df.columns}
    high_missing = [col for col, rate in missing_rate.items() if rate > 0.3]
    if high_missing:
        warnings.append(f"High missing rate (>30%) in columns: {high_missing}")

    high_cardinality = [c for c in categorical_cols_list if df[c].nunique() > 50]
    if high_cardinality:
        warnings.append(f"High cardinality (>50 unique values) in: {high_cardinality}")

    imbalance_ratio = None
    if target_column and target_column in df.columns:
        counts = df[target_column].value_counts()
        if len(counts) == 2:
            minority = counts.min()
            majority = counts.max()
            imbalance_ratio = float(majority / minority)
            if imbalance_ratio > 5:
                warnings.append(f"Class imbalance: majority/minority ratio = {imbalance_ratio:.1f}")

    # ── Outlier detection (IQR method on numeric columns) ───────────────
    outlier_counts = {}
    for col in numeric_cols_list:
        if df[col].nunique() > 2 and missing_rate.get(col, 0) < 0.5:
            inliers = _detect_outliers(df[col].dropna())
            total_non_null = int(df[col].notna().sum())
            outlier_counts[col] = total_non_null - inliers

    num_outlier_cols = sum(1 for v in outlier_counts.values() if v > 0)
    total_outliers = sum(outlier_counts.values())
    if num_outlier_cols > 0:
        warnings.append(f"Outliers detected in {num_outlier_cols} columns ({total_outliers} total)")

    # ── Duplicate rows ──────────────────────────────────────────────────
    duplicate_rows = int(df.duplicated().sum())
    if duplicate_rows > 0:
        dup_pct = duplicate_rows / num_rows * 100
        warnings.append(f"{duplicate_rows} duplicate rows ({dup_pct:.1f}%)")

    # ── Column profiling stats ─────────────────────────────────────────
    numeric_stats = {}
    for col in numeric_cols_list:
        s = df[col].dropna()
        if len(s) > 0:
            numeric_stats[col] = {
                "mean": round(float(s.mean()), 4) if s.dtype.kind in ("i", "u", "f") else None,
                "std": round(float(s.std()), 4) if s.dtype.kind in ("i", "u", "f") else None,
                "min": float(s.min()) if s.dtype.kind in ("i", "u", "f") else None,
                "max": float(s.max()) if s.dtype.kind in ("i", "u", "f") else None,
                "p25": round(float(s.quantile(0.25)), 4),
                "p50": round(float(s.median()), 4),
                "p75": round(float(s.quantile(0.75)), 4),
                "zeros": int((s == 0).sum()),
                "unique": int(s.nunique()),
            }

    categorical_stats = {}
    for col in categorical_cols_list:
        s = df[col].dropna()
        if len(s) > 0:
            top_val = s.value_counts().index[0] if len(s) > 0 else None
            categorical_stats[col] = {
                "unique": int(s.nunique()),
                "top": str(top_val) if top_val is not None else None,
                "top_freq": int(s.value_counts().iloc[0]) if len(s) > 0 else 0,
                "top_freq_pct": (
                    round(float(s.value_counts().iloc[0] / len(s) * 100), 1) if len(s) > 0 else 0
                ),
            }

    # ── Correlation matrix (numeric vs target) ─────────────────────────
    correlation_with_target = {}
    if target_column and target_column in df.columns:
        target = df[target_column].dropna()
        if target.dtype.kind in ("i", "u", "f"):
            # Detect and skip constant columns (zero variance) to prevent
            # RuntimeWarning: invalid value encountered in divide
            removed_constant_cols = []
            for col in numeric_cols_list:
                if col != target_column:
                    col_std = df[col].std()
                    if col_std == 0 or pd.isna(col_std):
                        removed_constant_cols.append(col)
            if removed_constant_cols:
                logger.info(
                    "Correlation preprocessing: removed_constant_columns=%d " "columns=%s",
                    len(removed_constant_cols),
                    removed_constant_cols,
                )
            for col in numeric_cols_list:
                if col != target_column and col not in removed_constant_cols:
                    try:
                        corr = df[col].corr(target)
                        correlation_with_target[col] = round(float(corr), 4)
                    except Exception:
                        pass

    # ── Memory estimate ─────────────────────────────────────────────────
    memory_bytes = df.memory_usage(deep=True).sum()

    return {
        "num_rows": num_rows,
        "num_columns": num_cols,
        "delimiter": delimiter,
        "column_types": column_types,
        "missing_value_rate": missing_rate,
        "high_cardinality_columns": high_cardinality,
        "class_imbalance_ratio": imbalance_ratio,
        "data_warnings": warnings,
        "outlier_counts": outlier_counts,
        "duplicate_rows": duplicate_rows,
        "numeric_stats": numeric_stats,
        "categorical_stats": categorical_stats,
        "correlation_with_target": correlation_with_target,
        "memory_usage_bytes": int(memory_bytes),
        "numeric_columns": numeric_cols_list,
        "categorical_columns": categorical_cols_list,
        "text_columns": text_cols_list,
    }


def infer_task_type(
    target_column: str | None,
    column_types: dict[str, str],
    file_path: str,
) -> str:
    if target_column is None:
        return "classification"

    try:
        df = pd.read_csv(file_path)
        if target_column not in df.columns:
            return "classification"
        target = df[target_column].dropna()
        n_unique = target.nunique()
        if pd.api.types.is_numeric_dtype(target) and n_unique > 20:
            return "regression"
        return "classification"
    except Exception:
        return "classification"


def select_evaluation_metric(task_type: str, imbalance_ratio: float | None) -> str:
    if task_type == "regression":
        return "rmse"
    elif task_type == "classification" and imbalance_ratio and imbalance_ratio > 3:
        return "f1"
    else:
        return "auc_roc"


def suggest_imbalance_strategy(imbalance_ratio: float | None) -> str:
    if imbalance_ratio is None:
        return "none"
    elif imbalance_ratio > 20:
        return "smote"
    elif imbalance_ratio > 5:
        return "class_weight"
    elif imbalance_ratio > 3:
        return "focal_loss"
    return "none"


def select_architecture_family(modality: str, task_type: str, num_rows: int) -> str:
    if modality == "tabular":
        return "tabnet" if num_rows >= 1_000_000 else "lightgbm"
    elif modality == "text":
        return "distilbert"
    elif modality == "image":
        return "efficientnet"
    return "lightgbm"


def write_mission_brief(
    eda_results: dict[str, Any],
    job_id: str,
    problem_description: str,
    file_path: str,
    target_column: str | None = None,
    constraints: dict | None = None,
    modality_override: str | None = None,
    engineering_reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_type = infer_task_type(target_column, eda_results.get("column_types", {}), file_path)
    metric = select_evaluation_metric(task_type, eda_results.get("class_imbalance_ratio"))
    modality = detect_modality(file_path, modality_override=modality_override)
    imbalance_strategy = suggest_imbalance_strategy(eda_results.get("class_imbalance_ratio"))

    brief = {
        "schema_version": "1.0",
        "job_id": job_id,
        "problem_description": problem_description,
        "task_type": task_type,
        "modality": modality,
        "target_column": target_column,
        "evaluation_metric": metric,
        "constraints": constraints or {"max_latency_ms": None, "max_model_size_mb": None},
        "dataset": {
            "file_path": file_path,
            "num_rows": eda_results.get("num_rows", 0),
            "num_columns": eda_results.get("num_columns", 0),
            "delimiter": eda_results.get("delimiter", ","),
            "column_types": eda_results.get("column_types", {}),
        },
        "data_quality": {
            "class_imbalance_ratio": eda_results.get("class_imbalance_ratio"),
            "missing_value_rate": eda_results.get("missing_value_rate", {}),
            "high_cardinality_columns": eda_results.get("high_cardinality_columns", []),
            "data_warnings": eda_results.get("data_warnings", []),
        },
        "imbalance_strategy": imbalance_strategy,
        "recommended_architecture_family": select_architecture_family(
            modality, task_type, eda_results.get("num_rows", 0)
        ),
        "engineering_reasoning": engineering_reasoning or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return brief


def _compute_expected_metric_range(
    task_type: str,
    modality: str,
    num_rows: int,
    class_imbalance_ratio: float | None,
) -> dict[str, Any]:
    """Compute realistic expected metric range from dataset properties.

    Aligns with Arbiter's threshold computation in agents/arbiter/tools.py:
      - Classification: threshold_auc = max(0.55, 0.80 - 0.03 * min(ratio, 10))
      - Regression: threshold_rmse = std(y_target) * 0.85

    Returns dict with min_acceptable, stretch_target, baseline for classification
    or min_acceptable_improvement ratio for regression.
    """
    if task_type == "classification":
        if class_imbalance_ratio and class_imbalance_ratio > 0:
            baseline = class_imbalance_ratio / (1 + class_imbalance_ratio)
        else:
            baseline = 0.5

        threshold = max(0.55, 0.80 - 0.03 * min(class_imbalance_ratio or 0, 10.0))
        min_acceptable = round(threshold, 3)
        stretch_target = round(min(0.99, min_acceptable + 0.12), 3)

        if num_rows < 500:
            stretch_target = min(stretch_target, 0.85)
        if num_rows < 200:
            stretch_target = min(stretch_target, 0.78)
        if modality == "text":
            stretch_target = max(stretch_target, 0.82)

        return {
            "primary_metric": "auc_roc",
            "min_acceptable": min_acceptable,
            "stretch_target": stretch_target,
            "baseline": round(baseline, 3),
            "threshold_formula": "max(0.55, 0.80 - 0.03 * min(imbalance_ratio, 10))",
        }
    else:
        return {
            "primary_metric": "rmse",
            "min_acceptable_improvement": 0.85,
            "stretch_improvement": 0.50,
            "baseline_std_ratio": 1.0,
            "threshold_formula": "std(y_true) * 0.85",
        }


def _build_engineering_decisions(reasoning: dict[str, Any]) -> dict[str, Any]:
    """Build structured engineering decisions map — preserves machine keys for backward compat.

    Returns a dict keyed by decision topic (architecture, preprocessing, etc.)
    preserving the same interface that Forge and Arbiter consume downstream:
      reasoning.update(spec["engineering_decisions"])
      reasoning.get("architecture") -> {"selected": "lightgbm", "rationale": "...", ...}

    Also enriches each decision with the human-readable decision and rationale
    in a consistent format.

    Keys produced: architecture, data_quality, leakage, preprocessing, imbalance,
    feature_engineering, outliers, validation, problem_type (when available).
    """
    decisions = {}
    decision_keys = [
        "problem_type",
        "data_quality",
        "leakage",
        "preprocessing",
        "feature_engineering",
        "outliers",
        "architecture",
        "validation",
    ]

    for key in decision_keys:
        dec = reasoning.get(key, {})
        if isinstance(dec, dict) and "selected" in dec:
            entry = {
                "selected": dec["selected"],
                "rationale": dec.get("rationale", ""),
                "confidence": dec.get("confidence", 0.0),
            }
            if "title" in dec:
                entry["title"] = dec["title"]
            if "alternatives" in dec:
                entry["alternatives"] = dec["alternatives"]
            if "expected_metric_range" in dec:
                entry["expected_metric_range"] = dec["expected_metric_range"]
            decisions[key] = entry

    imbalance = reasoning.get("imbalance")
    if isinstance(imbalance, dict):
        entry = {
            "selected": imbalance.get("selected", "none"),
            "rationale": imbalance.get("rationale", "Not needed"),
            "confidence": imbalance.get("confidence", 1.0),
        }
        if "title" in imbalance:
            entry["title"] = imbalance["title"]
        if "alternatives" in imbalance:
            entry["alternatives"] = imbalance["alternatives"]
        decisions["imbalance"] = entry
    else:
        decisions["imbalance"] = {
            "selected": "none",
            "rationale": "Not needed",
            "confidence": 1.0,
        }

    return decisions


def write_mission_spec(
    eda_results: dict[str, Any],
    job_id: str,
    problem_description: str,
    file_path: str,
    target_column: str | None = None,
    constraints: dict | None = None,
    modality_override: str | None = None,
    engineering_reasoning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a rich MissionSpecification — the authoritative mission analysis.

    Builds on the same data as write_mission_brief but organises it into
    a structured specification with dataset profiling, data quality, risks,
    candidate models, validation strategy, engineering decisions, confidence,
    and success criteria. All existing mission_brief fields remain accessible
    for backward compatibility.

    This is the primary contract between Scout and all downstream agents.
    The spec is stored at job:{job_id}:mission_spec and broadcast via
    the mission_spec_redis_key field in the MISSION_BRIEF_READY event.

    Returns a dict (JSON-serialisable) that is the MissionSpecification.
    """
    reasoning = engineering_reasoning or {}
    task_type = infer_task_type(target_column, eda_results.get("column_types", {}), file_path)
    metric = select_evaluation_metric(task_type, eda_results.get("class_imbalance_ratio"))
    modality = detect_modality(file_path, modality_override=modality_override)

    arch_decision = reasoning.get("architecture", {})
    primary_arch = arch_decision.get(
        "selected", select_architecture_family(modality, task_type, eda_results.get("num_rows", 0))
    )
    arch_alternatives = arch_decision.get("alternatives", [])
    arch_confidence = arch_decision.get("confidence", 0.85)

    overall_confidence = reasoning.get("overall_confidence", 0.85)

    spec = {
        "spec_version": "2.0",
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "objective": {
            "problem_description": problem_description,
            "task_type": task_type,
            "modality": modality,
            "target_column": target_column,
            "evaluation_metric": metric,
            "constraints": constraints or {"max_latency_ms": None, "max_model_size_mb": None},
        },
        "dataset_analysis": {
            "file_path": file_path,
            "num_rows": eda_results.get("num_rows", 0),
            "num_columns": eda_results.get("num_columns", 0),
            "column_types": eda_results.get("column_types", {}),
            "numeric_columns": eda_results.get("numeric_columns", []),
            "categorical_columns": eda_results.get("categorical_columns", []),
            "text_columns": eda_results.get("text_columns", []),
            "duplicate_rows": eda_results.get("duplicate_rows", 0),
            "memory_usage_bytes": eda_results.get("memory_usage_bytes", 0),
            "numeric_stats": eda_results.get("numeric_stats", {}),
            "categorical_stats": eda_results.get("categorical_stats", {}),
            "correlation_with_target": eda_results.get("correlation_with_target", {}),
        },
        "data_quality": {
            "overall_rating": reasoning.get("data_quality", {}).get("selected", "unknown"),
            "missing_value_rate": eda_results.get("missing_value_rate", {}),
            "high_missing_columns": [
                c for c, r in eda_results.get("missing_value_rate", {}).items() if r > 0.3
            ],
            "high_cardinality_columns": eda_results.get("high_cardinality_columns", []),
            "class_imbalance_ratio": eda_results.get("class_imbalance_ratio"),
            "outlier_counts": eda_results.get("outlier_counts", {}),
            "duplicate_rows": eda_results.get("duplicate_rows", 0),
            "data_warnings": eda_results.get("data_warnings", []),
        },
        "leakage_analysis": {
            "status": reasoning.get("leakage", {}).get("selected", "no_analysis"),
            "details": reasoning.get("leakage", {}).get("rationale", ""),
            "sources": [],
        },
        "risks": reasoning.get("risks", []),
        "recommended_pipeline": {
            "preprocessing": reasoning.get("preprocessing", {}).get("selected", "passthrough"),
            "preprocessing_rationale": reasoning.get("preprocessing", {}).get("rationale", ""),
            "imbalance_strategy": (
                reasoning.get("imbalance", {}).get("selected", "none")
                if reasoning.get("imbalance")
                else "none"
            ),
            "imbalance_rationale": (
                reasoning.get("imbalance", {}).get("rationale", "")
                if reasoning.get("imbalance")
                else ""
            ),
            "validation_strategy": reasoning.get("validation", {}).get(
                "selected", "train_val_split"
            ),
            "validation_rationale": reasoning.get("validation", {}).get("rationale", ""),
        },
        "candidate_models": {
            "primary": {
                "name": primary_arch,
                "confidence": arch_confidence,
                "rationale": arch_decision.get("rationale", ""),
            },
            "alternatives": [{"name": a} for a in arch_alternatives if a != primary_arch],
        },
        "engineering_decisions": _build_engineering_decisions(reasoning),
        "feature_engineering": reasoning.get("feature_engineering", {}),
        "outlier_strategy": reasoning.get("outliers", {}).get("selected", "none"),
        "confidence": {
            "overall": overall_confidence,
            "per_decision": {
                k: v.get("confidence", 0.0)
                for k, v in reasoning.items()
                if isinstance(v, dict) and "confidence" in v
            },
        },
        "success_criteria": {
            "primary_metric": metric,
            "expected_metric_range": reasoning.get("architecture", {}).get(
                "expected_metric_range",
                _compute_expected_metric_range(
                    task_type,
                    modality,
                    eda_results.get("num_rows", 0),
                    eda_results.get("class_imbalance_ratio"),
                ),
            ),
        },
    }

    return spec

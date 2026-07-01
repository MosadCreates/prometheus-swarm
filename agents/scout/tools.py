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


def detect_modality(file_path: str, modality_override: str | None = None) -> str:
    if modality_override is not None:
        return modality_override
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in {".csv", ".parquet", ".tsv", ".xlsx"}:
        return "tabular"
    elif ext in {".txt", ".jsonl", ".json"}:
        return "text"
    elif ext in {".jpg", ".jpeg", ".png", ".zip"}:
        return "image"
    else:
        try:
            pd.read_csv(file_path, nrows=5)
            return "tabular"
        except Exception:
            return "tabular"


def run_eda(file_path: str, target_column: str | None = None) -> dict[str, Any]:
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        return {"error": str(e)}

    num_rows, num_cols = df.shape
    warnings = []

    column_types = {}
    for col in df.columns:
        if col == target_column:
            column_types[col] = "target"
        elif pd.api.types.is_numeric_dtype(df[col]):
            column_types[col] = "numeric"
        elif df[col].dtype == object:
            avg_len = df[col].dropna().astype(str).str.len().mean()
            column_types[col] = "text" if avg_len > 50 else "categorical"
        else:
            column_types[col] = "categorical"

    missing_rate = {col: float(df[col].isna().mean()) for col in df.columns}
    high_missing = [col for col, rate in missing_rate.items() if rate > 0.3]
    if high_missing:
        warnings.append(f"High missing rate (>30%) in columns: {high_missing}")

    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]
    high_cardinality = [c for c in categorical_cols if df[c].nunique() > 50]
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

    return {
        "num_rows": num_rows,
        "num_columns": num_cols,
        "column_types": column_types,
        "missing_value_rate": missing_rate,
        "high_cardinality_columns": high_cardinality,
        "class_imbalance_ratio": imbalance_ratio,
        "data_warnings": warnings,
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
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return brief

from __future__ import annotations

import os

from prometheus.mission.models import (
    KNOWN_METRICS,
    ParsedMission,
    ValidationResult,
)


def validate(parsed: ParsedMission) -> ValidationResult:
    """Deterministic validation of a parsed mission.

    Checks:
      - Dataset exists and is readable
      - Dataset is a CSV file
      - Target column is not empty
      - Deployment threshold is between 0 and 1 if set
      - Evaluation metric is known
      - Task type is known

    Returns ValidationResult with errors and warnings.
    Never calls the LLM.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Dataset checks
    ds_path = parsed.dataset_path.strip()
    if not ds_path:
        errors.append("No dataset path specified.")
    else:
        resolved = _resolve_dataset(ds_path)
        if resolved is None:
            errors.append(f"Dataset not found: {ds_path}")
        elif not resolved.endswith(".csv"):
            warnings.append(f"Dataset is not a CSV file: {ds_path}")
        else:
            try:
                with open(resolved, "rb") as _f:
                    _f.read(1)
            except (OSError, PermissionError) as e:
                errors.append(f"Dataset cannot be read: {e}")

    # Target column
    if not parsed.target_column.strip():
        errors.append("No target column specified.")

    # Deployment threshold
    if parsed.deployment_threshold is not None:
        t = parsed.deployment_threshold
        if t < 0 or t > 1:
            errors.append(f"Deployment threshold must be between 0 and 1, got {t}")

    # Evaluation metric
    metric = parsed.evaluation_metric.strip().lower()
    if metric and metric not in KNOWN_METRICS and metric not in _ALIAS_LOOKUP:
        warnings.append(f"Unknown evaluation metric: {parsed.evaluation_metric}")

    # Task type
    task = parsed.task_type.strip().lower()
    known_tasks = {
        "classification",
        "regression",
        "clustering",
        "object_detection",
        "segmentation",
        "text_generation",
        "forecasting",
    }
    if task and task not in known_tasks:
        warnings.append(f"Unknown task type: {parsed.task_type}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings + parsed.warnings,
    )


_ALIAS_LOOKUP = {
    "roc auc",
    "roc_auc",
    "f1 score",
    "f1-score",
    "r2 score",
    "r2-score",
    "r-squared",
}


def _resolve_dataset(path: str) -> str | None:
    """Resolve a dataset path against common locations."""
    if os.path.exists(path):
        return os.path.abspath(path)
    base = os.path.basename(path)
    for prefix in [".", "./data", "./datasets", "./dataset"]:
        candidate = os.path.join(prefix, base)
        if os.path.exists(candidate):
            return os.path.abspath(candidate)
    return None

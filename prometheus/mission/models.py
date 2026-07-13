from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedMission:
    original_prompt: str
    problem_summary: str
    dataset_path: str
    target_column: str
    task_type: str
    evaluation_metric: str
    deployment_threshold: float | None = None
    deployment_operator: str = ">"
    constraints: list[str] = field(default_factory=list)
    dataset_exists: bool = False
    warnings: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


KNOWN_METRICS = {
    "accuracy",
    "f1",
    "precision",
    "recall",
    "roc auc",
    "auc",
    "auc_roc",
    "rmse",
    "mae",
    "mse",
    "r2",
}

TASK_TYPE_ALIASES: dict[str, str] = {
    "binary classification": "classification",
    "multiclass classification": "classification",
    "multi-label classification": "classification",
    "binary_classification": "classification",
    "multiclass": "classification",
    "regression": "regression",
    "clustering": "clustering",
    "object detection": "object_detection",
    "obj detection": "object_detection",
    "segmentation": "segmentation",
    "image segmentation": "segmentation",
    "text generation": "text_generation",
    "generation": "text_generation",
    "forecasting": "forecasting",
    "time series": "forecasting",
    "time-series": "forecasting",
}

METRIC_ALIASES: dict[str, str] = {
    "roc auc": "auc_roc",
    "roc_auc": "auc_roc",
    "auc": "auc_roc",
    "f1 score": "f1",
    "f1-score": "f1",
    "r2 score": "r2",
    "r2-score": "r2",
    "r-squared": "r2",
}

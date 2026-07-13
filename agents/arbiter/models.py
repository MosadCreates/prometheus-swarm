from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MissionConstraints:
    metric: str
    threshold: float | None = None
    operator: str = ">"
    constraints_list: list[str] = field(default_factory=list)

    @property
    def has_threshold(self) -> bool:
        return self.threshold is not None

    def passes(self, value: float) -> bool:
        if self.threshold is None:
            return True
        if self.operator == ">":
            return value > self.threshold
        elif self.operator == ">=":
            return value >= self.threshold
        elif self.operator == "<":
            return value < self.threshold
        elif self.operator == "<=":
            return value <= self.threshold
        return value > self.threshold

    def within_retry_window(self, value: float) -> bool:
        if self.threshold is None:
            return False
        gap = abs(value - self.threshold) / max(abs(self.threshold), 0.001)
        return gap <= 0.15


@dataclass
class EvaluationResult:
    metric: str
    metric_value: float
    all_metrics: dict[str, float] = field(default_factory=dict)
    task_type: str = "classification"
    checkpoint_path: str = ""
    num_samples: int = 0

    @classmethod
    def from_metrics_dict(
        cls,
        metrics: dict[str, float],
        task_type: str = "classification",
        checkpoint_path: str = "",
        num_samples: int = 0,
    ) -> EvaluationResult:
        primary = metrics.get("auc_roc") or metrics.get("rmse") or 0.0
        metric_name = "auc_roc" if "auc_roc" in metrics else "rmse"
        return cls(
            metric=metric_name,
            metric_value=primary,
            all_metrics=metrics,
            task_type=task_type,
            checkpoint_path=checkpoint_path,
            num_samples=num_samples,
        )


@dataclass
class DecisionResult:
    decision: str
    explanation: str
    metric_value: float = 0.0
    threshold: float | None = None


@dataclass
class EvaluationReport:
    job_id: str
    metric: str
    metric_value: float
    threshold: float | None
    decision: str
    checkpoint_path: str
    explanation: str
    all_metrics: dict[str, float] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "metric": self.metric,
            "metric_value": self.metric_value,
            "threshold": self.threshold,
            "decision": self.decision,
            "checkpoint_path": self.checkpoint_path,
            "explanation": self.explanation,
            "all_metrics": self.all_metrics,
            "created_at": self.created_at,
        }

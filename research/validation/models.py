"""Research Validation Framework — experiment models, metrics, statistics, and reporting."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ResearchHypothesis(str, Enum):
    H1 = "H1"
    H2 = "H2"
    H3 = "H3"


class ResearchQuestion(str, Enum):
    RQ1 = "RQ1"
    RQ2 = "RQ2"
    RQ3 = "RQ3"
    RQ4 = "RQ4"
    RQ5 = "RQ5"


class FailureCategory(str, Enum):
    PLANNER = "planner_failure"
    TRAINING = "training_failure"
    INFRASTRUCTURE = "infrastructure_failure"
    DATASET = "dataset_issue"
    RESOURCE = "resource_exhaustion"
    CONVERGENCE = "model_convergence"
    DEPLOYMENT = "deployment_failure"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Metric models
# ---------------------------------------------------------------------------


class SystemMetrics(BaseModel):
    duration_seconds: float = 0
    retries: int = 0
    crashes: int = 0
    crashes_recovered: int = 0
    peak_ram_mb: float | None = None
    peak_gpu_mb: float | None = None
    wall_clock_time_s: float = 0
    orchestration_overhead_s: float = 0


class ResearchMetrics(BaseModel):
    prediction_error_duration_pct: float | None = None
    prediction_error_ram_pct: float | None = None
    prediction_bias_duration_pct: float | None = None
    prediction_bias_ram_pct: float | None = None
    deployment_success: bool | None = None
    planner_confidence_score: float | None = None
    actual_success: bool | None = None
    architecture_selection_gap: float | None = None
    patch_success_rate: float | None = None
    fallback_success_rate: float | None = None
    final_metric: float | None = None


# ---------------------------------------------------------------------------
# Planning models
# ---------------------------------------------------------------------------


class PlanningCalibration(BaseModel):
    predicted_duration_minutes: int | None = None
    actual_duration_minutes: float | None = None
    predicted_ram_mb: int | None = None
    actual_ram_mb: float | None = None
    planner_confidence: float | None = None
    actual_deployment_success: bool | None = None


class LearningCurvePoint(BaseModel):
    evidence_count: int
    prediction_error_pct: float
    metric: str = "duration"


class ArchitectureSelectionAccuracy(BaseModel):
    planner_chosen_architecture: str = ""
    historical_best_architecture: str = ""
    planner_achieved_metric: float | None = None
    historical_best_metric: float | None = None
    selection_gap: float | None = None


# ---------------------------------------------------------------------------
# Statistics models
# ---------------------------------------------------------------------------


class ComparisonResult(BaseModel):
    metric_name: str = ""
    mean_a: float | None = None
    mean_b: float | None = None
    median_a: float | None = None
    median_b: float | None = None
    p_value: float | None = None
    effect_size: float | None = None
    effect_size_name: str = ""
    ci_lower: float | None = None
    ci_upper: float | None = None
    test_used: str = ""
    n_a: int = 0
    n_b: int = 0
    significant: bool = False
    research_question: str = ""


# ---------------------------------------------------------------------------
# Experiment models
# ---------------------------------------------------------------------------


class ExperimentRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    job_id: str = ""
    problem_id: str = ""
    hypothesis: ResearchHypothesis = ResearchHypothesis.H1
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    system_metrics: SystemMetrics = Field(default_factory=SystemMetrics)
    research_metrics: ResearchMetrics = Field(default_factory=ResearchMetrics)
    calibration: PlanningCalibration | None = None
    learning_curve: list[LearningCurvePoint] = Field(default_factory=list)
    architecture_accuracy: ArchitectureSelectionAccuracy | None = None
    failure_category: FailureCategory | None = None
    execution_outcome: dict[str, Any] = Field(default_factory=dict)
    prediction_error: dict[str, Any] = Field(default_factory=dict)
    replicability: dict[str, Any] = Field(default_factory=dict)


class Experiment(BaseModel):
    experiment_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    hypothesis: ResearchHypothesis
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    runs: list[ExperimentRun] = Field(default_factory=list)
    summary: dict[str, Any] | None = None


class ExperimentSet(BaseModel):
    set_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    experiments: dict[str, Experiment] = Field(default_factory=dict)
    comparisons: dict[str, ComparisonResult] = Field(default_factory=dict)
    git_commit: str = ""
    git_branch: str = ""
    python_version: str = ""
    configuration_hash: str = ""
    mission_spec_version: str = ""
    execution_plan_version: str = ""
    planner_version: str = ""
    dataset_problems_hash: str = ""

    def get_hypothesis(self, h: ResearchHypothesis) -> Experiment | None:
        return self.experiments.get(h.value)

    @property
    def h1(self) -> Experiment | None:
        return self.get_hypothesis(ResearchHypothesis.H1)

    @property
    def h2(self) -> Experiment | None:
        return self.get_hypothesis(ResearchHypothesis.H2)

    @property
    def h3(self) -> Experiment | None:
        return self.get_hypothesis(ResearchHypothesis.H3)


# ---------------------------------------------------------------------------
# Failure report
# ---------------------------------------------------------------------------


class FailureReport(BaseModel):
    experiment_set_id: str = ""
    total_failed: int = 0
    categories: dict[str, int] = Field(default_factory=dict)
    category_percentages: dict[str, float] = Field(default_factory=dict)
    representative_examples: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Report output
# ---------------------------------------------------------------------------


class EvaluationReport(BaseModel):
    title: str = "Research Validation Report"
    experiment_set_id: str = ""
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    sections: dict[str, str] = Field(default_factory=dict)
    summary_path: str = ""
    figures: list[str] = Field(default_factory=list)

"""Pydantic models for all data structures that cross agent boundaries."""

from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class DatasetInfo(BaseModel):
    file_path: str
    num_rows: int
    num_columns: int
    column_types: dict[str, str]


class DataQuality(BaseModel):
    class_imbalance_ratio: float | None = None
    missing_value_rate: dict[str, float] = {}
    high_cardinality_columns: list[str] = []
    data_warnings: list[str] = []


class Constraints(BaseModel):
    max_latency_ms: int | None = None
    max_model_size_mb: int | None = None


class MissionBrief(BaseModel):
    schema_version: str = "1.0"
    job_id: str = Field(default_factory=new_id)
    problem_description: str
    task_type: str
    modality: str
    target_column: str | None = None
    evaluation_metric: str | None = None
    constraints: Constraints = Field(default_factory=Constraints)
    dataset: DatasetInfo
    data_quality: DataQuality = Field(default_factory=DataQuality)
    imbalance_strategy: str = "none"
    recommended_architecture_family: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PatchLogEntry(BaseModel):
    patch_id: str = Field(default_factory=new_id)
    job_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    exception_type: str
    exception_message: str
    error_taxonomy_category: str
    taxonomy_match_method: str
    repair_strategy_used: str
    retrieved_similar_patches: list[dict] = []
    diff_applied: str
    lines_changed: int
    sandbox_test_result: str
    patch_outcome: str
    confidence_score: float
    attempt_number: int
    resume_from_checkpoint: str | None = None


class EvalReport(BaseModel):
    job_id: str
    checkpoint_path: str
    task_type: str
    primary_metric: str
    primary_metric_value: float
    all_metrics: dict[str, float]
    failure_analysis: str
    decision: str
    decision_reason: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

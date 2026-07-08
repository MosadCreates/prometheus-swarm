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


class MissionSpecification(BaseModel):
    """Rich mission specification — the contract between Scout and all downstream agents.

    Replaces mission_brief as the primary artifact. All fields structured for
    direct consumption by Forge, Furnace, Arbiter, Harbor without additional parsing.
    Written by Scout → job:{job_id}:mission_spec, broadcast via mission_spec_redis_key.
    """

    spec_version: str = "2.0"
    job_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    objective: dict = Field(default_factory=dict)
    dataset_analysis: dict = Field(default_factory=dict)
    data_quality: dict = Field(default_factory=dict)
    leakage_analysis: dict = Field(default_factory=dict)
    risks: list = Field(default_factory=list)
    recommended_pipeline: dict = Field(default_factory=dict)
    candidate_models: dict = Field(default_factory=dict)
    engineering_decisions: dict = Field(default_factory=dict)
    feature_engineering: dict = Field(default_factory=dict)
    outlier_strategy: str = "none"
    confidence: dict = Field(default_factory=dict)
    success_criteria: dict = Field(default_factory=dict)


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


class ReproducibilityContext(BaseModel):
    """Full version/configuration snapshot for research reproducibility.

    Recorded at job submission so every benchmark result can be reproduced
    months later. Stored at job:{job_id}:reproducibility.
    """

    reproducibility_version: str = "1.0"
    job_id: str
    git_commit: str = ""
    git_branch: str = ""
    has_uncommitted_changes: bool = False
    configuration_hash: str = ""
    python_version: str = ""
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    mission_spec_version: str = ""
    execution_plan_version: str = ""
    planner_version: str = ""
    agent_versions: dict[str, str] = Field(default_factory=dict)
    dataset_fingerprint: dict = Field(default_factory=dict)
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


class ExperienceRecord(BaseModel):
    job_id: str
    modality: str
    task_type: str
    num_rows: int
    num_columns: int = 0
    architecture: str
    class_imbalance_ratio: float | None = None
    expected_metric_range: list[float] | None = None
    achieved_metric: float | None = None
    expected_training_minutes: int | None = None
    actual_training_minutes: float | None = None
    total_crashes: int = 0
    patch_success: bool = False
    outcome: str = ""

    # ── Stage 3 enrichment: dataset fingerprint ──────────────────────────
    dataset_fingerprint: dict = Field(
        default_factory=dict,
        description="Column names, types, missing rates, outlier counts, correlation with target",
    )
    # ── Stage 3 enrichment: engineering decisions ────────────────────────
    engineering_decisions: dict = Field(
        default_factory=dict,
        description="Key decisions from reasoning (preprocessing, imbalance, validation, leakage, etc.)",
    )
    # ── Stage 3 enrichment: pipeline and features ────────────────────────
    pipeline_steps: list[str] = Field(
        default_factory=list,
        description="Actual preprocessing pipeline steps applied",
    )
    feature_engineering: list[str] = Field(
        default_factory=list,
        description="Feature engineering steps applied",
    )
    # ── Stage 3 enrichment: patch / recovery summary ─────────────────────
    patch_summary: dict = Field(
        default_factory=dict,
        description="Patch attempts summary: total_attempts, categories, last_outcome",
    )
    # ── Stage 3 enrichment: cost and references ──────────────────────────
    api_cost_usd: float = 0.0
    mission_spec_key: str = ""
    engineering_plan_key: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ExecutionOutcome(BaseModel):
    """What actually happened during execution — separate from engineering decisions.

    Used by the Adaptive Planning Engine to compute prediction error
    and produce PlanningHints for future jobs. Stored in Redis for fast
    access and synced to ChromaDB for historical analysis.
    """

    job_id: str
    architecture: str
    modality: str
    task_type: str
    num_rows: int = 0
    num_columns: int = 0
    duration_seconds: float
    retries: int = 0
    crashes: int = 0
    crashes_recovered: int = 0
    peak_ram_mb: float | None = None
    peak_gpu_mb: float | None = None
    deployment_success: bool | None = None
    final_metric: float | None = None
    outcome_label: str = "unknown"  # "pass", "retry", "escalate"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

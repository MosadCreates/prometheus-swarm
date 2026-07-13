"""Pydantic models for memory storage (ChromaDB + Redis persistence).

Note: Cross-agent contracts live in contracts/domain.py.
This file contains storage-specific models (ExperienceRecord, ExecutionOutcome, etc.)
that are NOT used as inter-agent communication contracts.
"""

from datetime import datetime, timezone
from pydantic import BaseModel, Field
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


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

"""Pydantic models for the Planner component.

ExecutionPlan is the single artifact produced by the Planner.
It describes how to execute a job — not what to build.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pydantic import BaseModel, Field

import uuid


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# DAG Node — generic building block for any execution graph
# ---------------------------------------------------------------------------


class DAGNode(BaseModel):
    """A single node in the execution DAG.

    This replaces hardcoded stage names like "develop" / "train".
    Any pipeline topology (RAG, speech, RL, graph ML) fits this model.
    """

    id: str
    agent: str
    label: str
    depends_on: list[str] = []
    condition: str | None = None
    timeout_seconds: int | None = None
    max_retries: int = 3
    metadata: dict = Field(default_factory=dict)


class DependencyEdge(BaseModel):
    from_node: str
    to_node: str
    condition: str | None = None


# ---------------------------------------------------------------------------
# Resource Budget — split into requirements vs estimates
# ---------------------------------------------------------------------------


class ResourceRequirements(BaseModel):
    """Hard requirements that must be satisfied before execution."""

    gpu_required: bool = False
    cuda_version: str | None = None
    min_ram_mb: int = 512
    min_disk_mb: int = 100
    min_vram_mb: int = 0


class ResourceEstimates(BaseModel):
    """Predicted resource usage (may differ from requirements)."""

    estimated_duration_minutes: int = 1
    estimated_ram_mb: int = 512
    estimated_disk_mb: int = 100
    estimated_vram_mb: int = 0


class ResourceBudget(BaseModel):
    requirements: ResourceRequirements = Field(default_factory=ResourceRequirements)
    estimates: ResourceEstimates = Field(default_factory=ResourceEstimates)
    cost_optimization_hint: str = "cpu_preferred"


# ---------------------------------------------------------------------------
# Retry Policy
# ---------------------------------------------------------------------------


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    fallback_models: list[str] = Field(default_factory=list)
    fallback_strategies: list[str] = Field(
        default_factory=lambda: [
            "reduce_epochs",
            "reduce_batch_size",
            "switch_optimizer",
            "switch_architecture",
        ]
    )
    escalation: str = "ESCALATE after 3 failures"


# ---------------------------------------------------------------------------
# Execution Confidence
# ---------------------------------------------------------------------------


class ExecutionConfidence(BaseModel):
    """How likely is this plan to succeed?

    Derived deterministically from dataset size, modality, architecture
    maturity, GPU availability, historical success rate, memory availability.
    Not an LLM confidence — an execution confidence.
    """

    score: float = Field(default=0.5, ge=0.0, le=1.0)
    factors: dict[str, float] = Field(default_factory=dict)
    assessment: str = "unknown"


# ---------------------------------------------------------------------------
# ExecutionPlan — the single artifact
# ---------------------------------------------------------------------------


class ExecutionPlan(BaseModel):
    """The Planner's sole output.

    MissionSpecification describes what success looks like.
    ExecutionPlan describes how to achieve it.
    """

    planner_version: str = "0.1.0"
    execution_plan_version: str = "1.0"

    plan_id: str = Field(default_factory=new_id)
    job_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    nodes: dict[str, DAGNode] = Field(default_factory=dict)
    edges: list[DependencyEdge] = Field(default_factory=list)

    resource_budget: ResourceBudget = Field(default_factory=ResourceBudget)

    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)

    confidence: ExecutionConfidence = Field(default_factory=lambda: ExecutionConfidence())

    critical_path: list[str] = Field(
        default_factory=list,
        description="Longest path through the DAG (node ids in order)",
    )
    estimated_total_minutes: int = 1

    artifacts: list[str] = Field(default_factory=list)
    critical_checkpoints: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# PlanningHints — lightweight data contract between learning system and Planner
# ---------------------------------------------------------------------------


class PlanningHints(BaseModel):
    """Historical evidence for adjusting execution estimates.

    Produced by the learning module from past ExecutionOutcomes.
    Planner consumes these to refine budget and retry policy.
    None fields mean 'not enough evidence' — Planner uses defaults.
    """

    version: str = "1.0"
    computed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    evidence_count: int = 0

    estimated_duration_minutes: int | None = None
    estimated_ram_mb: int | None = None
    estimated_vram_mb: int | None = None
    gpu_recommended: bool | None = None

    fallback_models: list[str] | None = None

    last_prediction_error_pct: float | None = None

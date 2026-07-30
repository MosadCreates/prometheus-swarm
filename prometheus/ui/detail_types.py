from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentState(str, Enum):
    """States that match the live tree renderer."""

    IDLE = "idle"
    THINKING = "thinking"
    PLANNING = "planning"
    ACTING = "acting"
    VERIFYING = "verifying"
    DONE = "done"
    ERROR = "error"
    RETRYING = "retrying"
    WAITING = "waiting"
    DISABLED = "disabled"


class DetailType(str, Enum):
    """Types of structured detail events."""

    SCOUT_DATASET = "scout_dataset"
    SCOUT_DATA_QUALITY = "scout_data_quality"
    SCOUT_TASK = "scout_task"
    SCOUT_METRIC = "scout_metric"
    SCOUT_MODALITY = "scout_modality"
    SCOUT_RECOMMENDATION = "scout_recommendation"
    SCOUT_CONFIDENCE = "scout_confidence"
    FORGE_ARCHITECTURE = "forge_architecture"
    FORGE_CANDIDATES = "forge_candidates"
    FORGE_RATIONALE = "forge_rationale"
    FORGE_SCRIPT = "forge_script"
    FORGE_SEARCH_SPACE = "forge_search_space"
    FORGE_VALIDATION = "forge_validation"
    FORGE_IMBALANCE = "forge_imbalance"
    FURNACE_EPOCH = "furnace_epoch"
    FURNACE_TRIAL = "furnace_trial"
    FURNACE_METRIC = "furnace_metric"
    FURNACE_TIME = "furnace_time"
    FURNACE_CONTAINER = "furnace_container"
    FURNACE_CHECKPOINT = "furnace_checkpoint"
    DISSECT_ERROR = "dissect_error"
    DISSECT_CASCADE = "dissect_cascade"
    DISSECT_PATCH = "dissect_patch"
    DISSECT_SANDBOX = "dissect_sandbox"
    DISSECT_OUTCOME = "dissect_outcome"
    ARBITER_METRICS = "arbiter_metrics"
    ARBITER_DECISION = "arbiter_decision"
    ARBITER_THRESHOLD = "arbiter_threshold"
    ARBITER_LEADERBOARD = "arbiter_leaderboard"
    ARBITER_REPORT = "arbiter_report"
    HARBOR_DEPLOY = "harbor_deploy"
    HARBOR_ENDPOINT = "harbor_endpoint"
    HARBOR_FORMAT = "harbor_format"
    HARBOR_HEALTH = "harbor_health"
    HARBOR_DRIFT = "harbor_drift"
    HARBOR_SELFTEST = "harbor_selftest"
    MISSION_START = "mission_start"
    MISSION_COMPLETE = "mission_complete"
    MISSION_ARTIFACT = "mission_artifact"
    PIPELINE_STATE = "pipeline_state"
    HEARTBEAT = "heartbeat"


class BaseDetail(BaseModel):
    """Base for all detail payloads."""

    model_config = ConfigDict(extra="allow")

    detail_type: DetailType
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    agent: str = ""


class PipelineStateDetail(BaseDetail):
    """Pipeline-level state transition."""

    detail_type: DetailType = DetailType.PIPELINE_STATE
    phase: str
    from_phase: str | None = None
    to_phase: str | None = None
    elapsed_seconds: float = 0.0
    active_agent: str | None = None


class ScoutDatasetDetail(BaseDetail):
    """Scout dataset inspection results."""

    detail_type: DetailType = DetailType.SCOUT_DATASET
    num_rows: int
    num_columns: int
    file_path: str
    delimiter: str = ","
    column_types: dict[str, str] = Field(default_factory=dict)
    memory_mb: float = 0.0


class ScoutDataQualityDetail(BaseDetail):
    """Scout data quality analysis."""

    detail_type: DetailType = DetailType.SCOUT_DATA_QUALITY
    missing_values: dict[str, float] = Field(default_factory=dict)
    high_cardinality: list[str] = Field(default_factory=list)
    class_imbalance_ratio: float | None = None
    outlier_counts: dict[str, int] = Field(default_factory=dict)
    duplicate_rows: int = 0
    warnings: list[str] = Field(default_factory=list)


class ScoutTaskDetail(BaseDetail):
    """Scout task type inference."""

    detail_type: DetailType = DetailType.SCOUT_TASK
    task_type: str
    confidence: float
    rationale: str
    alternatives: list[str] = Field(default_factory=list)


class ScoutMetricDetail(BaseDetail):
    """Scout evaluation metric selection."""

    detail_type: DetailType = DetailType.SCOUT_METRIC
    metric: str
    reason: str


class ScoutModalityDetail(BaseDetail):
    """Scout modality detection."""

    detail_type: DetailType = DetailType.SCOUT_MODALITY
    modality: str
    confidence: float


class ScoutRecommendationDetail(BaseDetail):
    """Scout architecture recommendation."""

    detail_type: DetailType = DetailType.SCOUT_RECOMMENDATION
    architecture: str
    confidence: float
    rationale: str
    alternatives: list[str] = Field(default_factory=list)


class ScoutConfidenceDetail(BaseDetail):
    """Scout overall confidence."""

    detail_type: DetailType = DetailType.SCOUT_CONFIDENCE
    overall: float
    per_decision: dict[str, float] = Field(default_factory=dict)


class ForgeArchitectureDetail(BaseDetail):
    """Forge architecture selection."""

    detail_type: DetailType = DetailType.FORGE_ARCHITECTURE
    selected: str
    confidence: float
    rationale: str
    alternatives: list[str] = Field(default_factory=list)
    modality: str
    task_type: str
    num_rows: int


class ForgeCandidatesDetail(BaseDetail):
    """Forge candidate models evaluated."""

    detail_type: DetailType = DetailType.FORGE_CANDIDATES
    primary: dict[str, Any]
    alternatives: list[dict[str, Any]] = Field(default_factory=list)


class ForgeRationaleDetail(BaseDetail):
    """Forge selection rationale."""

    detail_type: DetailType = DetailType.FORGE_RATIONALE
    rationale: str
    factors: list[str] = Field(default_factory=list)


class ForgeScriptDetail(BaseDetail):
    """Forge script generation."""

    detail_type: DetailType = DetailType.FORGE_SCRIPT
    script_path: str
    architecture: str
    validation: str = "passed"


class ForgeSearchSpaceDetail(BaseDetail):
    """Forge hyperparameter search space."""

    detail_type: DetailType = DetailType.FORGE_SEARCH_SPACE
    architecture: str
    dimensions: int
    parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ForgeValidationDetail(BaseDetail):
    """Forge validation strategy."""

    detail_type: DetailType = DetailType.FORGE_VALIDATION
    strategy: str
    folds: int
    stratified: bool
    rationale: str


class ForgeImbalanceDetail(BaseDetail):
    """Forge imbalance strategy."""

    detail_type: DetailType = DetailType.FORGE_IMBALANCE
    strategy: str
    reason: str


class FurnaceEpochDetail(BaseDetail):
    """Furnace epoch/trial progress."""

    detail_type: DetailType = DetailType.FURNACE_EPOCH
    epoch: int
    total_epochs: int | None = None
    trial: int = 0
    total_trials: int | None = None
    train_loss: float | None = None
    val_loss: float | None = None
    metric_name: str | None = None
    metric_value: float | None = None
    best_score: float | None = None
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0


class FurnaceTrialDetail(BaseDetail):
    """Furnace trial progress."""

    detail_type: DetailType = DetailType.FURNACE_TRIAL
    trial: int
    total_trials: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class FurnaceMetricDetail(BaseDetail):
    """Furnace metric update."""

    detail_type: DetailType = DetailType.FURNACE_METRIC
    metric_name: str
    metric_value: float
    best_metric: float
    is_improvement: bool = False


class FurnaceTimeDetail(BaseDetail):
    """Furnace time update."""

    detail_type: DetailType = DetailType.FURNACE_TIME
    training_time_seconds: float
    eta_seconds: float | None = None


class FurnaceContainerDetail(BaseDetail):
    """Furnace container info."""

    detail_type: DetailType = DetailType.FURNACE_CONTAINER
    container_name: str
    docker_image: str


class FurnaceCheckpointDetail(BaseDetail):
    """Furnace checkpoint info."""

    detail_type: DetailType = DetailType.FURNACE_CHECKPOINT
    checkpoint_path: str
    epoch: int
    metric_value: float


class DissectErrorDetail(BaseDetail):
    """Dissect error classification."""

    detail_type: DetailType = DetailType.DISSECT_ERROR
    exception_type: str
    exception_message: str
    category: str
    confidence: float
    match_method: str


class DissectCascadeDetail(BaseDetail):
    """Dissect cascade attempt."""

    detail_type: DetailType = DetailType.DISSECT_CASCADE
    level: int
    level_name: str
    strategy: str
    outcome: str
    message: str = ""


class DissectPatchDetail(BaseDetail):
    """Dissect patch application."""

    detail_type: DetailType = DetailType.DISSECT_PATCH
    patch_id: str
    lines_changed: int
    diff: str | None = None


class DissectSandboxDetail(BaseDetail):
    """Dissect sandbox test result."""

    detail_type: DetailType = DetailType.DISSECT_SANDBOX
    passed: bool
    output: str
    duration_seconds: float = 0.0


class DissectOutcomeDetail(BaseDetail):
    """Dissect final outcome."""

    detail_type: DetailType = DetailType.DISSECT_OUTCOME
    outcome: str
    patch_id: str
    escalation_reason: str | None = None


class ArbiterMetricsDetail(BaseDetail):
    """Arbiter computed metrics."""

    detail_type: DetailType = DetailType.ARBITER_METRICS
    task_type: str
    primary_metric: str
    primary_value: float
    all_metrics: dict[str, float] = Field(default_factory=dict)
    num_samples: int = 0


class ArbiterDecisionDetail(BaseDetail):
    """Arbiter decision."""

    detail_type: DetailType = DetailType.ARBITER_DECISION
    decision: str
    explanation: str
    metric_value: float
    threshold: float | None = None
    operator: str = ">"


class ArbiterThresholdDetail(BaseDetail):
    """Arbiter threshold info."""

    detail_type: DetailType = DetailType.ARBITER_THRESHOLD
    threshold: float
    operator: str
    metric: str
    source: str = "user_defined"


class ArbiterLeaderboardDetail(BaseDetail):
    """Arbiter candidate leaderboard."""

    detail_type: DetailType = DetailType.ARBITER_LEADERBOARD
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ArbiterReportDetail(BaseDetail):
    """Arbiter report paths."""

    detail_type: DetailType = DetailType.ARBITER_REPORT
    eval_report_path: str
    metrics_csv_path: str
    decision_json_path: str
    plots_dir: str


class HarborDeployDetail(BaseDetail):
    """Harbor deployment progress."""

    detail_type: DetailType = DetailType.HARBOR_DEPLOY
    stage: str
    progress: float = 0.0
    message: str = ""


class HarborEndpointDetail(BaseDetail):
    """Harbor endpoint info."""

    detail_type: DetailType = DetailType.HARBOR_ENDPOINT
    endpoint_url: str
    model_format: str
    port: int


class HarborFormatDetail(BaseDetail):
    """Harbor model format."""

    detail_type: DetailType = DetailType.HARBOR_FORMAT
    format: str
    fallback: bool = False
    reason: str = ""


class HarborHealthDetail(BaseDetail):
    """Harbor health check."""

    detail_type: DetailType = DetailType.HARBOR_HEALTH
    status: str
    latency_ms: float | None = None
    checked_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class HarborDriftDetail(BaseDetail):
    """Harbor drift detection."""

    detail_type: DetailType = DetailType.HARBOR_DRIFT
    psi_score: float
    psi_threshold: float
    feature: str
    window_size: int


class HarborSelfTestDetail(BaseDetail):
    """Harbor self-test result."""

    detail_type: DetailType = DetailType.HARBOR_SELFTEST
    passed: bool
    detail: str
    command: str | None = None


class MissionStartDetail(BaseDetail):
    """Mission started."""

    detail_type: DetailType = DetailType.MISSION_START
    problem_description: str
    dataset_path: str
    target_column: str | None = None


class MissionCompleteDetail(BaseDetail):
    """Mission completed."""

    detail_type: DetailType = DetailType.MISSION_COMPLETE
    status: str
    duration_seconds: float
    final_metric: float | None = None
    endpoint_url: str | None = None


class MissionArtifactDetail(BaseDetail):
    """Mission artifact produced."""

    detail_type: DetailType = DetailType.MISSION_ARTIFACT
    name: str
    path: str
    size_bytes: int
    artifact_type: str


class HeartbeatDetail(BaseDetail):
    """Agent heartbeat."""

    detail_type: DetailType = DetailType.HEARTBEAT
    agent: str
    status: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


DETAIL_TYPE_MAP: dict[DetailType, type[BaseDetail]] = {
    DetailType.PIPELINE_STATE: PipelineStateDetail,
    DetailType.SCOUT_DATASET: ScoutDatasetDetail,
    DetailType.SCOUT_DATA_QUALITY: ScoutDataQualityDetail,
    DetailType.SCOUT_TASK: ScoutTaskDetail,
    DetailType.SCOUT_METRIC: ScoutMetricDetail,
    DetailType.SCOUT_MODALITY: ScoutModalityDetail,
    DetailType.SCOUT_RECOMMENDATION: ScoutRecommendationDetail,
    DetailType.SCOUT_CONFIDENCE: ScoutConfidenceDetail,
    DetailType.FORGE_ARCHITECTURE: ForgeArchitectureDetail,
    DetailType.FORGE_CANDIDATES: ForgeCandidatesDetail,
    DetailType.FORGE_RATIONALE: ForgeRationaleDetail,
    DetailType.FORGE_SCRIPT: ForgeScriptDetail,
    DetailType.FORGE_SEARCH_SPACE: ForgeSearchSpaceDetail,
    DetailType.FORGE_VALIDATION: ForgeValidationDetail,
    DetailType.FORGE_IMBALANCE: ForgeImbalanceDetail,
    DetailType.FURNACE_EPOCH: FurnaceEpochDetail,
    DetailType.FURNACE_TRIAL: FurnaceTrialDetail,
    DetailType.FURNACE_METRIC: FurnaceMetricDetail,
    DetailType.FURNACE_TIME: FurnaceTimeDetail,
    DetailType.FURNACE_CONTAINER: FurnaceContainerDetail,
    DetailType.FURNACE_CHECKPOINT: FurnaceCheckpointDetail,
    DetailType.DISSECT_ERROR: DissectErrorDetail,
    DetailType.DISSECT_CASCADE: DissectCascadeDetail,
    DetailType.DISSECT_PATCH: DissectPatchDetail,
    DetailType.DISSECT_SANDBOX: DissectSandboxDetail,
    DetailType.DISSECT_OUTCOME: DissectOutcomeDetail,
    DetailType.ARBITER_METRICS: ArbiterMetricsDetail,
    DetailType.ARBITER_DECISION: ArbiterDecisionDetail,
    DetailType.ARBITER_THRESHOLD: ArbiterThresholdDetail,
    DetailType.ARBITER_LEADERBOARD: ArbiterLeaderboardDetail,
    DetailType.ARBITER_REPORT: ArbiterReportDetail,
    DetailType.HARBOR_DEPLOY: HarborDeployDetail,
    DetailType.HARBOR_ENDPOINT: HarborEndpointDetail,
    DetailType.HARBOR_FORMAT: HarborFormatDetail,
    DetailType.HARBOR_HEALTH: HarborHealthDetail,
    DetailType.HARBOR_DRIFT: HarborDriftDetail,
    DetailType.HARBOR_SELFTEST: HarborSelfTestDetail,
    DetailType.MISSION_START: MissionStartDetail,
    DetailType.MISSION_COMPLETE: MissionCompleteDetail,
    DetailType.MISSION_ARTIFACT: MissionArtifactDetail,
    DetailType.HEARTBEAT: HeartbeatDetail,
}


def create_detail(detail_type: DetailType, **kwargs) -> BaseDetail:
    """Factory function to create typed detail objects."""
    model_class = DETAIL_TYPE_MAP.get(detail_type)
    if model_class is None:
        return BaseDetail(detail_type=detail_type, **kwargs)
    return model_class(**kwargs)


def detail_to_dict(detail: BaseDetail) -> dict[str, Any]:
    """Convert detail to flat dict for Redis stream."""
    return detail.model_dump()


def dict_to_detail(data: dict[str, Any]) -> BaseDetail:
    """Convert flat dict back to typed detail."""
    detail_type_str = data.get("detail_type")
    if not detail_type_str:
        return BaseDetail(detail_type=DetailType.PIPELINE_STATE, **data)
    try:
        detail_type = DetailType(detail_type_str)
    except ValueError:
        return BaseDetail(**data)
    return create_detail(detail_type, **data)

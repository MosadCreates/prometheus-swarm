"""Shared data models — single source of truth for mission execution.

Every agent reads and writes MissionState. No agent invents its own state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from runtime.paths import get_job_paths

from contracts import RetryPlan  # noqa: F811 — replaces legacy dataclass below

# ── Known supported architectures (source of truth, single list) ──

SUPPORTED_ARCHITECTURES: dict[str, int] = {
    "lightgbm": 7,
    "xgboost": 6,
    "tabnet": 7,
    "distilbert": 5,
    "efficientnet": 5,
}


def check_architecture_supported(name: str) -> int:
    """Return minimum search space dimensions, or raise ValueError."""
    dims = SUPPORTED_ARCHITECTURES.get(name)
    if dims is None:
        raise ValueError(
            f"Unsupported architecture '{name}'. Supported: "
            f"{', '.join(sorted(SUPPORTED_ARCHITECTURES))}"
        )
    return dims


# ── Failure taxonomy ──

FAILURE_CATEGORIES: dict[str, str] = {
    "shape_mismatch": "Training input shape mismatch",
    "dtype_mismatch": "Data type conversion failure",
    "missing_column": "Required column not found in dataset",
    "import_error": "Missing Python dependency",
    "nan_propagation": "NaN or Inf values in data",
    "oom": "Out of memory (RAM)",
    "cuda_oom": "CUDA out of memory",
    "convergence_failure": "Model failed to converge",
    "label_encoding": "Target label encoding failure",
    "checkpoint_corruption": "Checkpoint file corrupted",
    "timeout": "Operation timed out",
    "docker_failure": "Docker container failure",
    "training_exception": "Generic training exception",
    "unknown": "Unclassified error",
}

FAILURE_RECOVERY: dict[str, str] = {
    "shape_mismatch": "dissect",
    "dtype_mismatch": "dissect",
    "missing_column": "dissect",
    "import_error": "install_dependency",
    "nan_propagation": "dissect",
    "oom": "reduce_batch_size",
    "cuda_oom": "reduce_batch_size",
    "convergence_failure": "retry_planner",
    "label_encoding": "dissect",
    "checkpoint_corruption": "restart_from_scratch",
    "timeout": "retry_planner",
    "docker_failure": "infrastructure",
    "training_exception": "retry_planner",
    "metric_below_threshold": "retry_planner",
    "unknown": "retry_planner",
}


def classify_exception(exc_type: str, exc_msg: str) -> str:
    """Classify an exception into a FailureReport category."""
    exc_lower = exc_msg.lower()
    if exc_type == "ValueError":
        if "shape" in exc_lower or "feature" in exc_lower or "dimension" in exc_lower:
            return "shape_mismatch"
        if "convert string to float" in exc_lower or "dtype" in exc_lower:
            return "dtype_mismatch"
        if "nan" in exc_lower or "inf" in exc_lower:
            return "nan_propagation"
        if "label" in exc_lower or "class" in exc_lower:
            return "label_encoding"
        return "training_exception"
    if exc_type == "TypeError":
        if "sparse" in exc_lower:
            return "shape_mismatch"
        return "training_exception"
    if exc_type == "MemoryError":
        return "oom"
    if exc_type == "RuntimeError":
        if "cuda" in exc_lower or "out of memory" in exc_lower:
            return "cuda_oom"
        if "label" in exc_lower:
            return "label_encoding"
        return "training_exception"
    if exc_type == "KeyError":
        return "missing_column"
    if exc_type == "ModuleNotFoundError" or exc_type == "ImportError":
        return "import_error"
    if exc_type == "FileNotFoundError":
        return "checkpoint_corruption"
    if exc_type in ("subprocess.CalledProcessError", "docker.errors.DockerException"):
        return "docker_failure"
    if exc_type == "asyncio.TimeoutError":
        return "timeout"
    return "unknown"


def recovery_path(category: str) -> str:
    """Map failure category to recovery action."""
    return FAILURE_RECOVERY.get(category, "retry_planner")


# ── Timeline entry ──


@dataclass
class TimelineEntry:
    phase: str
    agent: str
    message: str
    detail: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "agent": self.agent,
            "message": self.message,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


# ── FailureReport: structured failure from any agent ──


@dataclass
class FailureReport:
    phase: str
    exception_type: str
    exception_message: str
    category: str = "unknown"
    repairable: bool = False
    retryable: bool = True
    stacktrace: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_exception(
        cls,
        phase: str,
        exception: Exception,
        category: str | None = None,
        repairable: bool = False,
        retryable: bool = True,
    ) -> FailureReport:
        import traceback

        exc_type = type(exception).__name__
        exc_msg = str(exception)
        cat = category or classify_exception(exc_type, exc_msg)
        return cls(
            phase=phase,
            exception_type=exc_type,
            exception_message=exc_msg,
            category=cat,
            repairable=repairable,
            retryable=retryable,
            stacktrace=traceback.format_exc(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "category": self.category,
            "repairable": self.repairable,
            "retryable": self.retryable,
            "stacktrace": self.stacktrace,
            "timestamp": self.timestamp,
        }


# ── RetryAttemptRecord: one entry in the retry history ──


@dataclass
class RetryAttemptRecord:
    attempt: int
    architecture: str
    metric_value: float
    metric_name: str
    decision: str
    rationale: str = ""
    failure_category: str = ""
    checkpoint_path: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "architecture": self.architecture,
            "metric_value": self.metric_value,
            "metric_name": self.metric_name,
            "decision": self.decision,
            "rationale": self.rationale,
            "failure_category": self.failure_category,
            "checkpoint_path": self.checkpoint_path,
            "timestamp": self.timestamp,
        }


# ── RetryPlan: delegated to contracts.RetryPlan (Pydantic)
RetryContext = RetryPlan

# ── TrainingJob: typed specification for Furnace execution ──


@dataclass(frozen=True)
class TrainingJob:
    job_id: str
    retry_attempt: int
    architecture: str
    imbalance_strategy: str
    optuna_trials: int
    feature_engineering_level: str
    script_path: str
    output_dir: str
    search_space_json: str | None = None
    checkpoint_path: str | None = None
    metric_name: str = "auc_roc"
    deployment_threshold: float | None = None

    def validate(self) -> None:
        """Validate the TrainingJob before execution. Raises on first failure."""
        import os as _os

        if not _os.path.exists(self.script_path):
            raise FileNotFoundError(f"Training script not found: {self.script_path}")
        check_architecture_supported(self.architecture)
        if self.optuna_trials < 1:
            raise ValueError(f"optuna_trials must be >= 1, got {self.optuna_trials}")
        valid_imbalance = ("none", "class_weight", "smote", "focal_loss")
        if self.imbalance_strategy not in valid_imbalance:
            raise ValueError(
                f"Unknown imbalance strategy '{self.imbalance_strategy}'. "
                f"Valid: {valid_imbalance}"
            )
        valid_fe = ("none", "basic", "interaction", "advanced")
        if self.feature_engineering_level not in valid_fe:
            raise ValueError(
                f"Unknown feature_engineering_level '{self.feature_engineering_level}'. "
                f"Valid: {valid_fe}"
            )
        _os.makedirs(self.output_dir, exist_ok=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "retry_attempt": self.retry_attempt,
            "architecture": self.architecture,
            "imbalance_strategy": self.imbalance_strategy,
            "optuna_trials": self.optuna_trials,
            "feature_engineering_level": self.feature_engineering_level,
            "script_path": self.script_path,
            "output_dir": self.output_dir,
            "search_space_json": self.search_space_json,
            "checkpoint_path": self.checkpoint_path,
            "metric_name": self.metric_name,
            "deployment_threshold": self.deployment_threshold,
        }

    @classmethod
    def from_retry_plan(
        cls,
        plan: RetryPlan,
        job_id: str,
        script_path: str,
        search_space_json: str | None = None,
        checkpoint_path: str | None = None,
    ) -> TrainingJob:
        output_dir = plan.output_dir or str(get_job_paths(job_id).retry_dir(plan.attempt))
        return cls(
            job_id=job_id,
            retry_attempt=plan.attempt,
            architecture=plan.architecture,
            imbalance_strategy=plan.imbalance_strategy,
            optuna_trials=plan.num_trials,
            feature_engineering_level=plan.feature_engineering_level,
            script_path=script_path,
            output_dir=output_dir,
            search_space_json=search_space_json,
            checkpoint_path=checkpoint_path,
        )


# ── MissionState: single source of truth ──

MISSION_PHASES = [
    "MISSION_CREATED",
    "SCOUT_RUNNING",
    "SCOUT_COMPLETED",
    "FORGE_RUNNING",
    "FORGE_COMPLETED",
    "FURNACE_RUNNING",
    "FURNACE_COMPLETED",
    "TRAINING_FAILED",
    "DISSECT_RUNNING",
    "DISSECT_COMPLETED",
    "ARBITER_RUNNING",
    "ARBITER_COMPLETED",
    "RETRY_PENDING",
    "RETRY_RUNNING",
    "RETRY_COMPLETED",
    "MISSION_PASSED",
    "MISSION_FAILED",
]

PHASE_TRANSITIONS: dict[str, list[str]] = {
    "MISSION_CREATED": ["SCOUT_RUNNING"],
    "SCOUT_RUNNING": ["SCOUT_COMPLETED", "MISSION_FAILED"],
    "SCOUT_COMPLETED": ["FORGE_RUNNING"],
    "FORGE_RUNNING": ["FORGE_COMPLETED", "MISSION_FAILED"],
    "FORGE_COMPLETED": ["FURNACE_RUNNING"],
    "FURNACE_RUNNING": ["FURNACE_COMPLETED", "TRAINING_FAILED"],
    "FURNACE_COMPLETED": ["ARBITER_RUNNING"],
    "TRAINING_FAILED": ["DISSECT_RUNNING", "RETRY_PENDING", "MISSION_FAILED"],
    "DISSECT_RUNNING": ["DISSECT_COMPLETED", "MISSION_FAILED"],
    "DISSECT_COMPLETED": ["FURNACE_RUNNING"],
    "ARBITER_RUNNING": ["ARBITER_COMPLETED"],
    "ARBITER_COMPLETED": ["RETRY_PENDING", "MISSION_PASSED", "MISSION_FAILED"],
    "RETRY_PENDING": ["RETRY_RUNNING", "MISSION_FAILED"],
    "RETRY_RUNNING": ["FORGE_RUNNING", "RETRY_COMPLETED", "MISSION_FAILED"],
    "RETRY_COMPLETED": ["ARBITER_RUNNING", "MISSION_FAILED"],
    "MISSION_PASSED": [],
    "MISSION_FAILED": [],
}


def validate_transition(from_phase: str, to_phase: str) -> None:
    allowed = PHASE_TRANSITIONS.get(from_phase, [])
    if to_phase not in allowed:
        raise ValueError(
            f"Invalid phase transition: {from_phase} → {to_phase}. " f"Allowed: {allowed}"
        )


@dataclass
class MissionState:
    """Single source of truth for mission execution.

    Every agent reads this at start and writes at end.
    No agent invents or duplicates state.
    """

    job_id: str
    phase: str = "MISSION_CREATED"
    retry_number: int = 0
    max_retries: int = 3
    architecture: str = ""
    imbalance_strategy: str = "none"
    optuna_trials: int = 30
    metric_name: str = "auc_roc"
    metric_value: float = 0.0
    deployment_threshold: float | None = None
    best_metric: float = 0.0
    best_architecture: str = ""
    best_checkpoint: str = ""
    script_path: str = ""
    tried_architectures: list[str] = field(default_factory=list)
    failures: list[dict[str, Any]] = field(default_factory=list)
    retry_history: list[RetryAttemptRecord] = field(default_factory=list)
    timeline: list[TimelineEntry] = field(default_factory=list)
    phase_timestamps: dict[str, str] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition_to(self, phase: str) -> None:
        validate_transition(self.phase, phase)
        self.phase = phase
        self.phase_timestamps[phase] = datetime.now(timezone.utc).isoformat()
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_timeline(self, agent: str, message: str, **detail: Any) -> None:
        self.timeline.append(
            TimelineEntry(
                phase=self.phase,
                agent=agent,
                message=message,
                detail=detail,
            )
        )
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_failure(self, failure: FailureReport) -> None:
        self.failures.append(failure.to_dict())
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_retry_attempt(self, entry: RetryAttemptRecord) -> None:
        self.retry_number = entry.attempt
        self.architecture = entry.architecture
        self.metric_value = entry.metric_value
        self.metric_name = entry.metric_name
        self.retry_history.append(entry)
        if entry.metric_value > self.best_metric:
            self.best_metric = entry.metric_value
            self.best_architecture = entry.architecture
            self.best_checkpoint = entry.checkpoint_path
        self.updated_at = datetime.now(timezone.utc).isoformat()

    @property
    def has_retries_remaining(self) -> bool:
        return self.retry_number < self.max_retries

    @property
    def next_attempt_number(self) -> int:
        return self.retry_number + 1

    @property
    def is_terminal(self) -> bool:
        return self.phase in ("MISSION_PASSED", "MISSION_FAILED")

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "phase": self.phase,
            "retry_number": self.retry_number,
            "max_retries": self.max_retries,
            "architecture": self.architecture,
            "imbalance_strategy": self.imbalance_strategy,
            "optuna_trials": self.optuna_trials,
            "metric_name": self.metric_name,
            "metric_value": self.metric_value,
            "deployment_threshold": self.deployment_threshold,
            "best_metric": self.best_metric,
            "best_architecture": self.best_architecture,
            "best_checkpoint": self.best_checkpoint,
            "script_path": self.script_path,
            "tried_architectures": self.tried_architectures,
            "failures": self.failures,
            "retry_history": [h.to_dict() for h in self.retry_history],
            "timeline": [t.to_dict() for t in self.timeline],
            "phase_timestamps": self.phase_timestamps,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MissionState:
        retry_history = [
            RetryAttemptRecord(
                attempt=h["attempt"],
                architecture=h["architecture"],
                metric_value=h["metric_value"],
                metric_name=h["metric_name"],
                decision=h["decision"],
                rationale=h.get("rationale", ""),
                failure_category=h.get("failure_category", ""),
                checkpoint_path=h.get("checkpoint_path", ""),
                timestamp=h.get("timestamp", ""),
            )
            for h in data.get("retry_history", [])
        ]
        timeline = [
            TimelineEntry(
                phase=t.get("phase", ""),
                agent=t.get("agent", ""),
                message=t.get("message", ""),
                detail=t.get("detail", {}),
                timestamp=t.get("timestamp", ""),
            )
            for t in data.get("timeline", [])
        ]
        return cls(
            job_id=data["job_id"],
            phase=data.get("phase", "MISSION_CREATED"),
            retry_number=data.get("retry_number", 0),
            max_retries=data.get("max_retries", 3),
            architecture=data.get("architecture", ""),
            imbalance_strategy=data.get("imbalance_strategy", "none"),
            optuna_trials=data.get("optuna_trials", 30),
            metric_name=data.get("metric_name", "auc_roc"),
            metric_value=data.get("metric_value", 0.0),
            deployment_threshold=data.get("deployment_threshold"),
            best_metric=data.get("best_metric", 0.0),
            best_architecture=data.get("best_architecture", ""),
            best_checkpoint=data.get("best_checkpoint", ""),
            script_path=data.get("script_path", ""),
            tried_architectures=data.get("tried_architectures", []),
            failures=data.get("failures", []),
            retry_history=retry_history,
            timeline=timeline,
            phase_timestamps=data.get("phase_timestamps", {}),
            started_at=data.get("started_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# ── Persistence ──


def mission_state_path(job_id: str) -> str:
    return str(get_job_paths(job_id).mission_state_path)


def save_mission_state(state: MissionState) -> str:
    path = mission_state_path(state.job_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.to_dict(), f, indent=2)
    return path


def load_mission_state(job_id: str) -> MissionState | None:
    path = mission_state_path(job_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return MissionState.from_dict(data)
    except (json.JSONDecodeError, KeyError, ValueError):
        return None


async def save_mission_state_to_redis(redis_client, state: MissionState) -> None:
    """Persist mission state to Redis for cross-process access."""
    import json as _json

    await redis_client.set(
        f"job:{state.job_id}:mission_state",
        _json.dumps(state.to_dict()),
    )


async def load_mission_state_from_redis(
    redis_client,
    job_id: str,
) -> MissionState | None:
    """Load mission state from Redis. Falls back to file."""
    import json as _json

    raw = await redis_client.get(f"job:{job_id}:mission_state")
    if raw:
        try:
            data = _json.loads(raw) if isinstance(raw, str) else raw
            return MissionState.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return load_mission_state(job_id)


# ── Backward-compatible aliases ──

MissionExecutionState = MissionState

__all__ = [
    "SUPPORTED_ARCHITECTURES",
    "check_architecture_supported",
    "FAILURE_CATEGORIES",
    "FAILURE_RECOVERY",
    "classify_exception",
    "recovery_path",
    "TimelineEntry",
    "FailureReport",
    "RetryAttemptRecord",
    "RetryPlan",
    "RetryContext",
    "TrainingJob",
    "MissionState",
    "MissionExecutionState",
    "MISSION_PHASES",
    "PHASE_TRANSITIONS",
    "validate_transition",
    "mission_state_path",
    "save_mission_state",
    "load_mission_state",
    "save_mission_state_to_redis",
    "load_mission_state_from_redis",
]

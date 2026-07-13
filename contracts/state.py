"""Mission execution state — single source of truth for job progress.

Every agent reads MissionState at start and writes at end.
No agent invents or duplicates state.
All state carries schema_version for forward compatibility.

Phase 9: authoritative state machine with Redis persistence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

from pydantic import BaseModel, Field, model_validator

from contracts.domain import SCHEMA_VERSION_V1

import logging

logger = logging.getLogger(__name__)


# ── Phase definitions ───────────────────────────────────────────────────


class MissionPhase(str, Enum):
    """Canonical state names for the pipeline lifecycle.

    Every state listed here is the single source of truth.
    The legacy job:{job_id}:status string is always a member of this enum.
    """

    CREATED = "MISSION_CREATED"
    SCOUT_RUNNING = "SCOUT_RUNNING"
    SCOUT_COMPLETED = "SCOUT_COMPLETED"
    FORGE_RUNNING = "FORGE_RUNNING"
    FORGE_COMPLETED = "FORGE_COMPLETED"
    FURNACE_RUNNING = "FURNACE_RUNNING"
    FURNACE_COMPLETED = "FURNACE_COMPLETED"
    TRAINING_FAILED = "TRAINING_FAILED"
    DISSECT_RUNNING = "DISSECT_RUNNING"
    DISSECT_COMPLETED = "DISSECT_COMPLETED"
    ARBITER_RUNNING = "ARBITER_RUNNING"
    ARBITER_COMPLETED = "ARBITER_COMPLETED"
    RETRY_PENDING = "RETRY_PENDING"
    RETRY_RUNNING = "RETRY_RUNNING"
    RETRY_COMPLETED = "RETRY_COMPLETED"
    PASSED = "MISSION_PASSED"
    HARBOR_DEPLOYING = "HARBOR_DEPLOYING"
    HARBOR_COMPLETED = "HARBOR_COMPLETED"
    SCOUT_RETRAIN = "SCOUT_RETRAIN"
    CANCELLED = "CANCELLED"
    FAILED = "MISSION_FAILED"


# ── Transition matrix ──────────────────────────────────────────────────

MISSION_PHASE_TRANSITIONS: dict[str, list[str]] = {
    "MISSION_CREATED": ["SCOUT_RUNNING", "CANCELLED"],
    "SCOUT_RUNNING": ["SCOUT_COMPLETED", "MISSION_FAILED", "CANCELLED"],
    "SCOUT_COMPLETED": ["FORGE_RUNNING", "CANCELLED"],
    "FORGE_RUNNING": ["FORGE_COMPLETED", "MISSION_FAILED", "CANCELLED"],
    "FORGE_COMPLETED": ["FURNACE_RUNNING", "CANCELLED"],
    "FURNACE_RUNNING": ["FURNACE_COMPLETED", "TRAINING_FAILED", "CANCELLED"],
    "FURNACE_COMPLETED": ["ARBITER_RUNNING", "CANCELLED"],
    "TRAINING_FAILED": ["DISSECT_RUNNING", "RETRY_PENDING", "MISSION_FAILED", "CANCELLED"],
    "DISSECT_RUNNING": ["DISSECT_COMPLETED", "MISSION_FAILED", "CANCELLED"],
    "DISSECT_COMPLETED": ["FURNACE_RUNNING", "CANCELLED"],
    "ARBITER_RUNNING": ["ARBITER_COMPLETED", "CANCELLED"],
    "ARBITER_COMPLETED": ["RETRY_PENDING", "MISSION_PASSED", "MISSION_FAILED", "CANCELLED"],
    "RETRY_PENDING": ["RETRY_RUNNING", "MISSION_FAILED", "CANCELLED"],
    "RETRY_RUNNING": ["FORGE_RUNNING", "RETRY_COMPLETED", "MISSION_FAILED", "CANCELLED"],
    "RETRY_COMPLETED": ["ARBITER_RUNNING", "MISSION_FAILED", "CANCELLED"],
    "MISSION_PASSED": ["HARBOR_DEPLOYING", "SCOUT_RETRAIN", "CANCELLED"],
    "HARBOR_DEPLOYING": ["HARBOR_COMPLETED", "MISSION_FAILED", "CANCELLED"],
    "HARBOR_COMPLETED": ["SCOUT_RETRAIN", "CANCELLED"],
    "SCOUT_RETRAIN": ["SCOUT_RUNNING", "CANCELLED"],
    "CANCELLED": [],
    "MISSION_FAILED": [],
}


def validate_phase_transition(from_phase: str, to_phase: str) -> None:
    """Raise ValueError if the transition is not allowed."""
    allowed = MISSION_PHASE_TRANSITIONS.get(from_phase, [])
    if to_phase not in allowed:
        raise ValueError(
            f"Invalid phase transition: {from_phase} → {to_phase}. " f"Allowed: {allowed}"
        )


# ── Terminal / rollup helpers ──────────────────────────────────────────

TERMINAL_PHASES = frozenset({"MISSION_FAILED", "CANCELLED"})
SUCCESS_PHASES = frozenset({"HARBOR_COMPLETED"})
FAILURE_PHASES = frozenset({"MISSION_FAILED", "CANCELLED"})

# Maps legacy ad-hoc status strings to canonical MissionPhase values.
# Used during migration so existing Redis keys are readable.
LEGACY_STATUS_MAP: dict[str, str] = {
    "QUEUED": "MISSION_CREATED",
    "SCOUT_RUNNING": "SCOUT_RUNNING",
    "SCOUT_ANALYZING": "SCOUT_RUNNING",
    "SCOUT_COMPLETED": "SCOUT_COMPLETED",
    "FORGE_RUNNING": "FORGE_RUNNING",
    "FORGE_WORKING": "FORGE_RUNNING",
    "FORGE_RETRY": "FORGE_RUNNING",
    "FORGE_COMPLETED": "FORGE_COMPLETED",
    "FURNACE_TRAINING": "FURNACE_RUNNING",
    "FURNACE_RUNNING": "FURNACE_RUNNING",
    "FURNACE_COMPLETED": "FURNACE_COMPLETED",
    "TRAINING_FAILED": "TRAINING_FAILED",
    "DISSECT_RUNNING": "DISSECT_RUNNING",
    "DISSECT_PATCHING": "DISSECT_RUNNING",
    "DISSECT_COMPLETED": "DISSECT_COMPLETED",
    "ARBITER_EVALUATING": "ARBITER_RUNNING",
    "ARBITER_RUNNING": "ARBITER_RUNNING",
    "ARBITER_COMPLETED": "ARBITER_COMPLETED",
    "RETRY_PENDING": "RETRY_PENDING",
    "RETRY_NEEDED": "RETRY_PENDING",
    "RETRY_RUNNING": "RETRY_RUNNING",
    "RETRY_COMPLETED": "RETRY_COMPLETED",
    "MISSION_PASSED": "MISSION_PASSED",
    "PASSED": "MISSION_PASSED",
    "PASS": "MISSION_PASSED",
    "COMPLETE": "MISSION_PASSED",
    "COMPLETED": "HARBOR_COMPLETED",
    "HARBOR_DEPLOYING": "HARBOR_DEPLOYING",
    "HARBOR_COMPLETED": "HARBOR_COMPLETED",
    "SCOUT_RETRAIN": "SCOUT_RETRAIN",
    "FAILED": "MISSION_FAILED",
    "ESCALATED": "MISSION_FAILED",
    "ESCALATE": "MISSION_FAILED",
    "error": "MISSION_FAILED",
    "ERROR": "MISSION_FAILED",
    "crash": "MISSION_FAILED",
    "timeout": "MISSION_FAILED",
    "CANCELLED": "CANCELLED",
    "cancelled": "CANCELLED",
    "UNKNOWN": "MISSION_CREATED",
}


def canonical_phase(raw: str) -> str:
    """Map any legacy status string to a canonical MissionPhase value."""
    return LEGACY_STATUS_MAP.get(raw, raw)


# ── State sub-models ────────────────────────────────────────────────────


class TimelineEntry(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    phase: str = ""
    agent: str = ""
    message: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class FailureReport(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    phase: str = ""
    exception_type: str = ""
    exception_message: str = ""
    category: str = "unknown"
    repairable: bool = False
    retryable: bool = True
    stacktrace: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

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
        from runtime.models import classify_exception

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


class RetryAttemptRecord(BaseModel):
    schema_version: str = SCHEMA_VERSION_V1
    attempt: int = 0
    architecture: str = ""
    metric_value: float = 0.0
    metric_name: str = "auc_roc"
    decision: str = ""
    rationale: str = ""
    failure_category: str = ""
    checkpoint_path: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── MissionState ────────────────────────────────────────────────────────


class MissionState(BaseModel):
    """Single source of truth for mission execution.
    Every agent reads this at start and writes at end.
    """

    schema_version: str = SCHEMA_VERSION_V1
    job_id: str
    phase: str = "MISSION_CREATED"
    retry_number: int = 0
    max_retries: int = 3
    architecture: str = ""
    imbalance_strategy: str = "none"
    optuna_trials: int = 30
    metric_name: str = "auc_roc"
    metric_value: float = 0.0
    metric_direction: str = "maximize"
    deployment_threshold: float | None = None
    best_metric: float = 0.0
    best_architecture: str = ""
    best_checkpoint: str = ""
    script_path: str = ""
    tried_architectures: list[str] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    retry_history: list[RetryAttemptRecord] = Field(default_factory=list)
    timeline: list[TimelineEntry] = Field(default_factory=list)
    phase_timestamps: dict[str, str] = Field(default_factory=dict)
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition_to(self, phase: str) -> None:
        validate_phase_transition(self.phase, phase)
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
        self.failures.append(failure.model_dump())
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
        return self.phase in TERMINAL_PHASES

    def to_dict(self) -> dict[str, Any]:
        raw = self.model_dump()
        raw["failures"] = [
            f if isinstance(f, dict) else (f.model_dump() if hasattr(f, "model_dump") else dict(f))
            for f in raw.get("failures", [])
        ]
        raw["retry_history"] = [
            r if isinstance(r, dict) else (r.model_dump() if hasattr(r, "model_dump") else dict(r))
            for r in raw.get("retry_history", [])
        ]
        raw["timeline"] = [
            t if isinstance(t, dict) else (t.model_dump() if hasattr(t, "model_dump") else dict(t))
            for t in raw.get("timeline", [])
        ]
        return raw

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MissionState:
        cleaned = dict(data)
        for key in ("retry_history", "timeline"):
            items = cleaned.get(key, [])
            if items and isinstance(items[0], dict):
                cleaned[key] = items
        failures = cleaned.get("failures", [])
        if failures and isinstance(failures[0], dict):
            cleaned["failures"] = failures
        return cls(**cleaned)

    # ── Redis persistence ───────────────────────────────────────────────

    REDIS_KEY: ClassVar[str] = "job:{job_id}:mission_state"

    async def save_to_redis(self, redis_client: Any) -> None:
        """Persist this state to Redis for cross-process access."""
        import json as _json

        key = f"job:{self.job_id}:mission_state"
        raw = self.model_dump_json()
        await redis_client.set(key, raw)
        # Also write the backward-compat status key
        await redis_client.set(f"job:{self.job_id}:status", self.phase)
        logger.info(
            f"[job={self.job_id}] State persisted: {self.phase} " f"(retry={self.retry_number})"
        )

    @classmethod
    async def load_from_redis(cls, redis_client: Any, job_id: str) -> MissionState | None:
        """Load mission state from Redis. Returns None if not found."""
        key = f"job:{job_id}:mission_state"
        raw = await redis_client.get(key)
        if raw:
            try:
                decoded = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                return cls.model_validate_json(decoded)
            except Exception:
                logger.warning(f"[job={job_id}] Failed to decode mission_state from Redis")
                return None
        # Fallback: construct from legacy status key
        legacy_raw = await redis_client.get(f"job:{job_id}:status")
        if legacy_raw:
            legacy = legacy_raw.decode("utf-8") if isinstance(legacy_raw, bytes) else legacy_raw
            canonical = canonical_phase(legacy)
            state = cls(job_id=job_id, phase=canonical)
            state.phase_timestamps[canonical] = datetime.now(timezone.utc).isoformat()
            return state
        return None

    @classmethod
    async def create_or_load(cls, redis_client: Any, job_id: str, **defaults: Any) -> MissionState:
        """Load existing state or create a fresh one with defaults."""
        existing = await cls.load_from_redis(redis_client, job_id)
        if existing is not None:
            return existing
        state = cls(job_id=job_id, **defaults)
        await state.save_to_redis(redis_client)
        return state


# ── Standalone helpers ─────────────────────────────────────────────────


# Lazy-prometheus-metric guard so this module imports cleanly without
# prometheus_client installed.
_transition_counter = None


def _get_transition_counter():
    global _transition_counter
    if _transition_counter is None:
        try:
            from prometheus_client import Counter

            _transition_counter = Counter(
                "prometheus_state_transitions_total",
                "Total state machine transitions",
                ["job_id", "from_phase", "to_phase"],
            )
        except Exception:
            _transition_counter = _NoopCounter()
    return _transition_counter


class _NoopCounter:
    def labels(self, **kwargs):
        return self

    def inc(self, amount=1):
        pass


async def transition_and_save(
    redis_client: Any,
    job_id: str,
    to_phase: str,
    agent: str = "",
    message: str = "",
) -> MissionState:
    """Load, validate-transition, add timeline entry, save, return.

    If no prior state exists (fresh job), the new state is created directly
    at *to_phase* — no transition validation is applied for the first write.
    Once a state exists, all transitions must pass validate_phase_transition.
    """
    state = await MissionState.load_from_redis(redis_client, job_id)
    if state is None:
        state = MissionState(job_id=job_id, phase=to_phase)
        state.phase_timestamps[to_phase] = datetime.now(timezone.utc).isoformat()
        from_phase = to_phase
    else:
        from_phase = state.phase
        state.transition_to(to_phase)
    if agent:
        state.add_timeline(agent=agent, message=message or f"Transition to {to_phase}")
    await state.save_to_redis(redis_client)
    _get_transition_counter().labels(job_id=job_id, from_phase=from_phase, to_phase=to_phase).inc()
    return state

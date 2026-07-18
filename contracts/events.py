"""Typed event payloads for Redis Streams.

Every event published via bus/publisher.py should use one of these models.
This ensures every event carries:
  - schema_version
  - event_type (matches the constant in bus/events.py)
  - job_id
  - timestamp
  - typed fields (no raw dict access by consumers)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from contracts.domain import SCHEMA_VERSION_V1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventPayload(BaseModel):
    """Base for all event payloads. Not published directly."""

    schema_version: str = SCHEMA_VERSION_V1
    event_type: str = ""
    job_id: str = ""
    timestamp: str = Field(default_factory=_now)

    def to_redis_dict(self) -> dict[str, Any]:
        """Flatten to Redis-safe dict (all values str or JSON-encoded)."""
        import json

        flat: dict[str, Any] = {}
        raw = self.model_dump()
        for k, v in raw.items():
            if v is None:
                flat[k] = ""
            elif isinstance(v, (dict, list)):
                flat[k] = json.dumps(v)
            else:
                flat[k] = str(v)
        return flat


class MissionBriefReadyEvent(EventPayload):
    event_type: str = "MISSION_BRIEF_READY"
    job_id: str
    mission_brief_redis_key: str = ""
    mission_spec_redis_key: str = ""
    problem_description: str = ""
    dataset_path: str = ""


class TrainingScriptReadyEvent(EventPayload):
    event_type: str = "TRAINING_SCRIPT_READY"
    job_id: str
    script_path: str = ""
    search_space_redis_key: str = ""


class EpochCompleteEvent(EventPayload):
    event_type: str = "EPOCH_COMPLETE"
    job_id: str
    epoch: int = 0
    train_loss: float = 0.0
    val_loss: float = 0.0
    eta_seconds: int = 0
    trial: int = 0
    total_trials: int = 0
    metric_name: str = ""
    metric_value: float = 0.0
    best_score: float = 0.0
    elapsed_seconds: float = 0.0
    remaining_seconds: float = 0.0


class TrainingCompleteEvent(EventPayload):
    event_type: str = "TRAINING_COMPLETE"
    job_id: str
    checkpoint_path: str = ""
    metrics_path: str = ""
    best_metric: float = 0.0
    best_val_metric: float = 0.0
    metric_name: str = "auc_roc"
    training_time: float = 0.0
    total_epochs: int = 1
    total_trials: int = 1
    total_crashes_recovered: int = 0
    artifact_directory: str = ""


class CrashEventPayload(EventPayload):
    event_type: str = "CRASH_EVENT"
    job_id: str
    script_path: str = ""
    container_name: str = ""
    exit_code: int = -1
    exception_type: str = ""
    exception_message: str = ""
    category: str = "training_exception"
    traceback: str = ""
    container_logs: str = ""
    last_checkpoint_path: str | None = None
    epoch_at_crash: int = 0
    current_trial: int = 0
    crash_attempt_number: int = 1


class ResumeTrainingEvent(EventPayload):
    event_type: str = "RESUME_TRAINING"
    job_id: str
    patched_script_path: str = ""
    resume_from_checkpoint: str | None = None
    patch_id: str = ""
    epoch_count: int = 0


class EscalateEvent(EventPayload):
    event_type: str = "ESCALATE"
    job_id: str
    source_agent: str = ""
    reason: str = ""
    diagnostic_report_path: str = ""


class EvaluationPassEvent(EventPayload):
    event_type: str = "EVALUATION_PASS"
    job_id: str
    eval_report_path: str = ""
    primary_metric: str = "auc_roc"
    primary_metric_value: float = 0.0
    threshold: float | None = None


class EvaluationRetryEvent(EventPayload):
    event_type: str = "EVALUATION_RETRY"
    job_id: str
    eval_report_path: str = ""
    primary_metric: str = "auc_roc"
    primary_metric_value: float = 0.0
    threshold: float | None = None
    reason: str = ""


class EvaluationFailedEvent(EventPayload):
    event_type: str = "EVALUATION_FAILED"
    job_id: str
    eval_report_path: str = ""
    reason: str = ""


class JobFailedEvent(EventPayload):
    event_type: str = "JOB_FAILED"
    job_id: str
    source_agent: str = ""
    reason: str = ""
    diagnostic_report_path: str = ""


class EndpointLiveEvent(EventPayload):
    event_type: str = "ENDPOINT_LIVE"
    job_id: str
    endpoint_url: str = ""
    val_metric: float = 0.0
    p95_latency_ms: float = 0.0
    model_format: str = ""


class PlanCreatedEvent(EventPayload):
    event_type: str = "PLAN_CREATED"
    job_id: str
    plan_id: str = ""
    estimated_total_minutes: float = 0.0
    confidence_score: float = 0.0
    confidence_assessment: str = ""


class PlanCompletedEvent(EventPayload):
    event_type: str = "PLAN_COMPLETED"
    job_id: str


class PlanFailedEvent(EventPayload):
    event_type: str = "PLAN_FAILED"
    job_id: str


class DriftAlertEvent(EventPayload):
    event_type: str = "DRIFT_ALERT"
    job_id: str
    psi_score: float = 0.0
    psi_threshold: float = 0.2
    window_size: int = 1000
    feature: str = ""


class AgentEventPayload(EventPayload):
    """Agent state-transition event for the live Cockpit.

    Schema: prometheus.agent_event.v1
    Published to STREAM_AGENT_EVENTS so the frontend Cockpit can
    render a real-time feed of what each agent is doing.

    State machine: idle → thinking / planning / acting → verifying → done / error
    """

    event_type: str = "AGENT_EVENT"
    job_id: str
    event_id: str = ""
    mission_id: str = ""
    agent: str = ""
    seq: int = 0
    state: str = "idle"
    summary: str = ""
    detail: str = ""  # JSON-encoded dict; empty string for no detail
    duration_ms: int = 0
    parent_event_id: str = ""

    schema_version: str = "prometheus.agent_event.v1"

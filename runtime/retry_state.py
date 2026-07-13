"""Retry state management — thin wrapper around MissionState.

This module exists for backward compatibility. New code should use
runtime.models.MissionState directly.
"""

from __future__ import annotations

from runtime.models import (
    MissionState,
    RetryAttemptRecord as RetryAttemptRecord,
    RetryPlan as RetryPlan,
    save_mission_state as save_retry_state,
    load_mission_state as load_retry_state,
)
from runtime.retry_orchestrator import MAX_RETRY_ATTEMPTS as MAX_RETRY_ATTEMPTS
from runtime.paths import get_job_paths


class RetryState:
    """Legacy wrapper — delegates to MissionState.

    New code should use MissionState directly.
    """

    def __init__(
        self,
        job_id: str,
        attempt_number: int = 0,
        max_attempts: int = MAX_RETRY_ATTEMPTS,
        current_architecture: str = "lightgbm",
        last_metric_value: float = 0.0,
        last_metric_name: str = "auc_roc",
        last_decision: str = "",
        history: list | None = None,
    ):
        self._mission = MissionState(
            job_id=job_id,
            retry_number=attempt_number,
            max_retries=max_attempts,
            architecture=current_architecture,
            metric_value=last_metric_value,
            metric_name=last_metric_name,
        )
        self._mission.retry_history = history or []
        self._last_decision = last_decision

    # ── Properties mirroring old RetryState API ──

    @property
    def job_id(self) -> str:
        return self._mission.job_id

    @property
    def attempt_number(self) -> int:
        return self._mission.retry_number

    @attempt_number.setter
    def attempt_number(self, val: int) -> None:
        self._mission.retry_number = val

    @property
    def max_attempts(self) -> int:
        return self._mission.max_retries

    @property
    def current_architecture(self) -> str:
        return self._mission.architecture

    @current_architecture.setter
    def current_architecture(self, val: str) -> None:
        self._mission.architecture = val

    @property
    def last_metric_value(self) -> float:
        return self._mission.metric_value

    @last_metric_value.setter
    def last_metric_value(self, val: float) -> None:
        self._mission.metric_value = val

    @property
    def last_metric_name(self) -> str:
        return self._mission.metric_name

    @last_metric_name.setter
    def last_metric_name(self, val: str) -> None:
        self._mission.metric_name = val

    @property
    def last_decision(self) -> str:
        return self._last_decision

    @last_decision.setter
    def last_decision(self, val: str) -> None:
        self._last_decision = val

    @property
    def history(self) -> list:
        return self._mission.retry_history

    @history.setter
    def history(self, val: list) -> None:
        self._mission.retry_history = val

    @property
    def has_retries_remaining(self) -> bool:
        return self._mission.has_retries_remaining

    @property
    def attempts_left(self) -> int:
        return self._mission.max_retries - self._mission.retry_number

    @property
    def next_attempt_number(self) -> int:
        return self._mission.next_attempt_number

    def record_attempt(self, entry: RetryAttemptRecord) -> None:
        self._mission.record_retry_attempt(entry)
        self._last_decision = entry.decision

    def to_dict(self) -> dict:
        d = self._mission.to_dict()
        d["attempt_number"] = d.pop("retry_number", 0)
        d["max_attempts"] = d.pop("max_retries", 3)
        d["current_architecture"] = d.pop("architecture", "")
        d["last_metric_value"] = d.pop("metric_value", 0.0)
        d["last_metric_name"] = d.pop("metric_name", "auc_roc")
        d["last_decision"] = self._last_decision
        d["history"] = d.pop("retry_history", [])
        return d

    @classmethod
    def from_dict(cls, data: dict) -> RetryState:
        history = [
            RetryAttemptRecord(
                attempt=h["attempt"],
                architecture=h["architecture"],
                metric_value=h["metric_value"],
                metric_name=h["metric_name"],
                decision=h["decision"],
                rationale=h.get("rationale", ""),
                timestamp=h.get("timestamp", ""),
            )
            for h in data.get("history", [])
        ]
        return cls(
            job_id=data["job_id"],
            attempt_number=data.get("attempt_number", 0),
            max_attempts=data.get("max_attempts", MAX_RETRY_ATTEMPTS),
            current_architecture=data.get("current_architecture", "lightgbm"),
            last_metric_value=data.get("last_metric_value", 0.0),
            last_metric_name=data.get("last_metric_name", "auc_roc"),
            last_decision=data.get("last_decision", ""),
            history=history,
        )


# Backward-compatible aliases
RetryHistoryEntry = RetryAttemptRecord

# Keep original module-level functions for tests
from runtime.models import (  # noqa: F811
    save_mission_state,
    load_mission_state,
)

import os as _os
import json as _json


def retry_state_path(job_id: str) -> str:
    return str(get_job_paths(job_id).job_dir / "retry_state.json")




"""RetryEngine — central controller for the retry lifecycle.

Single source of truth for:
- Current attempt tracking
- Strategy generation (delegates to retry_strategy)
- Retry history (list of RetryAttemptRecord)
- Decision logging
- Best metric tracking
- Termination logic (PASS / FAIL / ESCALATE)
- Persistence (retry_history.json)

Owned by the Orchestrator. No other component controls retries.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contracts import RetryAttemptRecord, RetryPlan, ScoutIntelligence
from runtime.retry_strategy import build_next_strategy_from_state
from runtime.paths import get_job_paths

logger = logging.getLogger(__name__)


class RetryEngine:
    """Central controller for the retry lifecycle.

    Responsibilities:
    - current_attempt, max_attempts — attempt tracking
    - generate_strategy() — delegates to retry_strategy, returns immutable RetryPlan
    - record_attempt() — appends to retry_history, tracks best_metric
    - best_metric — read-only property across all attempts
    - should_terminate() — decides if loop should stop
    - save_history() / load_history() — retry_history.json persistence
    - decision_logging() — structured log entry per lifecycle event
    """

    def __init__(
        self,
        job_id: str,
        max_attempts: int = 4,
        metric_name: str = "auc_roc",
        metric_value: float = 0.0,
        architecture: str = "lightgbm",
        imbalance_strategy: str = "none",
        deployment_threshold: float | None = None,
        retry_history: list[RetryAttemptRecord] | None = None,
        scout_intelligence: ScoutIntelligence | None = None,
    ) -> None:
        self.job_id = job_id
        self._max_attempts = max_attempts
        self._metric_name = metric_name
        self._metric_value = metric_value
        self._architecture = architecture
        self._imbalance_strategy = imbalance_strategy
        self._deployment_threshold = deployment_threshold
        self._best_metric = 0.0
        self._best_architecture = ""
        self._best_checkpoint = ""
        self._retry_history: list[RetryAttemptRecord] = retry_history or []
        self._scout_intelligence = scout_intelligence

    # ── Read-only properties ──────────────────────────────────────────────

    @property
    def current_attempt(self) -> int:
        return len(self._retry_history)

    @property
    def max_attempts(self) -> int:
        return self._max_attempts

    @property
    def has_retries_remaining(self) -> bool:
        return self.current_attempt < self._max_attempts

    @property
    def next_attempt_number(self) -> int:
        return self.current_attempt + 1

    @property
    def best_metric(self) -> float:
        return self._best_metric

    @property
    def best_architecture(self) -> str:
        return self._best_architecture

    @property
    def best_checkpoint(self) -> str:
        return self._best_checkpoint

    @property
    def retry_history(self) -> list[RetryAttemptRecord]:
        return list(self._retry_history)

    @property
    def deployment_threshold(self) -> float | None:
        return self._deployment_threshold

    # ── Strategy generation ───────────────────────────────────────────────

    def generate_strategy(
        self,
        previous_metric_value: float | None = None,
        previous_metric_name: str | None = None,
    ) -> RetryPlan:
        """Generate the next immutable RetryPlan.

        Delegates to retry_strategy.build_next_strategy_from_state.
        The returned RetryPlan is frozen — callers must NOT mutate it.
        """
        attempt = self.next_attempt_number
        used_archs = [h.architecture for h in self._retry_history if h.architecture]
        strategy = build_next_strategy_from_state(
            attempt=attempt,
            current_architecture=self._architecture,
            previous_imbalance=self._imbalance_strategy,
            previous_metric_name=previous_metric_name or self._metric_name,
            previous_metric_value=previous_metric_value or self._metric_value,
            used_architectures=used_archs,
            max_attempts=self._max_attempts,
            scout_intelligence=self._scout_intelligence,
        )
        logger.debug(
            f"[job={self.job_id}] RetryPlan generated: "
            f"attempt={strategy.attempt}, "
            f"architecture={strategy.architecture}, "
            f"num_trials={strategy.num_trials}"
        )
        return strategy

    # ── Attempt recording ─────────────────────────────────────────────────

    def record_attempt(self, entry: RetryAttemptRecord) -> None:
        """Record a completed retry attempt.

        Appends to retry_history, updates best_metric tracking.
        """
        self._retry_history.append(entry)
        if entry.metric_value > self._best_metric:
            self._best_metric = entry.metric_value
            self._best_architecture = entry.architecture
            self._best_checkpoint = entry.checkpoint_path
        self._architecture = entry.architecture
        self._metric_value = entry.metric_value
        self._metric_name = entry.metric_name
        logger.debug(
            f"[job={self.job_id}] Attempt {entry.attempt} recorded: "
            f"architecture={entry.architecture}, "
            f"metric={entry.metric_value:.4f}, "
            f"decision={entry.decision}"
        )

    # ── Termination logic ─────────────────────────────────────────────────

    def should_terminate(self, decision: str) -> bool:
        """Return True if the retry loop should stop.

        Rules:
        - PASS → terminate (success)
        - No retries remaining → terminate (failure)
        """
        if decision == "PASS":
            return True
        if not self.has_retries_remaining:
            return True
        return False

    @property
    def is_exhausted(self) -> bool:
        """Return True if all retries have been used."""
        return not self.has_retries_remaining and self.current_attempt > 0

    # ── Decision logging ──────────────────────────────────────────────────

    def decision_logging(
        self,
        event: str,
        attempt: int | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """Create a structured log entry for the retry lifecycle.

        Returns a dict suitable for appending to retry_history.json.
        """
        entry: dict[str, Any] = {
            "event": event,
            "job_id": self.job_id,
            "attempt": attempt or self.current_attempt,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        entry.update(extra)
        return entry

    # ── Persistence: retry_history.json ───────────────────────────────────

    @property
    def _history_path(self) -> Path:
        return get_job_paths(self.job_id).retry_history_path

    def save_history(self) -> str:
        """Write retry_history.json to the job output directory.

        Returns the path written to.
        """
        path = self._history_path
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "schema_version": "1",
            "job_id": self.job_id,
            "max_attempts": self._max_attempts,
            "best_metric": self._best_metric,
            "best_architecture": self._best_architecture,
            "best_checkpoint": self._best_checkpoint,
            "metric_name": self._metric_name,
            "deployment_threshold": self._deployment_threshold,
            "attempts": [
                {
                    "attempt": h.attempt,
                    "architecture": h.architecture,
                    "metric_value": h.metric_value,
                    "metric_name": h.metric_name,
                    "decision": h.decision,
                    "rationale": h.rationale,
                    "failure_category": h.failure_category,
                    "checkpoint_path": h.checkpoint_path,
                    "timestamp": h.timestamp,
                }
                for h in self._retry_history
            ],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        logger.info(f"[job={self.job_id}] Retry history saved to {path}")
        return str(path)

    def load_history(self) -> bool:
        """Load retry_history.json from the job output directory.

        Returns True if history was loaded, False if no file exists.
        """
        path = self._history_path
        if not path.exists():
            return False
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            attempts_data = data.get("attempts", [])
            self._max_attempts = data.get("max_attempts", self._max_attempts)
            self._best_metric = data.get("best_metric", 0.0)
            self._best_architecture = data.get("best_architecture", "")
            self._best_checkpoint = data.get("best_checkpoint", "")
            self._retry_history = [
                RetryAttemptRecord(
                    attempt=a["attempt"],
                    architecture=a["architecture"],
                    metric_value=a["metric_value"],
                    metric_name=a.get("metric_name", "auc_roc"),
                    decision=a["decision"],
                    rationale=a.get("rationale", ""),
                    failure_category=a.get("failure_category", ""),
                    checkpoint_path=a.get("checkpoint_path", ""),
                    timestamp=a.get("timestamp", ""),
                )
                for a in attempts_data
            ]
            logger.info(
                f"[job={self.job_id}] Retry history loaded: " f"{len(self._retry_history)} attempts"
            )
            return True
        except Exception as e:
            logger.warning(f"[job={self.job_id}] Failed to load retry history: {e}")
            return False

    # ── Summary ───────────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Return a summary dict of retry status."""
        return {
            "job_id": self.job_id,
            "current_attempt": self.current_attempt,
            "max_attempts": self._max_attempts,
            "has_retries_remaining": self.has_retries_remaining,
            "best_metric": self._best_metric,
            "best_architecture": self._best_architecture,
            "best_checkpoint": self._best_checkpoint,
            "deployment_threshold": self._deployment_threshold,
            "total_attempts": len(self._retry_history),
        }

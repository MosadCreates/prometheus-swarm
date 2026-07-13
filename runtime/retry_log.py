"""Per-retry structured logging — each retry attempt writes a retry_log.json.

The retry_log.json is a JSON array of entries, one per lifecycle event
for the retry attempt (started, validation_pass, training_started,
crash_occurred, training_complete, eval_complete, decision_reached).

This is separate from the global patch_log (which tracks Dissect patches).
The retry_log tracks the full retry lifecycle for debugging and audit.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_RETRY_LOG_FILENAME = "retry_log.json"


def _retry_log_path(output_dir: str) -> str:
    return os.path.join(output_dir, _RETRY_LOG_FILENAME)


def _read_entries(output_dir: str) -> list[dict[str, Any]]:
    path = _retry_log_path(output_dir)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else [data]
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read retry_log {path}: {e}")
        return []


def _write_entries(output_dir: str, entries: list[dict[str, Any]]) -> None:
    os.makedirs(output_dir, exist_ok=True)
    path = _retry_log_path(output_dir)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, default=str)


def append_retry_log_entry(output_dir: str, entry: dict[str, Any]) -> str:
    """Append a single entry to the retry_log.json for this retry attempt.

    The entry is timestamped automatically and appended to the existing
    entries in the array. Creates the file if it doesn't exist.

    Args:
        output_dir: The retry's output directory (e.g., outputs/job_x/retry_1/).
        entry: Dict with at minimum 'event' and 'event_data' keys.

    Returns:
        The path to the retry_log.json file.
    """
    entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    entry.setdefault("event", "unknown")
    entries = _read_entries(output_dir)
    entries.append(entry)
    _write_entries(output_dir, entries)
    return _retry_log_path(output_dir)


def create_retry_log(
    output_dir: str,
    job_id: str,
    retry_attempt: int,
    architecture: str,
    imbalance_strategy: str,
    optuna_trials: int,
    feature_engineering_level: str,
    metric_name: str,
    deployment_threshold: float | None = None,
) -> str:
    """Create the initial retry_log.json with the attempt's specification.

    Args:
        output_dir: Isolated output directory for this retry.
        job_id: The job ID.
        retry_attempt: 1-indexed retry attempt number.
        architecture: Model architecture.
        imbalance_strategy: Imbalance handling strategy.
        optuna_trials: Number of Optuna trials.
        feature_engineering_level: Feature engineering level.
        metric_name: Primary evaluation metric name.
        deployment_threshold: Minimum acceptable metric value.

    Returns:
        Path to the created retry_log.json.
    """
    os.makedirs(output_dir, exist_ok=True)
    entry = {
        "event": "retry_started",
        "job_id": job_id,
        "retry_attempt": retry_attempt,
        "architecture": architecture,
        "imbalance_strategy": imbalance_strategy,
        "optuna_trials": optuna_trials,
        "feature_engineering_level": feature_engineering_level,
        "metric_name": metric_name,
        "deployment_threshold": deployment_threshold,
        "status": "pending",
    }
    return append_retry_log_entry(output_dir, entry)


def update_retry_log_status(
    output_dir: str,
    event: str,
    **extra_fields: Any,
) -> str:
    """Append a status-update entry to the retry_log.json.

    Args:
        output_dir: The retry's output directory.
        event: Event name (e.g., 'training_started', 'crash_occurred').
        **extra_fields: Additional fields to include in the entry.

    Returns:
        Path to the retry_log.json file.
    """
    entry: dict[str, Any] = {"event": event}
    entry.update(extra_fields)
    return append_retry_log_entry(output_dir, entry)

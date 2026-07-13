"""Structured mission state logging — single source of truth for pipeline debugging.

Every agent calls `log_mission_state()` at start and end of its run.
This reveals where state changes unexpectedly.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _brief_hash(brief: dict | None) -> str:
    """Compute a stable hash of the mission brief to detect unexpected changes."""
    if not brief:
        return "none"
    canonical = json.dumps(brief, sort_keys=True, default=str)
    return hashlib.md5(canonical.encode()).hexdigest()[:8]


def _safe(val: Any, default: str = "?") -> str:
    if val is None:
        return default
    return str(val)


def log_mission_state(
    stage: str,
    job_id: str,
    retry_number: int = 0,
    architecture: str | None = None,
    imbalance_strategy: str | None = None,
    search_space: dict | None = None,
    metric_name: str | None = None,
    metric_value: float | None = None,
    deployment_threshold: float | None = None,
    script_path: str | None = None,
    checkpoint_path: str | None = None,
    brief: dict | None = None,
    **extra: Any,
) -> None:
    """Log the complete mission state at a given stage.

    Every agent must call this at start and end of its run.
    Args become log fields. Output is a single INFO-level log line
    parsable by grep.
    """
    fields: dict[str, str] = {
        "MISSION_STATE": stage,
        "job_id": _safe(job_id),
        "retry": str(retry_number),
        "architecture": _safe(architecture),
        "imbalance": _safe(imbalance_strategy),
        "metric": _safe(metric_name),
        "threshold": _safe(deployment_threshold),
        "script": _safe(script_path),
        "checkpoint": _safe(checkpoint_path),
        "brief_hash": _brief_hash(brief),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if search_space is not None:
        fields["search_dims"] = str(len(search_space))
    if metric_value is not None:
        fields["metric_val"] = f"{metric_value:.4f}"

    for k, v in extra.items():
        fields[k.replace("_", "-")] = _safe(v)

    parts = [f"{k}={v}" for k, v in fields.items()]
    logger.info(f"MISSION_STATE | {' | '.join(parts)}")


def log_event_flow(
    job_id: str,
    event_type: str,
    phase: str,
    **extra: Any,
) -> None:
    """Log every event type as it flows through the pipeline."""
    fields: dict[str, str] = {
        "EVENT_FLOW": event_type,
        "job_id": _safe(job_id),
        "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    for k, v in extra.items():
        fields[k.replace("_", "-")] = _safe(v)
    parts = [f"{k}={v}" for k, v in fields.items()]
    logger.info(f"EVENT_FLOW | {' | '.join(parts)}")

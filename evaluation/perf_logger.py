"""Per-stage performance logger.

Records wall-clock timing for each pipeline stage per job.
Written to outputs/{job_id}/perf_log.jsonl as JSONL.
Each line is one stage event.

Stage events:
  scout_start, scout_end
  planner_start, planner_end  (or planner_skipped)
  forge_start, forge_end
  furnace_start, furnace_end
  dissect_start, dissect_end  (per crash)
  arbiter_start, arbiter_end
  harbor_start, harbor_end
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from runtime.paths import get_job_paths

logger = logging.getLogger(__name__)


def _ensure_log_dir(job_id: str) -> Path:
    log_dir = get_job_paths(job_id).job_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _append(job_id: str, entry: dict[str, Any]) -> None:
    log_dir = _ensure_log_dir(job_id)
    line = json.dumps(entry, separators=(",", ":")) + "\n"
    log_path = log_dir / "perf_log.jsonl"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to write perf log: {e}")


def record_stage(
    job_id: str,
    stage: str,
    status: str = "start",
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record a stage timing event.

    Args:
        job_id: Job UUID.
        stage: Stage name (scout, planner, forge, furnace, dissect, arbiter, harbor).
        status: "start", "end", "skipped", "error".
        metadata: Optional extra fields (duration_s, tokens, cost, etc.).
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "job_id": job_id,
        "stage": stage,
        "status": status,
    }
    if metadata:
        entry.update(metadata)
    _append(job_id, entry)


def read_perf_log(job_id: str) -> list[dict[str, Any]]:
    """Read a job's performance log. Returns list of entries or empty list."""
    log_path = get_job_paths(job_id).job_dir / "perf_log.jsonl"
    if not log_path.exists():
        return []
    entries = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception as e:
        logger.warning(f"[job={job_id}] Failed to read perf log: {e}")
    return entries


def summarize_job_perf(job_id: str) -> dict[str, Any]:
    """Aggregate a job's perf log into a stage-by-stage summary.

    Returns dict with per-stage start/end times and durations.
    """
    entries = read_perf_log(job_id)
    stages: dict[str, dict[str, Any]] = {}

    for entry in entries:
        stage = entry.get("stage", "")
        status = entry.get("status", "")
        if stage not in stages:
            stages[stage] = {}
        if status == "start":
            stages[stage]["start"] = entry["timestamp"]
        elif status == "end":
            stages[stage]["end"] = entry["timestamp"]
        elif status == "skipped":
            stages[stage]["skipped"] = True
        elif status == "error":
            stages[stage]["error"] = entry.get("duration_s", 0)

    summary = {}
    for stage, timings in stages.items():
        s: dict[str, Any] = {}
        if timings.get("skipped"):
            s["status"] = "skipped"
            s["duration_s"] = 0.0
        elif "start" in timings and "end" in timings:
            try:
                start = datetime.fromisoformat(timings["start"])
                end = datetime.fromisoformat(timings["end"])
                s["duration_s"] = round((end - start).total_seconds(), 2)
                s["status"] = "completed"
            except (ValueError, TypeError):
                s["status"] = "unknown"
        elif "start" in timings:
            s["status"] = "incomplete"
        summary[stage] = s

    return summary

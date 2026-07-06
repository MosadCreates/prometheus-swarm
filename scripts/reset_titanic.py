"""Reset the Titanic job for re-processing with the dataset mount fix."""

import json
import redis
import shutil
from pathlib import Path

r = redis.Redis("localhost", 6379, decode_responses=True)
job_id = "4fcfcff1-78d1-4550-95f0-b932f5868eae"

# Reset status to QUEUED
r.set(f"job:{job_id}:status", "QUEUED")
r.set(f"job:{job_id}:current_agent", "")
r.delete(f"job:{job_id}:api_cost")
r.delete(f"job:{job_id}:api_cost_summary")
r.delete(f"job:{job_id}:checkpoint")

# Clean up old outputs
for p in [Path(f"outputs/{job_id}"), Path(f"scripts/training_script_{job_id}.py")]:
    if p.exists():
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
        print(f"Removed {p}")

# Clear all streams so the only event is a fresh MISSION_BRIEF_READY
for s in [
    "scout_output",
    "forge_output",
    "furnace_output",
    "furnace_crash",
    "furnace_feed",
    "dissect_output",
    "arbiter_output",
    "harbor_output",
    "orchestrator_out",
]:
    r.delete(s)

# Publish fresh MISSION_BRIEF_READY with all fields Scout needs
file_path = r.get(f"job:{job_id}:file_path")
problem = r.get(f"job:{job_id}:problem_description")
r.xadd(
    "scout_output",
    {
        "event_type": "MISSION_BRIEF_READY",
        "job_id": job_id,
        "problem_description": problem or "",
        "file_path": file_path or "",
        "timestamp": "2026-07-03T18:00:00Z",
    },
    "*",
)

print("Job reset. Ready for re-processing.")

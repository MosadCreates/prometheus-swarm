"""Reset and publish MISSION_BRIEF_READY for the Titanic job."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import redis

job_id = "4fcfcff1-78d1-4550-95f0-b932f5868eae"
r = redis.Redis("localhost", 6379, decode_responses=True)

# Publish fresh MISSION_BRIEF_READY
file_path = r.get(f"job:{job_id}:file_path")
problem = r.get(f"job:{job_id}:problem_description")
r.xadd(
    "scout_output",
    {
        "event_type": "MISSION_BRIEF_READY",
        "job_id": job_id,
        "problem_description": problem or "",
        "file_path": file_path or "",
        "timestamp": "2026-07-03T19:15:00Z",
    },
    "*",
)

# Also set status to QUEUED
r.set(f"job:{job_id}:status", "QUEUED")
r.set(f"job:{job_id}:current_agent", "")
r.delete(f"job:{job_id}:api_cost")
r.delete(f"job:{job_id}:api_cost_summary")
r.delete(f"job:{job_id}:checkpoint")

print("Published MISSION_BRIEF_READY for retry")

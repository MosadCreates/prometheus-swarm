import redis
from datetime import datetime, timezone

r = redis.Redis("localhost", 6379, decode_responses=True)

job_id = "4fcfcff1-78d1-4550-95f0-b932f5868eae"

file_path = r.get(f"job:{job_id}:file_path")
problem_description = r.get(f"job:{job_id}:problem_description")

if not file_path or not problem_description:
    print("ERROR: job data not found in Redis")
    exit(1)

fields = {
    "event_type": "MISSION_BRIEF_READY",
    "job_id": job_id,
    "problem_description": problem_description,
    "file_path": file_path,
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

result = r.xadd("scout_output", fields, "*")
print(f"Published (stream id: {result})")

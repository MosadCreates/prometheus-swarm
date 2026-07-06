import redis

r = redis.Redis("localhost", 6379, decode_responses=True)
keys = r.keys("job:*")
jobs = set()
for k in keys:
    parts = k.split(":")
    if len(parts) >= 2:
        jobs.add(parts[1])
for j in sorted(jobs):
    status = r.get(f"job:{j}:status") or "?"
    desc = r.get(f"job:{j}:problem_description") or ""
    print(f"{j[:30]:30s} status={status:20s} {desc[:60]}")

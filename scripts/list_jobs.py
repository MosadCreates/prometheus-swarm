import redis

r = redis.Redis("localhost", 6379, decode_responses=True)
cursor = 0
keys: list[str] = []
while True:
    cursor, batch = r.scan(cursor=cursor, match="job:*", count=100)
    keys.extend(batch)
    if cursor == 0:
        break
jobs = set()
for k in keys:
    parts = k.split(":")
    if len(parts) >= 2:
        jobs.add(parts[1])
for j in sorted(jobs):
    status = r.get(f"job:{j}:status") or "?"
    desc = r.get(f"job:{j}:problem_description") or ""
    print(f"{j[:30]:30s} status={status:20s} {desc[:60]}")

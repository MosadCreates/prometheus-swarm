import redis

r = redis.Redis("localhost", 6379, decode_responses=True)

# Keep only the Titanic job
keep = "4fcfcff1"

cursor = 0
keys: list[str] = []
while True:
    cursor, batch = r.scan(cursor=cursor, match="job:*", count=100)
    keys.extend(batch)
    if cursor == 0:
        break
for k in keys:
    parts = k.split(":", 2)
    jid = parts[1]
    if not jid.startswith(keep):
        r.delete(k)

# Also clear all stream messages
streams = [
    "scout_output",
    "forge_output",
    "furnace_output",
    "furnace_crash",
    "furnace_feed",
    "dissect_output",
    "arbiter_output",
    "harbor_output",
    "orchestrator_out",
]
for s in streams:
    try:
        r.delete(s)
    except Exception:
        pass

print("Cleared old jobs and streams. Only Titanic job remains.")

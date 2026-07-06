import redis

r = redis.Redis("localhost", 6379, decode_responses=True)
groups = [
    "orchestrator_consumers",
    "forge_consumers",
    "furnace_consumers",
    "dissect_consumers",
    "arbiter_consumers",
    "harbor_consumers",
    "scout_consumers",
    "frontend_consumers",
]
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
cleaned = 0
for s in streams:
    for g in groups:
        try:
            r.xgroup_destroy(s, g)
            cleaned += 1
        except Exception:
            pass
print(f"Cleaned {cleaned} consumer groups")

"""Check Redis stream and consumer group state."""

import redis

r = redis.Redis("localhost", 6379, decode_responses=True)
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
    count = r.xlen(s)
    print(f"{s}: {count} entries")
    try:
        groups = r.xinfo_groups(s)
        for g in groups:
            pending = g["pending"]
            print(f"  Group {g['name']} on {s}: pending={pending}, consumers={g['consumers']}")
    except Exception:
        print(f"  No groups on {s}")

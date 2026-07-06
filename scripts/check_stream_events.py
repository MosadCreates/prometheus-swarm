"""Check what events are in the streams."""

import redis

r = redis.Redis("localhost", 6379, decode_responses=True)
streams = [
    "scout_output",
    "forge_output",
    "furnace_output",
    "furnace_crash",
    "dissect_output",
    "arbiter_output",
    "harbor_output",
    "orchestrator_out",
]

for s in streams:
    entries = r.xrange(s, "-", "+", count=10)
    for msg_id, data in entries:
        evt = data.get("event_type", "?")
        jid = data.get("job_id", "?")
        print(f"{s} [id={msg_id[:15]}..] event={evt} job={jid}")

"""One-time cleanup: remove stale p2-test prevention rules from Redis."""
import os
import redis as sync_redis
from dotenv import load_dotenv

load_dotenv()

host = os.getenv("REDIS_HOST", "localhost")
port = int(os.getenv("REDIS_PORT", 6379))
password = os.getenv("REDIS_PASSWORD") or None

r = sync_redis.Redis(host=host, port=port, password=password, decode_responses=True)

# Scan all prevention rule keys
removed = 0
for key in r.scan_iter("forge:prevention_rules:*"):
    for i in range(r.llen(key)):
        raw = r.lindex(key, i)
        if raw and "p2-test-" in raw:
            rule_data = __import__("json").loads(raw)
            rule_id = rule_data.get("rule_id", "unknown")
            print(f"Removing stale rule: {rule_id} (key={key})")
            r.lrem(key, 1, raw)
            removed += 1

if removed:
    print(f"Removed {removed} stale prevention rule(s)")
else:
    print("No stale rules found — Redis is clean")

r.close()

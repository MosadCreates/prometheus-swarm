# Skill-context fixtures (`tests/fixtures/skill_contexts/<agent>.json`)

Each file is the install-time **agent-compat smoke context** for one agent
(loaded by `agents/skills/installer.py:build_dry_run_context`). It carries
`brief` / `spec` / `paths` shaped exactly like the real
`MissionBrief` / `MissionSpecification` contracts (`contracts/domain.py`) that
Scout writes for a live job, so a skill claiming to target an agent is
smoke-run against data that agent would really see — a Scout-only skill that
reads Harbor-only paths fails the gate here.

## Provenance

These are **schema-derived snapshots** (built 2026-08-10 from
`contracts/domain.py` field lists, titanic-style classification mission).
They are structurally correct and stable, but they are **not yet captured from
a real run**. To replace them with ground-truth captures, run one mission and
dump what Scout actually persisted:

```powershell
# after `python -m prometheus mission new ...` completes
python - <<'PY'
import json, asyncio
from memory.redis_client import RedisClient

async def capture(job_id: str):
    r = RedisClient()
    await r.connect()
    brief = await r.get_json(f"job:{job_id}:mission_brief")
    spec = await r.get_json(f"job:{job_id}:mission_spec")
    for agent in ["scout", "forge", "furnace", "dissect", "arbiter", "harbor"]:
        doc = {"brief": brief, "spec": spec, "paths": {}}
        (f"tests/fixtures/skill_contexts/{agent}.json").write_text(
            json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    await r.aclose()

asyncio.run(capture("<real-job-id>"))
PY
```

Re-capturing keeps the compat gate honest as the mission contracts evolve.

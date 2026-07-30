"""Phase 1 exit test: run one mission headlessly, assert captured event sequence."""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv()


async def run_exit_test() -> bool:
    """Run the full mission pipeline via job_runner and validate agent_events."""
    from orchestrator.job_runner import run_job, JobConfig
    from memory.redis_client import RedisClient

    job_id = "phase1-exit-" + str(uuid.uuid4())[:8]
    dataset = os.path.abspath("tests/fixtures/titanic.csv")

    rc = RedisClient()
    await rc.connect()
    raw_client = rc._client

    config = JobConfig(
        problem_description="Predict passenger survival on the Titanic",
        dataset_path=dataset,
        target_column="Survived",
        use_docker=False,
        use_harbor=False,
        use_dissect=True,
        timeout_seconds=180,
        job_id=job_id,
    )

    # Clear stream for clean test
    try:
        await raw_client.delete("agent_events")
        for a in ("Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"):
            await raw_client.delete(f"job:{job_id}:agent_event_seq:{a}")
    except Exception:
        pass

    print(f"Running mission (job_id={job_id})...")
    result = await run_job(config, raw_client)
    print(f"Mission complete: status={result.status} metric={result.metric_value}")

    # Read ALL agent_events from stream (don't filter by job_id — read all)
    events = await raw_client.xrevrange("agent_events", max="+", min="-", count=1000)
    job_events: list[dict] = []
    for msg_id, fields in events:
        ev = {k: v for k, v in fields.items()}
        if ev.get("job_id") == job_id:
            job_events.append(ev)

    job_events.reverse()  # chronological

    print(f"\nCaptured {len(job_events)} agent events:")
    for ev in job_events:
        print(
            f"  [{ev.get('agent','?'):8s}] "
            f"{ev.get('state','?'):10s} "
            f"seq={ev.get('seq','?'):4s} "
            f"dur={ev.get('duration_ms','?'):>5s}ms "
            f"{ev.get('summary','?')}"
        )

    # === VALIDATIONS ===

    # V1: At least one event captured
    if not job_events:
        print("FAIL: No agent events captured")
        return False

    # V2: Scout events exist with correct state progression
    scout_events = [e for e in job_events if e.get("agent") == "Scout"]
    if not scout_events:
        print("FAIL: No Scout events")
        return False

    scout_states = [e.get("state") for e in scout_events]
    print(f"\n  Scout states: {scout_states}")

    # Must have acting (EDA) -> thinking (reasoning) progression
    if "acting" not in scout_states:
        print("FAIL: Scout missing 'acting' state")
        return False
    if "thinking" not in scout_states:
        print("FAIL: Scout missing 'thinking' state")
        return False

    # V3: Forge events exist with correct state progression
    forge_events = [e for e in job_events if e.get("agent") == "Forge"]
    forge_states = [e.get("state") for e in forge_events]
    print(f"  Forge states: {forge_states}")
    if not forge_events:
        print("FAIL: No Forge events")
        return False
    if "acting" not in forge_states:
        print("FAIL: Forge missing 'acting' state")
        return False

    # V4: Furnace events exist
    furnace_events = [e for e in job_events if e.get("agent") == "Furnace"]
    furnace_states = [e.get("state") for e in furnace_events]
    print(f"  Furnace states: {furnace_states}")
    if not furnace_events:
        print("FAIL: No Furnace events")
        return False
    if "acting" not in furnace_states:
        print("FAIL: Furnace missing 'acting' state")
        return False

    # V5: Arbiter events exist
    arbiter_events = [e for e in job_events if e.get("agent") == "Arbiter"]
    arbiter_states = [e.get("state") for e in arbiter_events]
    print(f"  Arbiter states: {arbiter_states}")
    if not arbiter_events:
        print("FAIL: No Arbiter events")
        return False

    # V6: All duration_ms are non-negative
    for ev in job_events:
        dur_str = ev.get("duration_ms", "0")
        try:
            dur = int(dur_str)
        except (ValueError, TypeError):
            print(f"FAIL: Non-integer duration_ms={dur_str!r}")
            return False
        if dur < 0:
            print(f"FAIL: Negative duration_ms={dur} in {ev.get('agent')}/{ev.get('state')}")
            return False

    # V7: Monotonic sequence numbers per agent
    for agent_name in ("Scout", "Forge", "Furnace", "Arbiter"):
        agent_evs = [e for e in job_events if e.get("agent") == agent_name]
        seen_seqs = []
        for ev in agent_evs:
            try:
                seq = int(ev.get("seq", -1))
            except (ValueError, TypeError):
                seq = -1
            seen_seqs.append(seq)
        if seen_seqs:
            expected = list(range(1, len(seen_seqs) + 1))
            if seen_seqs != expected:
                print(f"FAIL: {agent_name} seq numbers {seen_seqs} != expected {expected}")
                return False

    # V8: Agent list covers expected agents
    emitted_agents = set(e.get("agent") for e in job_events)
    expected_agents = {"Scout", "Forge", "Furnace", "Arbiter"}
    missing = expected_agents - emitted_agents
    if missing:
        print(f"FAIL: Missing agent events for: {missing}")
        return False

    print(
        f"\nPASS: All validations passed "
        f"({len(job_events)} events, {len(emitted_agents)} agents)"
    )
    return True


if __name__ == "__main__":
    success = asyncio.run(run_exit_test())
    sys.exit(0 if success else 1)

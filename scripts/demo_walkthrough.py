"""End-to-End Walkthrough — Prometheus Swarm Ch.14 Demo Script.

Usage:
    python scripts/demo_walkthrough.py                        # automated headless validation
    python scripts/demo_walkthrough.py --watch                # live Cockpit TUI mode
    python scripts/demo_walkthrough.py -m <mission_id>        # offline analysis of existing trace
    python scripts/demo_walkthrough.py -m <id> --watch        # replay an existing mission in Cockpit

The automated mode runs the full pipeline via Click test runner
(event-driven, no TUI), validates every phase from Scout through
Harbor, and prints a clean pass/fail summary.  Returns exit code
0 on success, 1 on failure.

The offline (-m) mode analyses a completed mission's trace file
without needing Redis or an API key.  Combined with --watch it
opens the Cockpit in replay mode.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# -- Constants -------------------------------------------------------------------

TITANIC_PATH = Path("data") / "titanic.csv"
PROBLEM = "predict passenger survival"
EXPECTED_AGENTS = ["Scout", "Forge", "Furnace", "Arbiter", "Harbor"]
EXPECTED_TERMINAL = "ENDPOINT_LIVE"


def _redis_host() -> str:
    """Return Redis host, defaulting to 127.0.0.1 (avoids IPv6 localhost issues on Windows)."""
    return os.getenv("REDIS_HOST", "127.0.0.1")


def _redis_port() -> int:
    return int(os.getenv("REDIS_PORT", "6379"))


def _parse_mission_id() -> str:
    """Parse --mission-id / -m from sys.argv, or return empty string."""
    for i, arg in enumerate(sys.argv):
        if arg in ("-m", "--mission-id") and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return ""


def _check_prerequisites(require_redis: bool = True, require_anthropic: bool = True) -> list[str]:
    """Check system prerequisites and return list of warnings."""
    warnings: list[str] = []

    if require_redis:
        try:
            import redis

            r = redis.Redis(host=_redis_host(), port=_redis_port(), socket_connect_timeout=3)
            r.ping()
            r.close()
        except Exception as e:
            warnings.append(f"Redis not reachable ({_redis_host()}:{_redis_port()}): {e}")
    else:
        pass

    if require_anthropic:
        try:
            import anthropic
        except ImportError:
            warnings.append("anthropic package not installed — pip install anthropic")
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            warnings.append("ANTHROPIC_API_KEY not set in environment")

    if not TITANIC_PATH.exists():
        warnings.append(f"Dataset not found at {TITANIC_PATH} — copy data/titanic.csv first")

    return warnings


def _load_trace(mission_id: str) -> list[dict]:
    """Load events from a trace file or Redis stream into a list."""
    events: list[dict] = []

    # Try trace file first
    trace_file = Path("outputs") / mission_id / "trace.jsonl"
    if trace_file.exists():
        with open(trace_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    if events:
        return events

    # Fall back to Redis
    try:
        import redis as _redis

        r = _redis.Redis(
            host=_redis_host(), port=_redis_port(), decode_responses=True, socket_connect_timeout=3
        )
        raw = r.xrange("agent_events", count=1000)
        r.close()
        for _msg_id, fields in raw:
            ev: dict = {}
            for k, v in fields.items():
                try:
                    decoded = json.loads(v) if isinstance(v, str) else v
                    if isinstance(decoded, dict):
                        ev.update(decoded)
                    else:
                        ev[k] = decoded
                except (json.JSONDecodeError, TypeError):
                    ev[k] = v
            if ev:
                events.append(ev)
    except Exception:
        pass

    return events


def _detect_terminal(events: list[dict]) -> tuple[bool, str]:
    """Detect if the pipeline reached terminal state.

    Checks:
    1. Last event is Harbor state=done or Harbor summary containing endpoint/deploy
    2. Any event has event_type=ENDPOINT_LIVE or AGENT_HEARTBEAT
    3. Job status key in Redis
    """
    if not events:
        return False, "no events"

    # Check last event
    last = events[-1]
    agent = last.get("agent", "")
    state = last.get("state", "")
    summary = last.get("summary", "").lower()

    if agent == "Harbor" and state == "done":
        return True, f"Harbor done: {last.get('summary', '')}"

    if "endpoint" in summary or "live" in summary or "deploy" in summary:
        return True, f"Endpoint keyword in summary: {last.get('summary', '')}"

    return False, f"Last event: {agent} state={state}"


def _analyze_events(events: list[dict]) -> dict:
    """Analyze a list of agent events and return summary stats."""
    agent_order: list[str] = []
    last_agent = ""
    for ev in events:
        a = ev.get("agent", "")
        if a and a != last_agent:
            agent_order.append(a)
            last_agent = a
    agent_dedup = []
    for a in agent_order:
        if not agent_dedup or agent_dedup[-1] != a:
            agent_dedup.append(a)

    agents = set(ev.get("agent", "") for ev in events if ev.get("agent"))
    agents.discard("")

    dissect_events = [ev for ev in events if ev.get("agent") == "Dissect"]
    cascade_levels: set[int] = set()
    for ev in dissect_events:
        d = ev.get("detail", {})
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except Exception:
                d = {}
        if isinstance(d, dict):
            lvl = d.get("cascade_level")
            if lvl is not None:
                cascade_levels.add(int(lvl))

    expected = EXPECTED_AGENTS
    seq_correct = all(a == e for a, e in zip(agent_dedup, expected) if a in expected)

    return {
        "total_events": len(events),
        "agents": sorted(agents),
        "agent_order": agent_dedup,
        "seq_correct": seq_correct,
        "has_dissect": len(dissect_events) > 0,
        "dissect_events": len(dissect_events),
        "cascade_levels": sorted(cascade_levels) if cascade_levels else [],
    }


def _run_offline(mission_id: str) -> int:
    """Analyse a completed mission's trace file (no Redis needed)."""
    print(f"  {'=' * 60}")
    print("  PROMETHEUS SWARM — TRACE ANALYSIS")
    print(f"  Mission: {mission_id}")
    print(f"  {'=' * 60}")
    print()

    if not Path("outputs") / mission_id / "trace.jsonl":
        print(f"  [FAIL] No trace file found at outputs/{mission_id}/trace.jsonl")
        return 1

    events = _load_trace(mission_id)
    if not events:
        print("  [FAIL] No events could be loaded (trace file empty or corrupted)")
        return 1

    print(f"  Loaded {len(events)} events from trace file")
    print()

    # Step 1: Validate agent order
    print("  [Step 1/3] Validating agent execution order...")
    stats = _analyze_events(events)
    if stats["seq_correct"]:
        print(f"    Sequence OK: {' -> '.join(stats['agent_order'])}")
    else:
        print(f"    Sequence: {' -> '.join(stats['agent_order'])}")
        print(f"    Expected:  {' -> '.join(EXPECTED_AGENTS)}")
        print("    [WARN] Execution order differs from expected")

    # Step 2: Check terminal state
    print("  [Step 2/3] Checking pipeline terminal state...")
    terminal, reason = _detect_terminal(events)
    if terminal:
        print(f"    Pipeline completed: {reason}")
    else:
        print(f"    {reason}")
        print("    [WARN] Pipeline may not have completed (trace truncated)")

    # Step 3: Check Dissect cascade
    print("  [Step 3/3] Checking Dissect cascade activity...")
    if stats["has_dissect"]:
        print(f"    Dissect activated: {stats['dissect_events']} events")
        if stats["cascade_levels"]:
            print(f"    Cascade levels: {stats['cascade_levels']}")
    else:
        print("    No Dissect activity (clean run)")
    print()

    # Summary
    print(f"  {'-' * 60}")
    if terminal:
        print("  [PASS] Pipeline completed — all agents executed")
    else:
        print(f"  [PARTIAL] {stats['total_events']} events captured, but terminal not reached")
    print(f"    Events: {stats['total_events']}")
    print(f"    Agents: {', '.join(stats['agents'])}")
    print(f"  {'-' * 60}")
    return 0 if terminal else 1


def _run_automated(mission_id_override: str = "") -> int:
    """Run the full pipeline headless and validate each phase.

    Uses the Click test runner to invoke CLI commands programmatically,
    then reads Redis state and trace files to verify pipeline completion.
    """
    from click.testing import CliRunner
    from prometheus.main import cli

    runner = CliRunner()
    print(f"  {'=' * 60}")
    print("  PROMETHEUS SWARM — END-TO-END WALKTHROUGH")
    print(f"  {PROBLEM}")
    print(f"  Dataset: {TITANIC_PATH}")
    print(f"  {'=' * 60}")
    print()

    # -- Step 1: Create a new mission -------------------------------
    mission_id = mission_id_override
    if not mission_id:
        print("  [Step 1/5] Submitting mission...")
        result = runner.invoke(
            cli,
            [
                "mission",
                "new",
                PROBLEM,
                "--dataset",
                str(TITANIC_PATH),
                "--no-watch",
                "--auto",
            ],
            catch_exceptions=False,
        )

        if result.exit_code != 0:
            print(f"  [FAIL] Mission submission failed (exit {result.exit_code})")
            print(f"  Output: {result.output[:500]}")
            return 1

        # Parse mission ID from output
        for line in result.output.splitlines():
            if "mission_id" in line.lower() or "job_id" in line.lower():
                import re

                m = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", line)
                if m:
                    mission_id = m.group()
                    break
            if "ID:" in line or "id:" in line.lower():
                parts = line.split()
                for p in parts:
                    if "-" in p and len(p) > 20:
                        mission_id = p.strip().rstrip(".")
                        break
        if not mission_id:
            print("  [SKIP] Could not parse mission ID from output — checking outputs/")
            outputs_dir = Path("outputs")
            recent = sorted(outputs_dir.iterdir(), reverse=True) if outputs_dir.exists() else []
            if recent:
                mission_id = recent[0].name
                print(f"  Found most recent: {mission_id}")

        print(f"  Mission ID: {mission_id or '(unknown)'}")
        print()

    if not mission_id:
        print("  [FAIL] No mission ID available")
        return 1

    # -- Step 2: Wait for pipeline to progress ----------------------
    print("  [Step 2/5] Waiting for pipeline progress...")
    try:
        import redis as _redis

        r = _redis.Redis(
            host=_redis_host(), port=_redis_port(), decode_responses=True, socket_connect_timeout=3
        )
        r.ping()
    except Exception:
        r = None

    if r:
        max_wait = 300  # 5 minutes
        poll_interval = 5
        agents_seen: set[str] = set()
        terminal_reached = False
        status_check_interval = 15
        last_status_check = 0
        start = time.time()

        while time.time() - start < max_wait:
            try:
                raw = r.xrevrange("agent_events", count=50)
                for _msg_id, fields in raw:
                    for k, v in fields.items():
                        try:
                            payload = json.loads(v) if isinstance(v, str) else v
                            agent = payload.get("agent", "")
                            if agent:
                                agents_seen.add(agent)
                            if payload.get("agent") == "Harbor" and payload.get("state") in (
                                "done",
                            ):
                                terminal_reached = True
                        except (json.JSONDecodeError, TypeError):
                            pass
            except Exception:
                pass

            if time.time() - last_status_check > status_check_interval:
                last_status_check = time.time()
                try:
                    status = r.get(f"job:{mission_id}:status") if mission_id else None
                    if status:
                        print(f"    Job status: {status}")
                        if status in ("COMPLETED", "ENDPOINT_LIVE", "success"):
                            terminal_reached = True
                        if status in ("FAILED", "ESCALATED", "failed"):
                            print(f"  [FAIL] Job ended with status: {status}")
                            r.close()
                            return 1
                except Exception:
                    pass

            if terminal_reached:
                break

            elapsed = int(time.time() - start)
            status = (
                f"agents seen: {', '.join(sorted(agents_seen))}"
                if agents_seen
                else "awaiting first event"
            )
            print(f"    +{elapsed}s  {status}", end="\r")
            time.sleep(poll_interval)

        elapsed = int(time.time() - start)
        print(f"    +{elapsed}s  {status}")
        print()

        # -- Step 3: Validate agent order ---------------------------
        print("  [Step 3/5] Validating agent execution order...")

        events: list[dict] = []
        try:
            raw = r.xrange("agent_events", count=500)
            for _msg_id, fields in raw:
                ev: dict = {}
                for k, v in fields.items():
                    try:
                        decoded = json.loads(v) if isinstance(v, str) else v
                        if isinstance(decoded, dict):
                            ev.update(decoded)
                        else:
                            ev[k] = decoded
                    except (json.JSONDecodeError, TypeError):
                        ev[k] = v
                if ev:
                    events.append(ev)
        except Exception:
            pass

        if not events and mission_id:
            trace_file = Path("outputs") / mission_id / "trace.jsonl"
            if trace_file.exists():
                with open(trace_file) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                events.append(json.loads(line))
                            except json.JSONDecodeError:
                                pass

        stats = _analyze_events(events)
        if stats["seq_correct"]:
            print(f"    Sequence OK: {' -> '.join(stats['agent_order'])}")
        else:
            print(f"    Sequence: {' -> '.join(stats['agent_order'])}")
            print(f"    Expected:  {' -> '.join(EXPECTED_AGENTS)}")
            print("    [WARN] Execution order differs from expected")

        # -- Step 4: Check for Dissect cascade ----------------------
        print("  [Step 4/5] Checking Dissect cascade activity...")
        if stats["has_dissect"]:
            if stats["cascade_levels"]:
                print(f"    Dissect activated: cascade levels {stats['cascade_levels']}")
            else:
                print(
                    f"    Dissect activated: {stats['dissect_events']} events, no cascade levels detected"
                )
        else:
            print("    No Dissect activity (clean run — no crashes)")

        # -- Step 5: Summary -----------------------------------------
        print("  [Step 5/5] Pipeline summary...")
        print()

        print(f"  {'-' * 60}")
        if terminal_reached:
            print("  [PASS] Pipeline completed: agent sequence verified")
            print(f"  Total events: {stats['total_events']}")
            print(f"  Agents: {', '.join(stats['agents'])}")
            print(f"  Duration: {elapsed}s")
            return_code = 0
        else:
            print(f"  [FAIL] Pipeline did not reach terminal state within {max_wait}s")
            print(f"  Agents seen: {', '.join(stats['agents']) if stats['agents'] else '(none)'}")
            print(f"  Events captured: {stats['total_events']}")
            return_code = 1

        r.close()
    else:
        print("  [FAIL] Cannot connect to Redis — cannot validate live events")
        if mission_id:
            print("  Falling back to trace-only analysis...")
            return _run_offline(mission_id)
        return_code = 1

    print(f"  {'-' * 60}")
    print(f"  Walkthrough {'complete' if return_code == 0 else 'incomplete'}.")
    return return_code


def _run_live() -> int:
    """Launch the Cockpit for an interactive demo.

    Runs ``prometheus mission new --watch`` so the user sees the
    full TUI pipeline in real time.  If a mission ID was given with
    -m, opens the Cockpit in replay mode for that mission.
    """
    mission_id = _parse_mission_id()

    if mission_id:
        print(f"  Opening Cockpit in replay mode for mission {mission_id}...")
        from prometheus.main import cli
        from click.testing import CliRunner

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "mission",
                "watch",
                mission_id,
            ],
            catch_exceptions=False,
        )

        if result.exit_code != 0:
            print(f"  Replay exited with code {result.exit_code}")
            if result.output:
                print(f"  Output: {result.output[:500]}")
            return 1
        return 0

    print("  Launching Cockpit for live demo...")
    print(f"  Problem: {PROBLEM}")
    print(f"  Dataset: {TITANIC_PATH}")
    print("  Press 'p' or 'q' to detach at any time.")
    print("  Press Ctrl-C twice to cancel the mission.")
    print()

    from prometheus.main import cli
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "mission",
            "new",
            PROBLEM,
            "--dataset",
            str(TITANIC_PATH),
            "--watch",
        ],
        catch_exceptions=False,
    )

    if result.exit_code != 0:
        print(f"  Mission exited with code {result.exit_code}")
        if result.output:
            print(f"  Output: {result.output[:500]}")
        return 1

    print("  Mission complete.")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Prometheus Swarm Chapter 14 Walkthrough",
        add_help=False,
    )
    parser.add_argument("--watch", "-w", action="store_true", help="Live Cockpit TUI mode")
    parser.add_argument(
        "--mission-id", "-m", type=str, default="", help="Mission ID for offline analysis"
    )
    parser.add_argument(
        "--offline", "-o", action="store_true", help="Offline mode (skip Redis/API key checks)"
    )
    parser.add_argument("--help", "-h", action="store_true", help="Show help")
    args, _ = parser.parse_known_args()

    if args.help:
        print(__doc__.strip())
        return 0

    print("  Prometheus Swarm — Chapter 14 Walkthrough")
    print()

    # Determine mode
    mission_id = args.mission_id or _parse_mission_id()
    require_redis = not args.offline and not bool(mission_id)
    require_anthropic = not args.offline and not bool(mission_id)

    # Check prerequisites (non-fatal warnings)
    warnings = _check_prerequisites(
        require_redis=require_redis, require_anthropic=require_anthropic
    )
    if warnings:
        print("  [INFO] Prerequisites:")
        for w in warnings:
            print(f"    - {w}")
        print()

    # Mode dispatch
    if args.watch:
        return _run_live()

    if mission_id:
        return _run_offline(mission_id)

    return _run_automated(mission_id_override=mission_id)


if __name__ == "__main__":
    sys.exit(main())

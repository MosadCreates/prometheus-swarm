"""
Exit test for the trace persister.

Runs a real mission (Titanic, no Dissect, no Harbor) and verifies that
the per-mission trace.jsonl written by the persister matches a
concurrent live capture of the agent_events stream — event for event.

Requires: Docker, redis, ANTHROPIC_API_KEY, prometheus-training-base image.
"""

import asyncio
import json
import os
import subprocess
import uuid

import pytest
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(600)]

from runtime.paths import get_paths, get_job_paths

TITANIC_PATH = str(get_paths().data / "titanic.csv")
TRAINING_IMAGE = "prometheus-training-base"
TEST_CAPTURE_GROUP = "test_trace_capture"


@pytest.fixture(autouse=True)
def require_stack():
    r = subprocess.run(["docker", "images", "-q", TRAINING_IMAGE], capture_output=True, text=True)
    if not r.stdout.strip():
        pytest.skip(f"{TRAINING_IMAGE} not found")
    if not os.path.exists(TITANIC_PATH):
        pytest.skip("data/titanic.csv not found")
    if not os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-ant-"):
        pytest.skip("ANTHROPIC_API_KEY not set")


@pytest.fixture
async def redis():
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    try:
        yield r
    finally:
        await r.aclose()


async def test_trace_persister_matches_live_stream(redis):
    """Diff the trace file against a concurrent capture — they must match exactly."""
    from bus.consumer import ensure_consumer_group
    from bus.events import STREAM_AGENT_EVENTS

    suffix = uuid.uuid4().hex[:8]
    job_id = f"test-trace-{suffix}"

    # ── Set up a separate capture consumer group (start from $, only new events) ─
    try:
        await redis.xgroup_destroy(STREAM_AGENT_EVENTS, TEST_CAPTURE_GROUP)
    except Exception:
        pass
    await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, TEST_CAPTURE_GROUP, start_id="$")

    captured: list[dict] = []

    async def capture_loop():
        consumer_name = f"capture-{suffix}"
        while True:
            try:
                results = await redis.xreadgroup(
                    groupname=TEST_CAPTURE_GROUP,
                    consumername=consumer_name,
                    streams={STREAM_AGENT_EVENTS: ">"},
                    count=100,
                    block=500,
                )
                if not results:
                    continue
                _, messages = results[0]
                for msg_id, raw_fields in messages:
                    msg: dict = {}
                    for k, v in raw_fields.items():
                        try:
                            msg[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            msg[k] = v
                    captured.append(msg)
                    await redis.xack(STREAM_AGENT_EVENTS, TEST_CAPTURE_GROUP, msg_id)
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    capturer = asyncio.create_task(capture_loop())

    try:
        # ── Run the mission (via job_runner, with its internal persister) ─
        from orchestrator.job_runner import run_job, JobConfig

        config = JobConfig(
            job_id=job_id,
            problem_description="Predict passenger survival on the Titanic",
            dataset_path=TITANIC_PATH,
            target_column="Survived",
            task_type="classification",
            modality="tabular",
            evaluation_metric="auc_roc",
            use_dissect=False,
            use_harbor=False,
            use_docker=True,
            timeout_seconds=300,
        )
        result = await run_job(config, redis)
        assert result.status in (
            "pass",
            "crash",
            "escalate",
        ), f"Job failed: status={result.status} detail={result.error_detail}"
    finally:
        capturer.cancel()
        try:
            await capturer
        except (asyncio.CancelledError, Exception):
            pass

    # ── Read the trace file ─────────────────────────────────────────────
    trace_path = get_job_paths(job_id).trace_path
    assert (
        trace_path.exists()
    ), f"Trace file not found at {trace_path}. Did run_job() start the trace persister?"

    raw = trace_path.read_text(encoding="utf-8").strip()
    trace_lines = [raw_line for raw_line in raw.split("\n") if raw_line.strip()]
    assert len(trace_lines) > 0, "Trace file is empty"

    trace_events = [json.loads(line) for line in trace_lines]

    # ── Compare: must match exactly, event for event ────────────────────
    assert len(trace_events) == len(captured), (
        f"Trace file has {len(trace_events)} events but live stream "
        f"capture has {len(captured)} events.\n"
        f"Check that the trace persister and capture consumer both received all events."
    )

    for i, (te, ce) in enumerate(zip(trace_events, captured)):
        assert te["event_id"] == ce["event_id"], (
            f"Event {i} event_id mismatch: "
            f"trace={te.get('event_id', '?')} stream={ce.get('event_id', '?')}"
        )
        assert (
            te["agent"] == ce["agent"]
        ), f"Event {i} agent mismatch: trace={te.get('agent', '?')} stream={ce.get('agent', '?')}"
        assert (
            te["state"] == ce["state"]
        ), f"Event {i} state mismatch: trace={te.get('state', '?')} stream={ce.get('state', '?')}"
        assert te["summary"] == ce["summary"], (
            f"Event {i} summary mismatch:\n"
            f"  trace:  {te.get('summary', '?')}\n"
            f"  stream: {ce.get('summary', '?')}"
        )

    print(f"\nTrace persister: {len(trace_events)} events verified — live = trace (100% match)")

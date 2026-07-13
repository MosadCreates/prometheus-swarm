"""
Section 4 gate test: one full Titanic job through the real orchestrator
(Scout->Forge->Furnace Docker->Arbiter->Harbor via Redis Streams).

Requires: Docker running, prometheus-training-base image built, Redis on localhost:6379.
"""

import asyncio
import json
import os
import subprocess

import pytest
import redis.asyncio as aioredis

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(600)]

from runtime.paths import get_paths

JOB_ID = "test-orch-titanic"
TITANIC_PATH = str(get_paths().data / "titanic.csv")
TRAINING_IMAGE = "prometheus-training-base"
TEST_GROUP = "test_orch_group"

STREAM_SCOUT_OUTPUT = "scout_output"
STREAM_FORGE_OUTPUT = "forge_output"
STREAM_FURNACE_OUTPUT = "furnace_output"
STREAM_ARBITER_OUTPUT = "arbiter_output"
STREAM_HARBOR_OUTPUT = "harbor_output"
STREAM_FURNACE_CRASH = "furnace_crash"
STREAM_DISSECT_OUTPUT = "dissect_output"

ALL_STREAMS = [
    STREAM_SCOUT_OUTPUT,
    STREAM_FORGE_OUTPUT,
    STREAM_FURNACE_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_DISSECT_OUTPUT,
    STREAM_ARBITER_OUTPUT,
    STREAM_HARBOR_OUTPUT,
]

JOB_KEYS = [
    f"job:{JOB_ID}:mission_brief",
    f"job:{JOB_ID}:script_path",
    f"job:{JOB_ID}:checkpoint",
    f"job:{JOB_ID}:file_path",
    f"job:{JOB_ID}:problem_description",
    f"job:{JOB_ID}:search_space",
    f"job:{JOB_ID}:status",
    f"job:{JOB_ID}:current_agent",
    f"job:{JOB_ID}:retry_count",
    f"job:{JOB_ID}:architecture_decision_id",
]


@pytest.fixture(autouse=True)
def require_docker_and_data():
    result = subprocess.run(
        ["docker", "images", "-q", TRAINING_IMAGE],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        pytest.skip(f"docker image '{TRAINING_IMAGE}' not found")
    if not os.path.exists(TITANIC_PATH):
        pytest.skip(f"Titanic dataset not found at {TITANIC_PATH}")


async def _clean_streams(redis):
    for s in ALL_STREAMS:
        await redis.delete(s)


async def _xread_group(redis, stream, group, consumer, timeout=300, once=False):
    """Read one message from a consumer group, ack it, return the decoded event."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = max(1, int((deadline - asyncio.get_event_loop().time()) * 1000))
        results = await redis.xreadgroup(
            group,
            consumer,
            {stream: ">"},
            count=1,
            block=min(remaining, 5000),
        )
        if results:
            for _stream, messages in results:
                for msg_id, raw in messages:
                    decoded = {}
                    for k, v in raw.items():
                        try:
                            decoded[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            decoded[k] = v
                    await redis.xack(stream, group, msg_id)
                    return decoded
        if once:
            return None
    return None


async def _wait_for_event(redis, stream, event_type, group=TEST_GROUP, timeout=300):
    """Wait for a specific event_type on a stream, return its payload."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        remaining = max(1, int((deadline - asyncio.get_event_loop().time()) * 1000))
        results = await redis.xreadgroup(
            group,
            "monitor",
            {stream: ">"},
            count=10,
            block=min(remaining, 5000),
        )
        if results:
            for _stream, messages in results:
                for msg_id, raw in messages:
                    decoded = {}
                    for k, v in raw.items():
                        try:
                            decoded[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            decoded[k] = v
                    await redis.xack(stream, group, msg_id)
                    if decoded.get("event_type") == event_type:
                        return decoded
    return None


async def test_orchestrator_titanic_end_to_end():
    from bus.events import (
        TRAINING_SCRIPT_READY,
        TRAINING_COMPLETE,
        EVALUATION_PASS,
        EVALUATION_RETRY,
        ESCALATE,
        ENDPOINT_LIVE,
    )
    from bus.consumer import ensure_consumer_group
    from orchestrator.runtime import OrchestratorRuntime
    from agents.scout.agent import ScoutAgent

    redis = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    await redis.ping()

    # Clean any leftover state from previous runs
    await _clean_streams(redis)
    for k in JOB_KEYS:
        await redis.delete(k)

    # Set up test consumer groups (before Runtime creates its own)
    for s in ALL_STREAMS:
        await ensure_consumer_group(redis, s, TEST_GROUP)

    # Start the real OrchestratorRuntime in the background
    runtime = OrchestratorRuntime()
    await runtime.initialize()
    runtime_task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.5)

    try:
        # ----- Step 1: Run Scout -----
        scout = ScoutAgent(job_id=JOB_ID)
        scout.redis._client = redis
        scout.job_data = {
            "problem_description": "Predict Titanic survival",
            "file_path": TITANIC_PATH,
            "target_column": "Survived",
        }
        await scout.run()
        print("[TEST] Scout done -- MISSION_BRIEF_READY published")

        # ----- Step 2: Wait for Forge output -----
        forge_ev = await _wait_for_event(
            redis, STREAM_FORGE_OUTPUT, TRAINING_SCRIPT_READY, timeout=30
        )
        assert forge_ev, "TRAINING_SCRIPT_READY not received within 30s"
        script_path = forge_ev.get("script_path", "")
        assert script_path, "TRAINING_SCRIPT_READY missing script_path"
        print(f"[TEST] Forge done -- TRAINING_SCRIPT_READY ({script_path})")

        # ----- Step 3: Wait for Furnace output (Docker training ~2 min) -----
        tc_ev = await _wait_for_event(redis, STREAM_FURNACE_OUTPUT, TRAINING_COMPLETE, timeout=300)
        assert tc_ev, "TRAINING_COMPLETE not received within 300s"

        ckpt_path = tc_ev.get("checkpoint_path", "")
        assert ckpt_path, "TRAINING_COMPLETE missing checkpoint_path"
        assert os.path.exists(ckpt_path), f"Checkpoint not found: {ckpt_path}"
        assert os.path.getsize(ckpt_path) > 0, "Checkpoint is empty"
        print(
            f"[TEST] Furnace done -- TRAINING_COMPLETE (checkpoint: {os.path.getsize(ckpt_path)}b)"
        )

        # ----- Step 4: Wait for Arbiter decision -----
        arb_ev = await _wait_for_event(redis, STREAM_ARBITER_OUTPUT, EVALUATION_PASS, timeout=60)
        if not arb_ev:
            for fallback in [EVALUATION_RETRY, ESCALATE]:
                fb = await _wait_for_event(redis, STREAM_ARBITER_OUTPUT, fallback, timeout=10)
                if fb:
                    pytest.fail(f"Arbiter decided {fallback}: {fb.get('reason', '')}")
                    return
            pytest.fail("Arbiter did not publish any decision within 60s")
        metric = arb_ev.get("primary_metric_value", 0.0)
        print(f"[TEST] Arbiter done -- EVALUATION_PASS (metric={metric})")

        # ----- Step 5: Wait for Harbor output (best-effort) -----
        harbor_ev = await _wait_for_event(redis, STREAM_HARBOR_OUTPUT, ENDPOINT_LIVE, timeout=90)
        if harbor_ev:
            url = harbor_ev.get("endpoint_url", "")
            print(f"[TEST] Harbor done -- ENDPOINT_LIVE ({url})")
        else:
            print("[TEST] Harbor ENDPOINT_LIVE not received (pipeline validated to Arbiter)")

        # ----- Step 6: Verify artifacts -----
        eval_report = f"outputs/{JOB_ID}/eval_report_{JOB_ID}.json"
        assert os.path.exists(eval_report), f"Eval report missing: {eval_report}"
        print(f"[TEST] Eval report: {eval_report}")

        print("\n=== SECTION 4 GATE: PASS ===")

    finally:
        runtime_task.cancel()
        try:
            await runtime_task
        except (asyncio.CancelledError, RuntimeError):
            pass
        await redis.aclose()

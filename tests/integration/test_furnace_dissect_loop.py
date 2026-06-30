"""Integration test for the Furnace↔Dissect crash-recovery loop — the core scientific
contribution of Prometheus Swarm (CLAUDE.md Section 0).

Verifies:
1. Furnace launches a buggy script, it crashes, CRASH_EVENT is published
2. Dissect consumes the crash, classifies the error, generates a patch
3. Dissect runs the patched script in a sandbox, verifies it passes
4. Dissect publishes RESUME_TRAINING and writes to patch_log_queue
5. Furnace consumes RESUME_TRAINING, retries with the patched script

Requires Anthropic API key for the LLM-powered Dissect agent.
"""

import asyncio
import json
import os
import shutil
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(120)]

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

JOB_ID = "test-furnace-dissect-loop"
FIXTURE_SRC = os.path.join(
    os.path.dirname(__file__),
    "../fixtures/injected_errors/03_missing_column.py",
)
SCRIPT_PATH = f"scripts/training_script_{JOB_ID}.py"
CHECKPOINT_DIR = f"outputs/{JOB_ID}/checkpoints"
CHECKPOINT_PATH = f"{CHECKPOINT_DIR}/best.ckpt"


def _check_api_key():
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — requires LLM call")


async def _setup():
    os.makedirs("scripts", exist_ok=True)
    shutil.copy2(FIXTURE_SRC, SCRIPT_PATH)
    os.makedirs(CHECKPOINT_DIR, exist_ok=True)
    with open(CHECKPOINT_PATH, "w") as f:
        f.write("dummy-checkpoint")


async def _cleanup():
    for p in [SCRIPT_PATH, SCRIPT_PATH + ".bak", CHECKPOINT_PATH]:
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists(CHECKPOINT_DIR):
        os.rmdir(CHECKPOINT_DIR)


async def test_furnace_dissect_crash_recovery():
    _check_api_key()
    await _setup()

    import redis.asyncio as aioredis
    from bus.consumer import ensure_consumer_group
    from bus.events import (
        RESUME_TRAINING,
        STREAM_FURNACE_CRASH,
        STREAM_DISSECT_OUTPUT,
        STREAM_FURNACE_OUTPUT,
        GROUP_DISSECT,
        GROUP_FURNACE,
    )
    from agents.furnace.agent import FurnaceAgent
    from agents.dissect.agent import DissectAgent
    from memory.redis_client import RedisClient

    redis = aioredis.Redis(
        host="localhost", port=6379, decode_responses=True,
    )

    # Ensure consumer groups before any messages are published
    for stream, group in [
        (STREAM_FURNACE_CRASH, GROUP_DISSECT),
        (STREAM_DISSECT_OUTPUT, GROUP_FURNACE),
        (STREAM_FURNACE_OUTPUT, "arbiter_consumers"),
    ]:
        await ensure_consumer_group(redis, stream, group)

    furnace_task = None
    try:
        # --- Launch Furnace in background ---
        furnace = FurnaceAgent(job_id=JOB_ID)
        furnace.redis = RedisClient()
        furnace.redis._client = redis

        furnace_task = asyncio.create_task(
            furnace.run(script_path=SCRIPT_PATH, use_docker=False)
        )

        await asyncio.sleep(1)

        # --- Consume CRASH_EVENT ---
        crash_event = None
        for _ in range(6):
            results = await redis.xreadgroup(
                GROUP_DISSECT,
                "test-dissect",
                {STREAM_FURNACE_CRASH: ">"},
                count=1,
                block=5000,
            )
            if results:
                for _stream, messages in results:
                    for msg_id, data in messages:
                        if data.get("job_id") == JOB_ID:
                            crash_event = dict(data)
                            crash_event["_msg_id"] = msg_id
                            break
                    if crash_event:
                        break
            if crash_event:
                break

        assert crash_event, "No CRASH_EVENT received within 30s"
        etype = crash_event.get("exception_type", "")
        assert etype == "RuntimeError", (
            f"Expected RuntimeError, got: {etype}"
        )
        assert crash_event.get("crash_attempt_number") in ("1", 1)

        await redis.xack(
            STREAM_FURNACE_CRASH,
            GROUP_DISSECT,
            crash_event["_msg_id"],
        )

        # --- Have Dissect handle the crash ---
        dissect = DissectAgent(job_id=JOB_ID)
        dissect.redis = RedisClient()
        dissect.redis._client = redis

        await dissect.handle_crash(crash_event)

        # --- Verify RESUME_TRAINING was published ---
        resume_event = None
        for _ in range(12):
            results = await redis.xreadgroup(
                GROUP_FURNACE,
                "test-furnace",
                {STREAM_DISSECT_OUTPUT: ">"},
                count=1,
                block=5000,
            )
            if results:
                for _stream, messages in results:
                    for msg_id, data in messages:
                        decoded = {}
                        for k, v in data.items():
                            try:
                                decoded[k] = json.loads(v)
                            except (json.JSONDecodeError, TypeError):
                                decoded[k] = v
                        if decoded.get("job_id") == JOB_ID and (
                            decoded.get("event_type") == RESUME_TRAINING
                        ):
                            resume_event = decoded
                            await redis.xack(
                                STREAM_DISSECT_OUTPUT,
                                GROUP_FURNACE,
                                msg_id,
                            )
                            break
                    if resume_event:
                        break
            if resume_event:
                break

        assert resume_event, (
            "Dissect did not publish RESUME_TRAINING within 60s"
        )
        assert resume_event.get("job_id") == JOB_ID
        assert (
            resume_event.get("patched_script_path") == SCRIPT_PATH
        ), f"Expected {SCRIPT_PATH}, got {resume_event.get('patched_script_path')}"
        assert resume_event.get("patch_id"), (
            "RESUME_TRAINING should include patch_id"
        )

        # --- Verify the bug was fixed in the script ---
        with open(SCRIPT_PATH) as f:
            content = f.read()
        assert "Age_log" in content, (
            "Patched script should contain Age_log column derivation"
        )
        assert (
            "np.log" in content
            or "np.log10" in content
            or "np.log1p" in content
        ), "Patched script should use a log transform for Age_log"

        # --- Wait for Furnace to complete ---
        try:
            await asyncio.wait_for(furnace_task, timeout=60)
        except asyncio.TimeoutError:
            pytest.fail(
                "Furnace task did not complete within 60s after patch"
            )

        # --- Verify TRAINING_COMPLETE was published ---
        tc_event = None
        for _ in range(5):
            results = await redis.xreadgroup(
                "arbiter_consumers",
                "test-arbiter",
                {STREAM_FURNACE_OUTPUT: ">"},
                count=1,
                block=2000,
            )
            if results:
                for _stream, messages in results:
                    for msg_id, data in messages:
                        if data.get("job_id") == JOB_ID:
                            tc_event = dict(data)
                            await redis.xack(
                                STREAM_FURNACE_OUTPUT,
                                "arbiter_consumers",
                                msg_id,
                            )
                            break
                    if tc_event:
                        break
            if tc_event:
                break

        assert tc_event, "TRAINING_COMPLETE was not published"
        assert tc_event.get("event_type") == "TRAINING_COMPLETE"

        # --- Verify patch_log_queue has a success entry for this patch ---
        patch_id_to_find = resume_event.get("patch_id", "")
        found_match = False
        for _ in range(10):
            result = await redis.blpop("patch_log_queue", timeout=3)
            if result is None:
                break
            _list_key, log_entry_raw = result
            log_entry = json.loads(log_entry_raw)
            if log_entry.get("patch_id") == patch_id_to_find:
                assert log_entry.get("patch_outcome") == "success", (
                    f"Expected patch_outcome=success, got: {log_entry.get('patch_outcome')}"
                )
                found_match = True
                break
        assert found_match, (
            f"No patch_log entry found matching patch_id={patch_id_to_find}"
        )

    finally:
        if furnace_task:
            furnace_task.cancel()
            try:
                await furnace_task
            except (asyncio.CancelledError, RuntimeError):
                pass
        await redis.delete("patch_log_queue")
        for key in [
            f"job:{JOB_ID}:mission_brief",
            f"job:{JOB_ID}:script_path",
            f"job:{JOB_ID}:checkpoint",
            f"job:{JOB_ID}:file_path",
            f"job:{JOB_ID}:problem_description",
        ]:
            await redis.delete(key)
        for stream in [
            STREAM_FURNACE_CRASH,
            STREAM_DISSECT_OUTPUT,
            STREAM_FURNACE_OUTPUT,
        ]:
            await redis.delete(stream)
        await redis.aclose()
        await _cleanup()

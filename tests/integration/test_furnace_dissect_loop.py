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

import pytest
from dotenv import load_dotenv

load_dotenv()

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
    import pickle

    with open(CHECKPOINT_PATH, "wb") as f:
        pickle.dump({"best_metric": 0.0, "epoch": 0, "best_val_metric": 0.0}, f)

    import redis.asyncio as aioredis

    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    keys = await r.keys(f"job:{JOB_ID}:*")
    for k in keys:
        await r.delete(k)
    for key in [
        "furnace_crash_stream",
        "dissect_output_stream",
        "furnace_output_stream",
        "patch_log_queue",
    ]:
        await r.delete(key)
    await r.aclose()


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

    test_redis = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    furnace_redis = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )
    dissect_redis = aioredis.Redis(
        host="localhost",
        port=6379,
        decode_responses=True,
    )

    for stream, group in [
        (STREAM_FURNACE_CRASH, GROUP_DISSECT),
        (STREAM_DISSECT_OUTPUT, GROUP_FURNACE),
        (STREAM_FURNACE_OUTPUT, "arbiter_consumers"),
    ]:
        await ensure_consumer_group(furnace_redis, stream, group)

    furnace_task = None
    try:
        furnace = FurnaceAgent(job_id=JOB_ID)
        furnace.redis = RedisClient()
        furnace.redis._client = furnace_redis

        furnace_task = asyncio.create_task(furnace.run(script_path=SCRIPT_PATH, use_docker=False))

        await asyncio.sleep(1)

        crash_event = None
        for _ in range(6):
            results = await test_redis.xreadgroup(
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
        assert etype == "RuntimeError", f"Expected RuntimeError, got: {etype}"
        assert crash_event.get("crash_attempt_number") in ("1", 1)

        await test_redis.xack(
            STREAM_FURNACE_CRASH,
            GROUP_DISSECT,
            crash_event["_msg_id"],
        )

        dissect = DissectAgent(job_id=JOB_ID)
        dissect.redis = RedisClient()
        dissect.redis._client = dissect_redis

        await dissect.handle_crash(crash_event)

        # Direct rpush test via dissect's resources
        import json as _json

        await dissect.redis.rpush("patch_log_queue", _json.dumps({"test": "direct"}))
        _qlen = await dissect_redis.llen("patch_log_queue")
        _qtype = await dissect_redis.type("patch_log_queue")
        _items = await dissect_redis.lrange("patch_log_queue", 0, -1)
        print(f"\n[POST_HANDLE] dissect_redis.llen={_qlen} type={_qtype} items={_items}")
        _test_rpush = await dissect_redis.rpush("patch_log_queue", _json.dumps({"raw": True}))
        _qlen2 = await dissect_redis.llen("patch_log_queue")
        print(
            f"[POST_HANDLE] raw rpush result={_test_rpush} llen={_qlen2} items={await dissect_redis.lrange('patch_log_queue', 0, -1)}"
        )

        resume_event = None
        for _ in range(12):
            results = await test_redis.xreadgroup(
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
                            await test_redis.xack(
                                STREAM_DISSECT_OUTPUT,
                                GROUP_FURNACE,
                                msg_id,
                            )
                            break
                    if resume_event:
                        break
            if resume_event:
                break

        assert resume_event, "Dissect did not publish RESUME_TRAINING within 60s"
        assert resume_event.get("job_id") == JOB_ID
        assert (
            resume_event.get("patched_script_path") == SCRIPT_PATH
        ), f"Expected {SCRIPT_PATH}, got {resume_event.get('patched_script_path')}"
        assert resume_event.get("patch_id"), "RESUME_TRAINING should include patch_id"

        with open(SCRIPT_PATH) as f:
            content = f.read()
        assert "Age_log" in content, "Patched script should contain Age_log column derivation"
        assert (
            "np.log" in content or "np.log10" in content or "np.log1p" in content
        ), "Patched script should use a log transform for Age_log"

        try:
            await asyncio.wait_for(furnace_task, timeout=60)
        except asyncio.TimeoutError:
            pytest.fail("Furnace task did not complete within 60s after patch")

        tc_event = None
        for _ in range(5):
            results = await test_redis.xreadgroup(
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
                            await test_redis.xack(
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

        patch_id_to_find = resume_event.get("patch_id", "")
        found_match = False
        patch_log_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "../../research/patch_log.jsonl")
        )
        for _ in range(10):
            result = await test_redis.blpop("patch_log_queue", timeout=3)
            if result is None:
                break
            _list_key, log_entry_raw = result
            log_entry = json.loads(log_entry_raw)
            if log_entry.get("patch_id") == patch_id_to_find:
                assert (
                    log_entry.get("patch_outcome") == "success"
                ), f"Expected patch_outcome=success, got: {log_entry.get('patch_outcome')}"
                found_match = True
                os.makedirs(os.path.dirname(patch_log_path), exist_ok=True)
                with open(patch_log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, separators=(",", ":")) + "\n")
                break
        assert found_match, f"No patch_log entry found matching patch_id={patch_id_to_find}"

        while True:
            result = await test_redis.blpop("patch_log_queue", timeout=1)
            if result is None:
                break
            _list_key, log_entry_raw = result
            with open(patch_log_path, "a", encoding="utf-8") as f:
                f.write(log_entry_raw + "\n")

    finally:
        if furnace_task:
            furnace_task.cancel()
            try:
                await furnace_task
            except (asyncio.CancelledError, RuntimeError):
                pass
        for r_client in [test_redis, furnace_redis, dissect_redis]:
            keys = await r_client.keys(f"job:{JOB_ID}:*")
            for key in keys:
                await r_client.delete(key)
            for stream_key in [
                "patch_log_queue",
                STREAM_FURNACE_CRASH,
                STREAM_DISSECT_OUTPUT,
                STREAM_FURNACE_OUTPUT,
            ]:
                await r_client.delete(stream_key)
            await r_client.aclose()
        await _cleanup()

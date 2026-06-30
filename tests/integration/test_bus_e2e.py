"""Tests that all event types can be published and consumed end-to-end through Redis Streams. Phase 0 gate test."""

import asyncio
import json
import pytest
import redis.asyncio as aioredis

from bus.events import (
    MISSION_BRIEF_READY, TRAINING_SCRIPT_READY, EPOCH_COMPLETE,
    TRAINING_COMPLETE, CRASH_EVENT, RESUME_TRAINING,
    EVALUATION_PASS, EVALUATION_RETRY, ESCALATE, ENDPOINT_LIVE, DRIFT_ALERT,
    STREAM_SCOUT_OUTPUT, GROUP_FORGE,
)
from bus.publisher import publish
from bus.consumer import ensure_consumer_group, consume_one


@pytest.fixture
async def redis():
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    yield r
    for stream in ["test_stream_e2e"]:
        await r.delete(stream)
    await r.aclose()


@pytest.mark.asyncio
async def test_publish_and_consume_roundtrip(redis):
    stream = "test_stream_e2e"
    group = "test_group"

    await ensure_consumer_group(redis, stream, group)

    payload = {
        "job_id": "test-job-001",
        "mission_brief_redis_key": "job:test-job-001:mission_brief",
    }
    msg_id = await publish(redis, stream, MISSION_BRIEF_READY, payload)
    assert msg_id is not None

    received = {}

    async def handler(message):
        received.update(message)

    await consume_one(redis, stream, group, "test-consumer", handler, block_ms=1000)

    assert received["event_type"] == MISSION_BRIEF_READY
    assert received["job_id"] == "test-job-001"
    assert "timestamp" in received


@pytest.mark.asyncio
async def test_all_event_types_are_publishable(redis):
    stream = "test_stream_all_events"
    await redis.delete(stream)

    events = [
        (MISSION_BRIEF_READY, {"job_id": "j1", "mission_brief_redis_key": "k"}),
        (TRAINING_SCRIPT_READY, {"job_id": "j1", "script_path": "s.py", "search_space_redis_key": "k"}),
        (EPOCH_COMPLETE, {"job_id": "j1", "epoch": 1, "train_loss": 0.5, "val_loss": 0.6, "eta_seconds": 100}),
        (TRAINING_COMPLETE, {"job_id": "j1", "checkpoint_path": "/c", "best_val_metric": 0.9, "total_epochs": 10, "total_crashes_recovered": 0}),
        (CRASH_EVENT, {"job_id": "j1", "exception_type": "ValueError", "exception_message": "test", "traceback": "tb", "script_path": "s.py", "last_checkpoint_path": None, "epoch_at_crash": 2, "crash_attempt_number": 1}),
        (RESUME_TRAINING, {"job_id": "j1", "patched_script_path": "s.py", "resume_from_checkpoint": None, "patch_id": "pid"}),
        (EVALUATION_PASS, {"job_id": "j1", "eval_report_path": "/r", "primary_metric": "auc_roc", "primary_metric_value": 0.91}),
        (EVALUATION_RETRY, {"job_id": "j1", "eval_report_path": "/r", "reason": "below threshold"}),
        (ESCALATE, {"job_id": "j1", "source_agent": "Dissect", "reason": "3 failures", "diagnostic_report_path": "/d"}),
        (ENDPOINT_LIVE, {"job_id": "j1", "endpoint_url": "http://x", "val_metric": 0.9, "p95_latency_ms": 12.0, "model_format": "onnx"}),
        (DRIFT_ALERT, {"job_id": "j1", "psi_score": 0.25, "psi_threshold": 0.2, "window_size": 1000}),
    ]

    for event_type, payload in events:
        msg_id = await publish(redis, stream, event_type, payload)
        assert msg_id is not None, f"Failed to publish {event_type}"

    messages = await redis.xrange(stream)
    assert len(messages) == 11

    # Verify None fields are serialized as empty string, not "None"
    crash_msg = [m for m in messages if m[1].get("event_type") == CRASH_EVENT][0]
    raw_last_cp = crash_msg[1].get("last_checkpoint_path", "MISSING")
    assert raw_last_cp == "", f"Expected empty string for None field, got: {raw_last_cp!r}"

    await redis.delete(stream)

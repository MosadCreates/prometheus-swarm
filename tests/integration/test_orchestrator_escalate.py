"""Integration tests for orchestator ESCALATE handling — diagnostic report + container kill.

These tests verify the ESCALATE resolution path defined in CLAUDE.md §14:
1. Diagnostic report is written to outputs/{job_id}/diagnostic_{job_id}.json
2. JOB_FAILED is published to orchestrator_output stream
3. Training container is killed via DockerManager

Since ESCALATE requires Redis, tests that need Redis are marked with @pytest.mark.skipif.
Container-kill assertions use mocked DockerManager to avoid requiring Docker daemon.
"""

import json
import os
import shutil
import sys
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


JOB_ID = "test-escalate-job"
DIAGNOSTIC_PATH = f"outputs/{JOB_ID}/diagnostic_{JOB_ID}.json"


def _cleanup():
    diag_dir = f"outputs/{JOB_ID}"
    if os.path.exists(diag_dir):
        shutil.rmtree(diag_dir)


@pytest.fixture(autouse=True)
def cleanup():
    _cleanup()
    yield
    _cleanup()


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_handle_escalate_writes_diagnostic_report():
    """Orchestrator._handle_escalate writes diagnostic_{job_id}.json."""
    from orchestrator.runtime import OrchestratorRuntime

    runtime = OrchestratorRuntime()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"123-0")
    runtime.redis = mock_redis

    mock_docker = MagicMock()
    mock_docker.kill_container = AsyncMock()

    with patch("training.docker_manager.DockerManager", return_value=mock_docker):
        await runtime._handle_escalate(
            job_id=JOB_ID,
            source="Dissect",
            reason="3 patch attempts failed",
        )

    assert os.path.exists(DIAGNOSTIC_PATH), f"Diagnostic file not found at {DIAGNOSTIC_PATH}"
    with open(DIAGNOSTIC_PATH) as f:
        report = json.load(f)
    assert report["job_id"] == JOB_ID
    assert report["source_agent"] == "Dissect"
    assert report["reason"] == "3 patch attempts failed"
    assert report["escalated"] is True


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_handle_escalate_sets_redis_status():
    """Orchestrator._handle_escalate sets job status to MISSION_FAILED via state machine."""
    from orchestrator.runtime import OrchestratorRuntime

    runtime = OrchestratorRuntime()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"123-0")
    runtime.redis = mock_redis

    mock_docker = MagicMock()
    mock_docker.kill_container = AsyncMock()

    with patch("training.docker_manager.DockerManager", return_value=mock_docker):
        await runtime._handle_escalate(
            job_id=JOB_ID,
            source="Arbiter",
            reason="AUC too low",
        )

    # Verify mission_state key was written (state machine contract)
    state_calls = [
        c for c in mock_redis.set.call_args_list if c[0][0] == f"job:{JOB_ID}:mission_state"
    ]
    assert len(state_calls) >= 1
    assert "MISSION_FAILED" in str(state_calls[-1][0][1])

    # Verify backward-compat status key was also written
    status_calls = [c for c in mock_redis.set.call_args_list if c[0][0] == f"job:{JOB_ID}:status"]
    assert len(status_calls) >= 1
    assert "MISSION_FAILED" in str(status_calls[-1][0][1])


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_handle_escalate_publishes_job_failed():
    """Orchestrator._handle_escalate publishes JOB_FAILED to orchestrator_output."""
    from orchestrator.runtime import OrchestratorRuntime
    from bus.events import JOB_FAILED, STREAM_ORCHESTRATOR_OUT

    runtime = OrchestratorRuntime()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"123-0")
    runtime.redis = mock_redis

    mock_docker = MagicMock()
    mock_docker.kill_container = AsyncMock()

    with patch("training.docker_manager.DockerManager", return_value=mock_docker):
        await runtime._handle_escalate(
            job_id=JOB_ID,
            source="Dissect",
            reason="3 patch attempts failed",
        )

    xadd_calls = [c for c in mock_redis.xadd.call_args_list]
    found = False
    for call in xadd_calls:
        stream = call[0][0]
        fields = call[0][1]
        if stream == STREAM_ORCHESTRATOR_OUT and "event_type" in fields:
            if fields["event_type"] == JOB_FAILED:
                found = True
                break
    assert found, "JOB_FAILED was not published to orchestrator_output"


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_handle_escalate_calls_docker_kill():
    """Orchestrator._handle_escalate kills the training Docker container."""
    from orchestrator.runtime import OrchestratorRuntime

    runtime = OrchestratorRuntime()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"123-0")
    runtime.redis = mock_redis

    mock_docker_manager = MagicMock()
    mock_docker_manager.kill_container = AsyncMock()

    with patch(
        "training.docker_manager.DockerManager", return_value=mock_docker_manager
    ) as mock_dm_cls:
        await runtime._handle_escalate(
            job_id=JOB_ID,
            source="Furnace",
            reason="Container crashed",
        )

    mock_dm_cls.assert_called_once()
    mock_docker_manager.kill_container.assert_awaited_once_with(JOB_ID)


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_on_escalate_delegates_to_handle_escalate():
    """Orchestrator._on_escalate extracts fields and delegates to _handle_escalate."""
    from orchestrator.runtime import OrchestratorRuntime

    runtime = OrchestratorRuntime()
    runtime._handle_escalate = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    runtime.redis = mock_redis

    await runtime._on_escalate(
        {
            "job_id": JOB_ID,
            "source_agent": "Dissect",
            "reason": "All patches failed",
        }
    )

    runtime._handle_escalate.assert_awaited_once_with(JOB_ID, "Dissect", "All patches failed")


@pytest.mark.asyncio
@pytest.mark.timeout(15)
async def test_docker_kill_failure_does_not_block_escalate():
    """Docker kill failure is logged but does not block the ESCALATE flow."""
    from orchestrator.runtime import OrchestratorRuntime

    runtime = OrchestratorRuntime()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.xgroup_create = AsyncMock()
    mock_redis.set = AsyncMock()
    mock_redis.xadd = AsyncMock(return_value=b"123-0")
    runtime.redis = mock_redis

    mock_docker_manager = MagicMock()
    mock_docker_manager.kill_container = AsyncMock(side_effect=Exception("Container not found"))

    with patch("training.docker_manager.DockerManager", return_value=mock_docker_manager):
        try:
            await runtime._handle_escalate(
                job_id=JOB_ID,
                source="Arbiter",
                reason="Metrics too low",
            )
        except Exception:
            pytest.fail("Docker kill failure should not raise in _handle_escalate")

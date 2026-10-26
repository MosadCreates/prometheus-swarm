"""Unit tests for the Dissect sandbox pass/fail policy (Week-1 hardening).

Verifies the corrected run_sandbox_test behavior:
- clean exit 0 -> PASS
- nonzero exit -> FAIL
- timeout WITH observable training progress -> PASS (patch cleared the crash point)
- timeout WITHOUT any progress -> FAIL (suspected infinite loop must not pass)
"""

from unittest.mock import MagicMock, patch

import pytest


def _make_container(wait_side_effect, logs_bytes=b""):
    """Build a mock docker container with scripted wait()/logs() behavior."""
    container = MagicMock()
    container.wait = MagicMock(side_effect=wait_side_effect)
    container.logs = MagicMock(return_value=logs_bytes)
    container.kill = MagicMock()
    container.remove = MagicMock()
    return container


async def _run_sandbox(container):
    from agents.dissect.tools import run_sandbox_test

    client = MagicMock()
    client.containers.run = MagicMock(return_value=container)
    with (
        patch("docker.from_env", return_value=client),
        patch("agents.dissect.tools._validate_sandbox_env", return_value=None),
    ):
        return await run_sandbox_test("scripts/dummy.py", "job-sbx-test")


@pytest.mark.asyncio
async def test_exit_zero_passes():
    container = _make_container(lambda **kw: {"StatusCode": 0}, b"AUC: 0.9\nTRAINING_COMPLETE\n")
    passed, output = await _run_sandbox(container)
    assert passed is True
    assert "TRAINING_COMPLETE" in output


@pytest.mark.asyncio
async def test_nonzero_exit_fails():
    container = _make_container(lambda **kw: {"StatusCode": 1}, b"Traceback...\n")
    passed, output = await _run_sandbox(container)
    assert passed is False


@pytest.mark.asyncio
async def test_timeout_with_progress_passes():
    """Timeout AFTER the script proved it entered training → patch accepted."""
    container = _make_container(
        lambda **kw: (_ for _ in ()).throw(TimeoutError("wait deadline")),
        b"[10] valid's auc: 0.812\n",
    )
    passed, output = await _run_sandbox(container)
    assert passed is True
    assert "training progress was observed" in output


@pytest.mark.asyncio
async def test_timeout_with_json_progress_passes():
    container = _make_container(
        lambda **kw: (_ for _ in ()).throw(TimeoutError("wait deadline")),
        b'{"type": "progress", "epoch": 2}\n',
    )
    passed, _ = await _run_sandbox(container)
    assert passed is True


@pytest.mark.asyncio
async def test_timeout_silent_fails_as_suspected_hang():
    """The core Week-1 fix: a hang with NO output must FAIL, not pass."""
    container = _make_container(
        lambda **kw: (_ for _ in ()).throw(TimeoutError("wait deadline")),
        b"",
    )
    passed, output = await _run_sandbox(container)
    assert passed is False
    assert "suspected hang" in output


@pytest.mark.asyncio
async def test_timeout_with_only_startup_noise_fails():
    container = _make_container(
        lambda **kw: (_ for _ in ()).throw(TimeoutError("wait deadline")),
        b"Loading dataset...\nImporting lightgbm...\n",
    )
    passed, _ = await _run_sandbox(container)
    assert passed is False

"""Test that CRASH_EVENT.last_checkpoint_path is empty string when no checkpoint exists."""
import sys
sys.path.insert(0, ".")

from unittest.mock import AsyncMock, patch

import pytest

from agents.furnace.agent import FurnaceAgent


@pytest.mark.asyncio
async def test_last_checkpoint_path_is_empty_when_no_checkpoint():
    agent = FurnaceAgent(job_id="test-no-checkpoint")

    agent.redis._client = AsyncMock()
    agent.redis._client.xread = AsyncMock(return_value=[])

    captured_payload = {}

    async def fake_publish(_redis, _stream, _event_type, payload):
        captured_payload.update(payload)

    with patch("agents.furnace.agent.os.path.exists", return_value=False), \
         patch("agents.furnace.agent.publish", new=fake_publish):

        result = await agent._handle_crash(
            error=ValueError("test error"),
            script_path="nonexistent.py",
            attempt_number=1,
        )

    assert result is None
    assert captured_payload.get("last_checkpoint_path") == "", \
        f"Expected empty string, got: {captured_payload.get('last_checkpoint_path')!r}"
    assert captured_payload.get("crash_attempt_number") == 1
    assert captured_payload.get("exception_type") == "ValueError"

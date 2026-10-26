"""Regression test: Furnace must emit an authoritative final epoch-detail
BEFORE its `done` event, so the stream renderer never finalizes on a stale
mid-training snapshot.

The bug (fixed): epoch-progress details were emitted as fire-and-forget
`asyncio.create_task` background tasks racing the awaited `done` event. If
`done` landed in the `agent_events` stream first, the renderer finalized on
whatever the last in-order epoch event showed (e.g. ``best=0.7961
epoch=5/100``) even though training completed all 100 epochs.

Fix contract (verified here): `_emit_epoch_detail` is AWAITED with the final
epoch count and best metric immediately before `done` is emitted.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agents.furnace.agent import FurnaceAgent


@pytest.mark.asyncio
async def test_run_emits_final_epoch_before_done():
    agent = FurnaceAgent(job_id="test-final-epoch")
    agent.redis._client = AsyncMock()
    agent._epoch_count = 100
    agent._best_val_metric = 0.8295

    emitted_epochs: list[dict] = []
    done_calls: list[tuple] = []
    order: list[str] = []

    async def fake_emit_epoch_detail(self, **kwargs):
        # `self` is bound positionally (patched class method), remaining
        # args are the call's keyword args.
        emitted_epochs.append(kwargs)
        order.append("epoch")

    async def fake_done(summary, detail=None):
        done_calls.append((summary, detail))
        order.append("done")

    fake_tracker = AsyncMock()
    fake_tracker.done = fake_done

    jp = SimpleNamespace(
        checkpoint_path=Path("/tmp/checkpoints/best.ckpt"),
        job_dir=Path("/tmp/job"),
    )

    with (
        patch("agents.furnace.agent.get_job_paths", return_value=jp),
        patch("agents.furnace.agent.log_mission_state"),
        patch("agents.furnace.agent.AgentEventTracker", return_value=fake_tracker),
        patch.object(FurnaceAgent, "_launch_and_monitor_docker", new=AsyncMock()),
        patch.object(FurnaceAgent, "_finalize_training", new=AsyncMock()),
        patch.object(FurnaceAgent, "_emit_epoch_detail", new=fake_emit_epoch_detail),
    ):
        await agent.run(script_path="script.py", use_docker=True)

    assert order == ["epoch", "done"], (
        "The final epoch detail must land in the stream BEFORE the done event; "
        f"actual order: {order}"
    )

    assert emitted_epochs, "A final epoch detail must be emitted before done"
    final_epoch = emitted_epochs[-1]
    assert final_epoch["epoch"] == 100
    assert final_epoch["total_epochs"] == 100
    assert final_epoch["metric_value"] == 0.8295
    assert final_epoch["best_score"] == 0.8295
    assert final_epoch["max_epochs"] == 100

    assert done_calls, "done must be emitted"
    assert done_calls[0][0] == "Training complete"
    done_detail = done_calls[0][1] or {}
    assert done_detail.get("best_metric") == 0.8295
    assert done_detail.get("epochs") == 100


@pytest.mark.asyncio
async def test_run_skips_final_epoch_when_no_epochs_ran():
    """A zero-epoch run still completes cleanly (no false final detail)."""
    agent = FurnaceAgent(job_id="test-zero-epochs")
    agent.redis._client = AsyncMock()
    agent._epoch_count = 0
    agent._best_val_metric = 0.0

    emitted_epochs: list[dict] = []
    done_calls: list[tuple] = []

    async def fake_emit_epoch_detail(self, **kwargs):
        emitted_epochs.append(kwargs)

    async def fake_done(summary, detail=None):
        done_calls.append((summary, detail))

    fake_tracker = AsyncMock()
    fake_tracker.done = fake_done

    jp = SimpleNamespace(
        checkpoint_path=Path("/tmp/checkpoints/best.ckpt"),
        job_dir=Path("/tmp/job"),
    )

    with (
        patch("agents.furnace.agent.get_job_paths", return_value=jp),
        patch("agents.furnace.agent.log_mission_state"),
        patch("agents.furnace.agent.AgentEventTracker", return_value=fake_tracker),
        patch.object(FurnaceAgent, "_launch_and_monitor_docker", new=AsyncMock()),
        patch.object(FurnaceAgent, "_finalize_training", new=AsyncMock()),
        patch.object(FurnaceAgent, "_emit_epoch_detail", new=fake_emit_epoch_detail),
    ):
        await agent.run(script_path="script.py", use_docker=True)

    assert emitted_epochs == [], "No final epoch detail should be emitted"
    assert done_calls and done_calls[0][0] == "Training complete"
    assert (done_calls[0][1] or {}).get("epochs") == 0

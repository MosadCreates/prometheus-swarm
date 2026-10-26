"""Regression tests for Furnace epoch counting.

Bug fixed: the final rendered Furnace line showed ``=best=0.8354  epoch=102/102``
when the run only trained 100 epochs. Root cause: the direct-metric parser
counted the post-training summary lines (``Accuracy:`` / ``AUC:`` / ``RMSE:``)
printed by the tabular templates as extra epochs on top of the 100 ``[N]``
LightGBM/XGBoost iteration lines.

Fix contract (verified here):
  1. ``[N]`` iteration lines are the authoritative per-epoch source; the count
     is the max iteration number seen, never inflated by later summary lines.
  2. JSON ``epoch_complete`` lines are likewise authoritative and record
     ``max_epochs``.
  3. A bare metric line (``Accuracy:`` / ``AUC:`` / ``RMSE:``) mints an epoch
     ONLY when no authoritative source has been seen yet (the fallback signal
     for the multiclass/regression templates that emit no iteration lines).
"""

from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from unittest.mock import AsyncMock

import pytest

from agents.furnace.agent import FurnaceAgent


@pytest.mark.asyncio
async def test_lightgbm_iterations_plus_summary_lines_stay_at_true_max():
    """100 real iteration lines + 2 post-training summaries -> count 100, not 102."""
    agent = FurnaceAgent(job_id="epoch-binary")
    agent.redis._client = AsyncMock()

    for n in range(1, 101):
        agent._on_training_log(
            f"[{n}]\tvalid_0's auc: {0.7 + n / 1000:.6f}\tvalid_0's binary_logloss: 0.5"
        )
    # Post-training summary lines (the bug: these used to push the count to 102).
    agent._on_training_log("Accuracy: 0.7989")
    agent._on_training_log("AUC: 0.8279")
    await asyncio.sleep(0.05)

    assert agent._epoch_count == 100, f"expected 100, got {agent._epoch_count}"
    assert agent._max_epochs == 100, f"expected 100, got {agent._max_epochs}"
    assert agent._epoch_source == "iter"


@pytest.mark.asyncio
async def test_early_stopped_iterations_count_to_last_iteration():
    """A run that stops at iteration 40 reports 40, not 40 + summary lines."""
    agent = FurnaceAgent(job_id="epoch-early-stop")
    agent.redis._client = AsyncMock()

    for n in range(1, 41):
        agent._on_training_log(f"[{n}]\tvalid_0's auc: {0.7 + n / 1000:.6f}")
    agent._on_training_log("Accuracy: 0.79")
    agent._on_training_log("AUC: 0.81")
    await asyncio.sleep(0.05)

    assert agent._epoch_count == 40
    assert agent._max_epochs == 40
    assert agent._epoch_source == "iter"


@pytest.mark.asyncio
async def test_multiclass_single_summary_is_fallback_epoch():
    """Multiclass/regression templates print no iteration lines; the single
    summary line remains the fallback epoch signal (count = 1)."""
    agent = FurnaceAgent(job_id="epoch-multiclass")
    agent.redis._client = AsyncMock()

    agent._on_training_log("Accuracy: 0.9103")
    await asyncio.sleep(0.05)

    assert agent._epoch_count == 1
    assert agent._max_epochs == 1
    assert agent._epoch_source is None


@pytest.mark.asyncio
async def test_json_progress_is_authoritative_and_summary_does_not_inflate():
    """JSON epoch_complete (distilbert/efficientnet/tabnet) is authoritative:
    the per-epoch Accuracy lines printed alongside must not mint extra epochs."""
    agent = FurnaceAgent(job_id="epoch-json")
    agent.redis._client = AsyncMock()

    for epoch in range(1, 4):
        agent._on_training_log(f"Epoch {epoch}/3 | Train loss: 0.5")
        agent._on_training_log(f"Accuracy: {0.9 + epoch / 100:.4f}")
        agent._on_training_log(
            '{"type":"progress","epoch":%d,"max_epochs":3,"metric":"accuracy","value":%s}'
            % (epoch, 0.9 + epoch / 100)
        )
    await asyncio.sleep(0.05)

    assert agent._epoch_count == 3, f"expected 3, got {agent._epoch_count}"
    assert agent._max_epochs == 3
    assert agent._epoch_source == "json"


@pytest.mark.asyncio
async def test_xgboost_iterations_starting_at_zero():
    """XGBoost logs ``[0]``..``[N]``; the count is the max iteration number."""
    agent = FurnaceAgent(job_id="epoch-xgboost")
    agent.redis._client = AsyncMock()

    for n in range(0, 101):
        agent._on_training_log(f"[{n}]\tvalidation_0-auc:{0.7 + n / 1000:.6f}")
    agent._on_training_log("Accuracy: 0.80")
    agent._on_training_log("AUC: 0.82")
    await asyncio.sleep(0.05)

    assert agent._epoch_count == 100, f"expected 100, got {agent._epoch_count}"
    assert agent._max_epochs == 100
    assert agent._epoch_source == "iter"

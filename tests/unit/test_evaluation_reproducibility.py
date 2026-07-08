"""Tests for evaluation/reproducibility.py — variance checker."""

import logging

import pytest

logging.disable(logging.CRITICAL)


def test_reproducibility_imports():
    """Module should import cleanly."""
    from evaluation.reproducibility import VARIANCE_THRESHOLD, run_reproducibility_check

    assert VARIANCE_THRESHOLD == 0.05
    assert callable(run_reproducibility_check)


def test_reproducibility_no_problems():
    """Should return error for non-existent problem IDs."""
    import asyncio

    from evaluation.reproducibility import run_reproducibility_check

    result = asyncio.run(run_reproducibility_check(problem_ids=["NONEXISTENT"], n_runs=1))
    assert result["passed"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_reproducibility_variance_threshold_is_constant():
    """VARIANCE_THRESHOLD should be 0.05 as documented."""
    from evaluation.reproducibility import VARIANCE_THRESHOLD

    assert VARIANCE_THRESHOLD == 0.05

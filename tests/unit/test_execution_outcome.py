"""Tests for learning/execution_outcome.py — ExecutionOutcome recording."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from memory.schemas import ExecutionOutcome


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    return redis


@pytest.fixture
def sample_outcome():
    return ExecutionOutcome(
        job_id="test-job-001",
        architecture="lightgbm",
        modality="tabular",
        task_type="classification",
        num_rows=891,
        num_columns=11,
        duration_seconds=780.0,
        retries=1,
        crashes=0,
        crashes_recovered=0,
        peak_ram_mb=1200.0,
        deployment_success=True,
        final_metric=0.892,
        outcome_label="pass",
    )


@pytest.mark.asyncio
async def test_record_outcome_stores_to_redis(mock_redis):
    from learning.execution_outcome import record_outcome

    with patch("memory.collections.experience_memory.store_experience"):
        outcome = await record_outcome(
            redis=mock_redis,
            job_id="test-job-001",
            architecture="lightgbm",
            modality="tabular",
            task_type="classification",
            duration_seconds=780.0,
            retries=1,
            crashes=0,
            crashes_recovered=0,
            peak_ram_mb=1200.0,
            deployment_success=True,
            final_metric=0.892,
            outcome_label="pass",
            num_rows=891,
            num_columns=11,
        )

    assert outcome.job_id == "test-job-001"
    assert outcome.architecture == "lightgbm"
    assert outcome.duration_seconds == 780.0
    assert outcome.outcome_label == "pass"
    assert outcome.deployment_success is True
    assert mock_redis.set.called
    key = mock_redis.set.call_args[0][0]
    assert key == "job:test-job-001:execution_outcome"


@pytest.mark.asyncio
async def test_get_outcome_returns_recorded(mock_redis):
    from learning.execution_outcome import get_outcome, record_outcome

    with patch("memory.collections.experience_memory.store_experience"):
        await record_outcome(
            redis=mock_redis,
            job_id="test-job-002",
            architecture="xgboost",
            modality="tabular",
            task_type="regression",
            duration_seconds=1500.0,
            retries=0,
            crashes=0,
            crashes_recovered=0,
            deployment_success=True,
            final_metric=0.75,
            outcome_label="pass",
        )

    mock_redis.get.return_value = (
        '{"job_id":"test-job-002","architecture":"xgboost","modality":"tabular",'
        '"task_type":"regression","num_rows":0,"num_columns":0,"duration_seconds":1500.0,'
        '"retries":0,"crashes":0,"crashes_recovered":0,"peak_ram_mb":null,"peak_gpu_mb":null,'
        '"deployment_success":true,"final_metric":0.75,"outcome_label":"pass",'
        '"created_at":"2026-07-07T00:00:00"}'
    )

    outcome = await get_outcome(mock_redis, "test-job-002")
    assert outcome is not None
    assert outcome.job_id == "test-job-002"
    assert outcome.architecture == "xgboost"
    assert outcome.duration_seconds == 1500.0
    assert outcome.outcome_label == "pass"


@pytest.mark.asyncio
async def test_get_outcome_returns_none_when_missing(mock_redis):
    from learning.execution_outcome import get_outcome

    outcome = await get_outcome(mock_redis, "nonexistent-job")
    assert outcome is None


@pytest.mark.asyncio
async def test_record_outcome_on_escalate(mock_redis):
    from learning.execution_outcome import record_outcome

    with patch("memory.collections.experience_memory.store_experience"):
        outcome = await record_outcome(
            redis=mock_redis,
            job_id="test-job-003",
            architecture="lightgbm",
            modality="tabular",
            task_type="classification",
            duration_seconds=300.0,
            retries=2,
            crashes=3,
            crashes_recovered=1,
            deployment_success=False,
            outcome_label="escalate",
        )

    assert outcome.outcome_label == "escalate"
    assert outcome.deployment_success is False
    assert outcome.crashes == 3
    assert outcome.crashes_recovered == 1


@pytest.mark.asyncio
async def test_outcome_duration_minutes_property(sample_outcome):
    assert sample_outcome.duration_minutes == pytest.approx(13.0, rel=0.1)


@pytest.mark.asyncio
async def test_record_outcome_fails_gracefully(mock_redis):
    from learning.execution_outcome import record_outcome

    mock_redis.set.side_effect = RuntimeError("Redis down")

    with patch("memory.collections.experience_memory.store_experience"):
        outcome = await record_outcome(
            redis=mock_redis,
            job_id="test-job-004",
            architecture="lightgbm",
            modality="tabular",
            task_type="classification",
            duration_seconds=60.0,
            outcome_label="pass",
        )

    assert outcome.job_id == "test-job-004"
    assert outcome.outcome_label == "pass"

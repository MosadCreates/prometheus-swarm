"""Unit tests for Forge Script Fingerprint Cache (Gap 4 / Missing Piece 4)."""

import json
import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from agents.forge.script_fingerprint import (
    compute_fingerprint,
    check_fingerprint,
    record_fingerprint,
    record_fingerprint_pending,
    mark_fingerprint_success,
    mark_fingerprint_failed,
    get_job_fingerprint,
    fp_redis_key,
)

SAMPLE_SCRIPT = """
import lightgbm as lgb
import pandas as pd

df = pd.read_csv("data.csv")
target = df.pop("Survived")
model = lgb.LGBMClassifier()
model.fit(df, target)
print("done")
"""

ANOTHER_SCRIPT = """
import xgboost as xgb
import pandas as pd

df = pd.read_csv("data.csv")
model = xgb.XGBClassifier()
model.fit(df.drop("y", axis=1), df["y"])
print("done")
"""


class TestComputeFingerprint:
    def test_returns_16_char_hex(self):
        fp = compute_fingerprint(SAMPLE_SCRIPT)
        assert len(fp) == 16
        assert all(c in "0123456789abcdef" for c in fp)

    def test_deterministic_same_input(self):
        fp1 = compute_fingerprint(SAMPLE_SCRIPT)
        fp2 = compute_fingerprint(SAMPLE_SCRIPT)
        assert fp1 == fp2

    def test_different_inputs_differ(self):
        fp1 = compute_fingerprint(SAMPLE_SCRIPT)
        fp2 = compute_fingerprint(ANOTHER_SCRIPT)
        assert fp1 != fp2

    def test_whitespace_insensitive_at_edges(self):
        a = compute_fingerprint("  hello  ")
        b = compute_fingerprint("hello")
        assert a == b

    def test_empty_string(self):
        fp = compute_fingerprint("")
        expected = hashlib.sha256(b"").hexdigest()[:16]
        assert fp == expected

    def test_known_hash(self):
        """Verify the hash doesn't change across Python versions."""
        fp = compute_fingerprint("print(1)")
        expected = hashlib.sha256(b"print(1)").hexdigest()[:16]
        assert fp == expected


class TestFingerprintRedisKey:
    def test_key_format(self):
        key = fp_redis_key("abc123")
        assert key == "forge:script_fp:abc123"


class TestCheckFingerprint:
    @pytest.mark.asyncio
    async def test_returns_none_when_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        result = await check_fingerprint(mock_redis, "abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_record_when_found(self):
        mock_redis = AsyncMock()
        record = {"fingerprint": "abc123", "outcome": "success", "val_metric": 0.85}
        mock_redis.get.return_value = json.dumps(record)
        result = await check_fingerprint(mock_redis, "abc123")
        assert result == record

    @pytest.mark.asyncio
    async def test_handles_corrupted_json_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "not-json"
        result = await check_fingerprint(mock_redis, "abc123")
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_connection_error_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = ConnectionError("Redis down")
        result = await check_fingerprint(mock_redis, "abc123")
        assert result is None


class TestRecordFingerprint:
    @pytest.mark.asyncio
    async def test_records_new_fingerprint(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # No existing record

        await record_fingerprint(
            mock_redis,
            "abc123",
            "lightgbm",
            "job-1",
            outcome="pending",
            script_path="scripts/train.py",
        )
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        key = call_args[0]
        value = json.loads(call_args[2])
        assert key == "forge:script_fp:abc123"
        assert value["fingerprint"] == "abc123"
        assert value["architecture"] == "lightgbm"
        assert value["outcome"] == "pending"
        assert value["usage_count"] == 1

    @pytest.mark.asyncio
    async def test_increments_usage_count_on_existing(self):
        mock_redis = AsyncMock()
        existing = json.dumps(
            {
                "fingerprint": "abc123",
                "architecture": "lightgbm",
                "outcome": "pending",
                "usage_count": 5,
                "first_seen": "2026-01-01T00:00:00Z",
            }
        )
        mock_redis.get.return_value = existing

        await record_fingerprint(
            mock_redis,
            "abc123",
            "lightgbm",
            "job-2",
            outcome="pending",
            script_path="scripts/train2.py",
        )
        value = json.loads(mock_redis.setex.call_args[0][2])
        assert value["usage_count"] == 6

    @pytest.mark.asyncio
    async def test_records_as_success(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        await record_fingerprint(
            mock_redis,
            "abc123",
            "xgboost",
            "job-1",
            outcome="success",
            val_metric=0.91,
            total_epochs=10,
        )
        value = json.loads(mock_redis.setex.call_args[0][2])
        assert value["outcome"] == "success"
        assert value["val_metric"] == 0.91
        assert value["total_epochs"] == 10

    @pytest.mark.asyncio
    async def test_sets_90_day_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        await record_fingerprint(mock_redis, "abc123", "lightgbm", "job-1", outcome="pending")
        call_args = mock_redis.setex.call_args[0]
        ttl = call_args[1]
        assert ttl == 86400 * 90  # 90 days


class TestRecordFingerprintPending:
    @pytest.mark.asyncio
    async def test_records_pending_and_job_key(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        await record_fingerprint_pending(
            mock_redis,
            "abc123",
            "lightgbm",
            "job-42",
            script_path="scripts/training_script_job-42.py",
        )
        # Should set the fp record
        assert mock_redis.setex.call_count >= 1

        # Should also set the job→fp mapping
        # Find the call with the job key
        job_key_calls = [
            c for c in mock_redis.setex.call_args_list if "job:job-42:script_fingerprint" in str(c)
        ]
        assert len(job_key_calls) >= 1


class TestMarkFingerprintSuccess:
    @pytest.mark.asyncio
    async def test_updates_pending_to_success(self):
        mock_redis = AsyncMock()
        existing = json.dumps(
            {
                "fingerprint": "abc123",
                "architecture": "lightgbm",
                "outcome": "pending",
                "usage_count": 1,
                "first_seen": "2026-01-01T00:00:00Z",
            }
        )
        mock_redis.get.return_value = existing

        await mark_fingerprint_success(
            mock_redis,
            "abc123",
            checkpoint_path="outputs/job-1/checkpoints/best.ckpt",
            val_metric=0.88,
            total_epochs=8,
        )
        value = json.loads(mock_redis.setex.call_args[0][2])
        assert value["outcome"] == "success"
        assert value["checkpoint_path"] == "outputs/job-1/checkpoints/best.ckpt"
        assert value["val_metric"] == 0.88
        assert value["total_epochs"] == 8

    @pytest.mark.asyncio
    async def test_does_nothing_if_fingerprint_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        await mark_fingerprint_success(mock_redis, "nonexistent", "", 0.0, 0)
        mock_redis.setex.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_corrupted_record_gracefully(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "corrupted"
        await mark_fingerprint_success(mock_redis, "abc123", "", 0.0, 0)
        mock_redis.setex.assert_not_called()


class TestMarkFingerprintFailed:
    @pytest.mark.asyncio
    async def test_updates_to_failed(self):
        mock_redis = AsyncMock()
        existing = json.dumps(
            {
                "fingerprint": "abc123",
                "outcome": "pending",
                "usage_count": 1,
                "first_seen": "2026-01-01T00:00:00Z",
            }
        )
        mock_redis.get.return_value = existing
        await mark_fingerprint_failed(mock_redis, "abc123")
        value = json.loads(mock_redis.setex.call_args[0][2])
        assert value["outcome"] == "failed"

    @pytest.mark.asyncio
    async def test_does_nothing_if_missing(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        await mark_fingerprint_failed(mock_redis, "nonexistent")
        mock_redis.setex.assert_not_called()


class TestGetJobFingerprint:
    @pytest.mark.asyncio
    async def test_returns_none_if_no_job_fp(self):
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        result = await get_job_fingerprint(mock_redis, "job-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_record_from_job_fp(self):
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = lambda key: {
            "job:job-1:script_fingerprint": "abc123",
            "forge:script_fp:abc123": json.dumps(
                {
                    "fingerprint": "abc123",
                    "outcome": "success",
                    "val_metric": 0.85,
                }
            ),
        }.get(key)

        result = await get_job_fingerprint(mock_redis, "job-1")
        assert result is not None
        assert result["fingerprint"] == "abc123"
        assert result["outcome"] == "success"


class TestIntegrationHooks:
    """Test that tools.py integrates fingerprint calls correctly."""

    def test_compute_fingerprint_imported_from_tools(self):
        from agents.forge.tools import write_training_script
        from agents.forge.script_fingerprint import compute_fingerprint

        # Verify the function is accessible and callable
        fp = compute_fingerprint("test script")
        assert len(fp) == 16

    @patch("agents.forge.tools._check_and_record_fingerprint")
    def test_write_training_script_calls_fingerprint_f_string(
        self,
        mock_fp,
    ):
        """Verify the fingerprint hook is called in the f-string fallback path."""
        from agents.forge.tools import write_training_script

        brief = {
            "task_type": "classification",
            "modality": "tabular",
            "target_column": "Survived",
            "imbalance_strategy": "none",
            "evaluation_metric": "auc_roc",
            "recommended_architecture_family": "lightgbm",
            "dataset": {
                "file_path": "tests/fixtures/titanic.csv",
                "num_rows": 891,
                "column_types": {},
            },
        }

        with patch("agents.forge.tools._write_lightgbm_script", return_value="/tmp/script.py"):
            write_training_script(
                brief,
                "job-fp-test",
                architecture="lightgbm",
                scripts_dir="/tmp",
            )
            mock_fp.assert_called_once()

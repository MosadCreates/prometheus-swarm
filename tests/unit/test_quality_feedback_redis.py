"""Unit tests for Forge Quality Feedback with Redis (Gap 3)."""

import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from agents.forge.quality_feedback import (
    infer_architecture,
    record_repair,
    _sync_to_file,
    _get_recommendation,
    _category_to_modification_type,
)

SAMPLE_LIGHTGBM = """
import lightgbm as lgb
from lightgbm import LGBMClassifier
"""

SAMPLE_XGBOOST = """
import xgboost as xgb
model = xgb.XGBClassifier()
"""

SAMPLE_DISTILBERT = """
from transformers import DistilBertForSequenceClassification
model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased")
"""

SAMPLE_EFFICIENTNET = """
from torchvision import models
model = models.efficientnet_b0(pretrained=True)
"""


class TestInferArchitecture:
    def test_lightgbm(self):
        assert infer_architecture(SAMPLE_LIGHTGBM) == "lightgbm"

    def test_xgboost(self):
        assert infer_architecture(SAMPLE_XGBOOST) == "xgboost"

    def test_distilbert(self):
        assert infer_architecture(SAMPLE_DISTILBERT) == "distilbert"

    def test_efficientnet(self):
        assert infer_architecture(SAMPLE_EFFICIENTNET) == "efficientnet"

    def test_tabnet(self):
        assert (
            infer_architecture("from pytorch_tabnet.tab_model import TabNetClassifier") == "tabnet"
        )

    def test_unknown(self):
        assert infer_architecture("import numpy as np") == "unknown"

    def test_empty_string(self):
        assert infer_architecture("") == "unknown"

    def test_none(self):
        assert infer_architecture(None) == "unknown"


class TestGetRecommendation:
    def test_known_category(self):
        rec = _get_recommendation("dtype_mismatch", "lightgbm")
        assert "LabelEncoder" in rec

    def test_unknown_category(self):
        rec = _get_recommendation("some_rare_error", "lightgbm")
        assert "some_rare_error" in rec
        assert "lightgbm" in rec


class TestCategoryToModificationType:
    def test_dtype_mismatch(self):
        assert _category_to_modification_type("dtype_mismatch") == "insert_after_imports"

    def test_missing_column(self):
        assert _category_to_modification_type("missing_column") == "insert_after_data_loading"

    def test_nan_propagation(self):
        assert _category_to_modification_type("nan_propagation") == "insert_after_data_loading"

    def test_convergence_failure(self):
        assert _category_to_modification_type("convergence_failure") == "insert_before_checkpoint"

    def test_unknown(self):
        assert _category_to_modification_type("novel_error") == "insert_after_imports"


class TestSyncToFile:
    """Test the file-based sync with isolated temp files."""

    def _temp_feedback(self, initial="{}"):
        f = tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w")
        f.write(initial)
        f.close()
        return f.name

    def test_starts_file_if_not_exists(self):
        path = self._temp_feedback("{}")
        os.unlink(path)  # remove so it doesn't exist
        with patch("agents.forge.quality_feedback.FEEDBACK_FILE", path):
            _sync_to_file("job-1", "dtype_mismatch", "lightgbm", False)
            assert os.path.exists(path)
        os.unlink(path)

    def test_appends_without_corrupting(self):
        path = self._temp_feedback("{}")
        with patch("agents.forge.quality_feedback.FEEDBACK_FILE", path):
            _sync_to_file("job-1", "dtype_mismatch", "lightgbm", False)
            _sync_to_file("job-2", "missing_column", "xgboost", False)
            _sync_to_file("job-3", "dtype_mismatch", "lightgbm", True)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["total_jobs_tracked"] == 3
            assert data["total_repairs_needed"] == 2
        os.unlink(path)

    def test_tracks_counts_per_architecture_and_category(self):
        path = self._temp_feedback("{}")
        with patch("agents.forge.quality_feedback.FEEDBACK_FILE", path):
            _sync_to_file("job-1", "dtype_mismatch", "lightgbm", False)
            _sync_to_file("job-2", "dtype_mismatch", "lightgbm", False)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["recurring_categories"]["lightgbm::dtype_mismatch"]["count"] == 2
        os.unlink(path)

    def test_top_failures_sorted(self):
        path = self._temp_feedback("{}")
        with patch("agents.forge.quality_feedback.FEEDBACK_FILE", path):
            for i in range(3):
                _sync_to_file(f"job-{i}", "dtype_mismatch", "lightgbm", False)
            for i in range(2):
                _sync_to_file(f"job-{i+10}", "missing_column", "xgboost", False)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data["top_failures"]) == 2
            assert data["top_failures"][0]["count"] == 3
        os.unlink(path)

    @pytest.mark.asyncio
    async def test_record_repair_fallback_calls_sync_to_file(self):
        with patch("agents.forge.quality_feedback._sync_to_file") as mock_sync:
            await record_repair("job-1", "dtype_mismatch", "lightgbm", False)
            mock_sync.assert_called_once()


class TestRecordRepairRedis:
    """Test the Redis-backed recording path."""

    @pytest.mark.asyncio
    async def test_record_repair_redis_success(self):
        mock_redis = AsyncMock()
        from agents.forge.quality_feedback import record_repair_redis

        await record_repair_redis(mock_redis, "job-1", "dtype_mismatch", "lightgbm", True)
        assert mock_redis.hincrby.call_count >= 2

    @pytest.mark.asyncio
    async def test_infers_architecture(self):
        mock_redis = AsyncMock()
        from agents.forge.quality_feedback import record_repair_redis

        await record_repair_redis(
            mock_redis,
            "job-1",
            "dtype_mismatch",
            "unknown",
            False,
            script_content=SAMPLE_LIGHTGBM,
        )
        mock_redis.hincrby.assert_any_call("forge:error_stats:lightgbm:dtype_mismatch", "count", 1)

    @pytest.mark.asyncio
    async def test_increment_script_count(self):
        mock_redis = AsyncMock()
        from agents.forge.quality_feedback import increment_script_count

        await increment_script_count(mock_redis, "lightgbm")
        assert mock_redis.hincrby.call_count == 2

    @pytest.mark.asyncio
    async def test_get_error_rate_by_category(self):
        mock_redis = AsyncMock()
        mock_redis.hget.side_effect = lambda k, f: {
            ("forge:error_stats:totals", "lightgbm:total_scripts"): "10",
            ("forge:error_stats:lightgbm:dtype_mismatch", "count"): "3",
        }.get((k, f))
        from agents.forge.quality_feedback import get_error_rate_redis

        rate = await get_error_rate_redis(mock_redis, "lightgbm", "dtype_mismatch")
        assert rate == pytest.approx(0.3)

    @pytest.mark.asyncio
    async def test_get_error_rate_all_categories(self):
        mock_redis = AsyncMock()
        mock_redis.scan_keys = AsyncMock(
            return_value=[
                "forge:error_stats:lightgbm:dtype_mismatch",
                "forge:error_stats:lightgbm:missing_column",
            ]
        )
        mock_redis.hget.side_effect = lambda k, f: {
            ("forge:error_stats:totals", "lightgbm:total_scripts"): "10",
            ("forge:error_stats:lightgbm:dtype_mismatch", "count"): "3",
            ("forge:error_stats:lightgbm:missing_column", "count"): "1",
        }.get((k, f))
        from agents.forge.quality_feedback import get_error_rate_redis

        rates = await get_error_rate_redis(mock_redis, "lightgbm")
        assert isinstance(rates, dict)
        assert rates.get("dtype_mismatch") == pytest.approx(0.3)
        assert rates.get("missing_column") == pytest.approx(0.1)

    @pytest.mark.asyncio
    async def test_get_top_failures_redis(self):
        mock_redis = AsyncMock()
        mock_redis.scan_keys = AsyncMock(
            return_value=[
                "forge:error_stats:lightgbm:dtype_mismatch",
                "forge:error_stats:lightgbm:missing_column",
            ]
        )
        mock_redis.hget.side_effect = lambda k, f: {
            ("forge:error_stats:lightgbm:dtype_mismatch", "count"): "5",
            ("forge:error_stats:lightgbm:missing_column", "count"): "2",
        }.get((k, f))
        from agents.forge.quality_feedback import get_top_failures_redis

        failures = await get_top_failures_redis(mock_redis, "lightgbm", n=2)
        assert len(failures) == 2
        assert failures[0]["category"] == "dtype_mismatch"

    @pytest.mark.asyncio
    async def test_auto_prevention_fires_at_threshold(self):
        """Count >= 2 and rate >= 20% triggers auto-prevention."""
        mock_redis = AsyncMock()

        async def hget(k, f):
            m = {
                ("forge:error_stats:lightgbm:dtype_mismatch", "count"): "2",
                ("forge:error_stats:totals", "lightgbm:total_scripts"): "5",
            }
            return m.get((k, f))

        mock_redis.hget.side_effect = hget

        with patch("agents.forge.prevention.push_prevention_rule", new_callable=AsyncMock) as push:
            with patch("shared.metrics.FORGE_ERROR_PREVENTIONS_AUTO") as met:
                from agents.forge.quality_feedback import record_repair_redis

                await record_repair_redis(mock_redis, "job-1", "dtype_mismatch", "lightgbm", False)
                push.assert_called_once()

    @pytest.mark.asyncio
    async def test_auto_prevention_does_not_fire_below_threshold(self):
        """Count < 3 skips auto-prevention."""
        mock_redis = AsyncMock()

        async def hget(k, f):
            m = {
                ("forge:error_stats:lightgbm:dtype_mismatch", "count"): "1",
                ("forge:error_stats:totals", "lightgbm:total_scripts"): "10",
            }
            return m.get((k, f))

        mock_redis.hget.side_effect = hget

        with patch("agents.forge.prevention.push_prevention_rule", new_callable=AsyncMock) as push:
            from agents.forge.quality_feedback import record_repair_redis

            await record_repair_redis(mock_redis, "job-1", "dtype_mismatch", "lightgbm", False)
            push.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_repair_skips_prevention(self):
        mock_redis = AsyncMock()
        with patch("agents.forge.quality_feedback._auto_create_prevention_rule") as auto:
            from agents.forge.quality_feedback import record_repair_redis

            await record_repair_redis(mock_redis, "job-1", "dtype_mismatch", "lightgbm", True)
            auto.assert_not_called()

    @pytest.mark.asyncio
    async def test_connection_error_graceful(self):
        mock_redis = AsyncMock()
        mock_redis.hincrby.side_effect = ConnectionError("Redis down")
        with patch("agents.forge.quality_feedback._sync_to_file") as sync:
            from agents.forge.quality_feedback import record_repair_redis

            await record_repair_redis(mock_redis, "job-1", "dtype_mismatch", "lightgbm", False)
            sync.assert_called_once()

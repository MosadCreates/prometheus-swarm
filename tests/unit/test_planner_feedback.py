"""Tests for learning/planner_feedback.py — PlanningHints and prediction error."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from prometheus.planner.models import PlanningHints


@pytest.fixture
def mock_redis():
    return AsyncMock()


@pytest.fixture
def sample_spec():
    return {
        "dataset_analysis": {
            "modality": "tabular",
            "task_type": "classification",
            "num_rows": 891,
            "num_columns": 11,
        },
        "recommended_pipeline": {
            "architecture": "lightgbm",
        },
        "constraints": {},
        "success_criteria": {},
    }


class TestComputePlanningHints:
    @pytest.mark.asyncio
    async def test_hints_empty_when_no_data(self, mock_redis, sample_spec):
        from learning.planner_feedback import compute_planning_hints

        with patch(
            "learning.planner_feedback._fetch_similar_outcomes",
            return_value=[],
        ):
            hints = await compute_planning_hints(sample_spec, mock_redis, "job-001")

        assert hints.evidence_count == 0
        assert hints.estimated_duration_minutes is None

    @pytest.mark.asyncio
    async def test_hints_empty_when_below_threshold(self, mock_redis, sample_spec):
        from learning.planner_feedback import compute_planning_hints

        with patch(
            "learning.planner_feedback._fetch_similar_outcomes",
            return_value=[{"architecture": "lightgbm", "outcome": "pass"}] * 2,
        ):
            hints = await compute_planning_hints(sample_spec, mock_redis, "job-002")

        assert hints.evidence_count == 0  # below _MIN_EVIDENCE threshold

    @pytest.mark.asyncio
    async def test_hints_from_similar_jobs(self, mock_redis, sample_spec):
        from learning.planner_feedback import compute_planning_hints

        outcomes = [
            {
                "architecture": "lightgbm",
                "outcome": "pass",
                "actual_training_minutes": 14.0,
                "peak_ram_mb": "1200",
                "peak_gpu_mb": "0",
                "prediction_error": 0.12,
            },
            {
                "architecture": "lightgbm",
                "outcome": "pass",
                "actual_training_minutes": 18.0,
                "peak_ram_mb": "1500",
                "peak_gpu_mb": "0",
                "prediction_error": 0.08,
            },
            {
                "architecture": "lightgbm",
                "outcome": "retry",
                "actual_training_minutes": 22.0,
                "peak_ram_mb": "1800",
                "peak_gpu_mb": "0",
                "prediction_error": 0.15,
            },
            {
                "architecture": "xgboost",
                "outcome": "pass",
                "actual_training_minutes": 25.0,
                "peak_ram_mb": "2000",
                "peak_gpu_mb": "0",
            },
        ]

        with patch(
            "learning.planner_feedback._fetch_similar_outcomes",
            return_value=outcomes,
        ):
            hints = await compute_planning_hints(sample_spec, mock_redis, "job-003")

        assert hints.evidence_count == 4
        # median of [14, 18, 22, 25] = (18+22)/2 = 20
        assert hints.estimated_duration_minutes == 20
        # median of [1200, 1500, 1800, 2000] = (1500+1800)/2 = 1650
        assert hints.estimated_ram_mb == 1650

    @pytest.mark.asyncio
    async def test_hints_fallback_models_ranked(self, mock_redis, sample_spec):
        from learning.planner_feedback import compute_planning_hints

        outcomes = [
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "escalate"},
            {"architecture": "tabnet", "outcome": "pass"},
            {"architecture": "tabnet", "outcome": "escalate"},
            {"architecture": "tabnet", "outcome": "escalate"},
        ]

        with patch(
            "learning.planner_feedback._fetch_similar_outcomes",
            return_value=outcomes,
        ):
            hints = await compute_planning_hints(sample_spec, mock_redis, "job-004")

        if hints.fallback_models:
            xgb_idx = (
                hints.fallback_models.index("xgboost") if "xgboost" in hints.fallback_models else 99
            )
            tab_idx = (
                hints.fallback_models.index("tabnet") if "tabnet" in hints.fallback_models else 99
            )
            # xgboost (67%) should rank above tabnet (33%)
            assert xgb_idx < tab_idx

    @pytest.mark.asyncio
    async def test_hints_gpu_recommended(self, mock_redis, sample_spec):
        from learning.planner_feedback import compute_planning_hints

        outcomes = [
            {
                "architecture": "lightgbm",
                "outcome": "pass",
                "gpu_used": True,
                "actual_training_minutes": 5,
            },
            {
                "architecture": "lightgbm",
                "outcome": "pass",
                "gpu_used": True,
                "actual_training_minutes": 5,
            },
            {
                "architecture": "lightgbm",
                "outcome": "pass",
                "gpu_used": False,
                "actual_training_minutes": 5,
            },
        ]

        with patch(
            "learning.planner_feedback._fetch_similar_outcomes",
            return_value=outcomes,
        ):
            hints = await compute_planning_hints(sample_spec, mock_redis, "job-005")

        assert hints.gpu_recommended is True  # 2/3 used GPU
        assert hints.evidence_count == 3


class TestPredictionError:
    def test_compute_prediction_error_duration_overestimate(self):
        from learning.planner_feedback import compute_prediction_error

        errors = compute_prediction_error(
            predicted_duration_minutes=10,
            predicted_ram_mb=1024,
            predicted_vram_mb=0,
            actual_duration_seconds=780,
            actual_ram_mb=1500.0,
            actual_vram_mb=0.0,
            actual_retries=1,
            actual_deployment_success=True,
        )

        assert "duration_error_pct" in errors
        # |13-10|/10 = 30%
        assert errors["duration_error_pct"] == pytest.approx(30.0, rel=0.1)
        # (13-10)/10 = +30% (Planner underestimated)
        assert errors["duration_bias"] == pytest.approx(30.0, rel=0.1)

    def test_compute_prediction_error_exact_match(self):
        from learning.planner_feedback import compute_prediction_error

        errors = compute_prediction_error(
            predicted_duration_minutes=10,
            predicted_ram_mb=1024,
            predicted_vram_mb=0,
            actual_duration_seconds=600,
            actual_ram_mb=1024.0,
            actual_vram_mb=0.0,
            actual_retries=0,
            actual_deployment_success=True,
        )

        assert errors["duration_error_pct"] == pytest.approx(0.0, rel=0.1)
        assert errors["ram_error_pct"] == pytest.approx(0.0, rel=0.1)
        assert errors["retries_accuracy"] == "exact"
        assert errors["deployment_accuracy"] is True

    def test_compute_prediction_error_ram_underestimate(self):
        from learning.planner_feedback import compute_prediction_error

        errors = compute_prediction_error(
            predicted_duration_minutes=5,
            predicted_ram_mb=2000,
            predicted_vram_mb=0,
            actual_duration_seconds=300,
            actual_ram_mb=1000.0,
            actual_vram_mb=0.0,
            actual_retries=0,
            actual_deployment_success=True,
        )

        # |1000-2000|/2000 = 50%
        assert errors["ram_error_pct"] == pytest.approx(50.0, rel=0.1)
        # (1000-2000)/2000 = -50% (Planner overestimated)
        assert errors["ram_bias"] == pytest.approx(-50.0, rel=0.1)

    def test_compute_prediction_error_retries_over(self):
        from learning.planner_feedback import compute_prediction_error

        errors = compute_prediction_error(
            predicted_duration_minutes=10,
            predicted_ram_mb=1024,
            predicted_vram_mb=0,
            actual_duration_seconds=600,
            actual_ram_mb=1024.0,
            actual_vram_mb=0.0,
            actual_retries=2,
            actual_deployment_success=True,
        )

        assert errors["retries_accuracy"] == "over"

    def test_compute_prediction_error_no_ram_no_vram(self):
        from learning.planner_feedback import compute_prediction_error

        errors = compute_prediction_error(
            predicted_duration_minutes=10,
            predicted_ram_mb=None,
            predicted_vram_mb=None,
            actual_duration_seconds=600,
            actual_ram_mb=None,
            actual_vram_mb=None,
            actual_retries=0,
            actual_deployment_success=True,
        )

        assert "duration_error_pct" in errors
        assert "ram_error_pct" not in errors
        assert "vram_error_pct" not in errors


class TestRankFallbackModels:
    def test_rank_by_pass_rate(self):
        from learning.planner_feedback import _rank_fallback_models

        outcomes = [
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "escalate"},
            {"architecture": "tabnet", "outcome": "pass"},
            {"architecture": "tabnet", "outcome": "escalate"},
            {"architecture": "tabnet", "outcome": "escalate"},
        ]

        ranked = _rank_fallback_models(outcomes, "lightgbm")
        assert ranked is not None
        assert ranked[0] == "xgboost"

    def test_returns_none_when_below_threshold(self):
        from learning.planner_feedback import _rank_fallback_models

        ranked = _rank_fallback_models([{"architecture": "xgboost", "outcome": "pass"}], "lightgbm")
        assert ranked is None

    def test_excludes_current_architecture(self):
        from learning.planner_feedback import _rank_fallback_models

        outcomes = [
            {"architecture": "lightgbm", "outcome": "pass"},
            {"architecture": "lightgbm", "outcome": "pass"},
            {"architecture": "lightgbm", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "pass"},
            {"architecture": "xgboost", "outcome": "pass"},
        ]

        ranked = _rank_fallback_models(outcomes, "lightgbm")
        assert ranked is not None
        assert "lightgbm" not in ranked

    def test_returns_none_when_no_alternatives(self):
        from learning.planner_feedback import _rank_fallback_models

        outcomes = [
            {"architecture": "lightgbm", "outcome": "pass"},
            {"architecture": "lightgbm", "outcome": "pass"},
            {"architecture": "lightgbm", "outcome": "pass"},
        ]

        ranked = _rank_fallback_models(outcomes, "lightgbm")
        assert ranked is None

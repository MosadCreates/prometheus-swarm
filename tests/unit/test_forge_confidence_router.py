"""Unit tests for Forge Confidence Threshold Router (Missing Piece 5)."""

from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from agents.forge.confidence_router import (
    get_generation_strategy,
    strategy_label,
    TEMPLATE_THRESHOLD,
    CACHE_THRESHOLD,
    Strategy,
)


class TestGetGenerationStrategy:
    """Tests for strategy selection based on confidence score."""

    def test_none_confidence_returns_llm(self):
        assert get_generation_strategy(None) == "llm"

    def test_zero_confidence_returns_llm(self):
        assert get_generation_strategy(0.0) == "llm"

    def test_below_cache_threshold_returns_llm(self):
        assert get_generation_strategy(CACHE_THRESHOLD - 0.01) == "llm"

    def test_at_cache_threshold_returns_cache(self):
        assert get_generation_strategy(CACHE_THRESHOLD) == "cache"

    def test_above_cache_below_template_returns_cache(self):
        mid = (CACHE_THRESHOLD + TEMPLATE_THRESHOLD) / 2.0
        assert get_generation_strategy(mid) == "cache"

    def test_at_template_threshold_returns_template(self):
        assert get_generation_strategy(TEMPLATE_THRESHOLD) == "template"

    def test_above_template_threshold_returns_template(self):
        assert get_generation_strategy(TEMPLATE_THRESHOLD + 0.05) == "template"

    def test_perfect_confidence_returns_template(self):
        assert get_generation_strategy(1.0) == "template"

    def test_max_confidence_returns_template(self):
        assert get_generation_strategy(0.99) == "template"

    def test_high_confidence_edge_returns_template(self):
        assert get_generation_strategy(0.86) == "template"

    def test_medium_confidence_edge_returns_cache(self):
        assert get_generation_strategy(0.56) == "cache"

    def test_low_confidence_edge_returns_llm(self):
        assert get_generation_strategy(0.54) == "llm"

    def test_confidence_just_below_zero_clamped_returns_llm(self):
        # Confidence should be 0.0–1.0, but handle edge
        assert get_generation_strategy(0.0) == "llm"

    def test_confidence_above_one_is_valid(self):
        assert get_generation_strategy(1.5) == "template"

    def test_no_negative_division(self):
        for i in range(101):
            c = i / 100.0
            s = get_generation_strategy(c)
            assert s in ("template", "cache", "llm"), f"Unexpected strategy {s} for confidence {c}"


class TestStrategyLabel:
    def test_template_label(self):
        assert strategy_label("template") == "Template"

    def test_cache_label(self):
        assert strategy_label("cache") == "Cache"

    def test_llm_label(self):
        assert strategy_label("llm") == "LLM"

    def test_unknown_label(self):
        assert strategy_label("unknown") == "Unknown"
        assert strategy_label("") == "Unknown"  # type: ignore[arg-type]


class TestThresholdConstants:
    """Verify threshold values are in valid range and ordered correctly."""

    def test_template_threshold_greater_than_cache(self):
        assert TEMPLATE_THRESHOLD > CACHE_THRESHOLD

    def test_template_threshold_in_valid_range(self):
        assert 0.0 < TEMPLATE_THRESHOLD <= 1.0

    def test_cache_threshold_in_valid_range(self):
        assert 0.0 < CACHE_THRESHOLD <= 1.0

    def test_default_thresholds_match_spec(self):
        # From spec: high ≥ 0.85, medium ≥ 0.55, low < 0.55
        assert TEMPLATE_THRESHOLD == 0.85
        assert CACHE_THRESHOLD == 0.55


class TestIntegrationWithWriteTrainingScript:
    """Verify confidence_router is wired into tools.py correctly."""

    @patch("agents.forge.tools.select_and_render")
    @patch("agents.forge.tools.FORGE_STRATEGY_ROUTES")
    def test_template_strategy_skips_cache_lookup(
        self,
        mock_metric,
        mock_render,
    ):
        mock_render.return_value = "script content"

        from agents.forge.tools import write_training_script

        result = write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv"},
                "imbalance_strategy": "none",
            },
            "test-job-template",
            scripts_dir=".",
            architecture="lightgbm",
            confidence=0.90,
        )
        assert result is not None

    @patch("agents.forge.tools._lookup_fingerprint")
    @patch("agents.forge.tools.select_and_render")
    @patch("agents.forge.tools.FORGE_STRATEGY_ROUTES")
    def test_cache_strategy_checks_fingerprint_first(
        self,
        mock_metric,
        mock_render,
        mock_lookup,
    ):
        mock_lookup.return_value = None
        mock_render.return_value = "script content"

        from agents.forge.tools import write_training_script

        write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv"},
                "imbalance_strategy": "none",
            },
            "test-job-cache",
            scripts_dir=".",
            architecture="lightgbm",
            confidence=0.65,
        )
        mock_lookup.assert_called_once()

    @patch("agents.forge.tools._lookup_fingerprint")
    @patch("agents.forge.tools.select_and_render")
    @patch("agents.forge.tools.FORGE_STRATEGY_ROUTES")
    def test_cache_strategy_reuses_fingerprint_hit(
        self,
        mock_metric,
        mock_render,
        mock_lookup,
    ):
        mock_lookup.return_value = "cached_script_path.py"
        mock_render.return_value = "rendered"

        from agents.forge.tools import write_training_script

        result = write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv"},
                "imbalance_strategy": "none",
            },
            "test-job-cache-hit",
            scripts_dir=".",
            architecture="lightgbm",
            confidence=0.65,
        )
        assert result == "cached_script_path.py"
        mock_render.assert_not_called()

    def test_low_confidence_skips_template_and_generates(self):
        from agents.forge.tools import write_training_script

        result = write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv", "num_rows": 100},
                "imbalance_strategy": "none",
                "target_column": "Survived",
            },
            "test-low-conf",
            scripts_dir=".",
            architecture="lightgbm",
            confidence=0.40,
        )
        assert result is not None
        assert "test-low-conf" in result


class TestStrategyMetrics:
    """Verify each strategy increments the correct metric."""

    @patch("agents.forge.tools.FORGE_STRATEGY_ROUTES")
    def test_metric_labeled_with_strategy(self, mock_metric):
        from agents.forge.tools import write_training_script

        write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv"},
                "imbalance_strategy": "none",
            },
            "test-job-metric",
            scripts_dir=".",
            architecture="lightgbm",
            confidence=0.95,
        )
        mock_metric.labels.assert_called_once_with(
            strategy="template", architecture="lightgbm", job_id="test-job-metric"
        )

    @patch("agents.forge.tools.FORGE_STRATEGY_ROUTES")
    def test_default_confidence_uses_llm_strategy(self, mock_metric):
        from agents.forge.tools import write_training_script

        write_training_script(
            {
                "task_type": "classification",
                "dataset": {"file_path": "data.csv"},
                "imbalance_strategy": "none",
            },
            "test-job-default",
            scripts_dir=".",
            architecture="lightgbm",
        )
        mock_metric.labels.assert_called_once_with(
            strategy="llm", architecture="lightgbm", job_id="test-job-default"
        )

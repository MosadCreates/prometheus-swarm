"""Tests for compiler.py hints integration — historical evidence weighting."""

from __future__ import annotations

from typing import Any

import pytest

from prometheus.planner.models import PlanningHints
from prometheus.planner.compiler import (
    _apply_hints_to_budget,
    _apply_hints_to_retry,
    ResourceBudget,
    ResourceEstimates,
    RetryPolicy,
)


@pytest.fixture
def sample_spec() -> dict[str, Any]:
    return {
        "dataset_analysis": {
            "num_rows": 891,
            "num_columns": 11,
            "modality": "tabular",
        },
        "recommended_pipeline": {
            "architecture": "lightgbm",
        },
        "constraints": {},
        "success_criteria": {
            "primary_metric": "auc_roc",
            "min_acceptable": 0.80,
        },
    }


@pytest.fixture
def default_budget():
    return ResourceBudget(
        estimates=ResourceEstimates(
            estimated_duration_minutes=15,
            estimated_ram_mb=1024,
            estimated_vram_mb=0,
            estimated_disk_mb=100,
            gpu_required=False,
            cuda_version=None,
        ),
        limits={
            "max_duration_minutes": 30,
            "max_ram_mb": 2048,
            "max_vram_mb": 0,
        },
    )


@pytest.fixture
def default_retry():
    return RetryPolicy(
        max_attempts=3,
        fallback_models=["xgboost", "tabnet"],
    )


class TestApplyHintsToBudget:
    def test_weighted_blend_applied(self, default_budget):
        hints = PlanningHints(
            evidence_count=12,
            estimated_duration_minutes=25,
            estimated_ram_mb=2000,
        )

        budget = _apply_hints_to_budget(default_budget, hints)

        # weight = min(0.7, 12/20) = 0.6
        # duration = 0.6 * 25 + 0.4 * 15 = 21
        assert budget.estimates.estimated_duration_minutes == pytest.approx(21.0, rel=0.5)
        # ram = 0.6 * 2000 + 0.4 * 1024 = 1200 + 409.6 = 1609.6
        assert budget.estimates.estimated_ram_mb == pytest.approx(1610, rel=1)

    def test_caps_at_max_weight(self, default_budget):
        hints = PlanningHints(
            evidence_count=100,
            estimated_duration_minutes=50,
            estimated_ram_mb=5000,
        )

        budget = _apply_hints_to_budget(default_budget, hints)

        # weight = min(0.7, 100/20) = 0.7
        assert budget.estimates.estimated_duration_minutes == pytest.approx(39.5, rel=1)


class TestApplyHintsToRetry:
    def test_fallback_models_override(self, default_retry):
        hints = PlanningHints(
            evidence_count=10,
            estimated_duration_minutes=20,
            estimated_ram_mb=1500,
            fallback_models=["tabnet", "xgboost"],
        )

        retry = _apply_hints_to_retry(default_retry, hints)

        assert retry.fallback_models == ["tabnet", "xgboost"]

    def test_no_hints_leaves_default(self, default_retry):
        hints = PlanningHints(
            evidence_count=0,
            estimated_duration_minutes=None,
            estimated_ram_mb=None,
            fallback_models=None,
        )

        retry = _apply_hints_to_retry(default_retry, hints)

        assert retry.fallback_models == ["xgboost", "tabnet"]

    def test_empty_fallback_keeps_default(self, default_retry):
        hints = PlanningHints(
            evidence_count=5,
            estimated_duration_minutes=20,
            estimated_ram_mb=1000,
            fallback_models=[],
        )

        retry = _apply_hints_to_retry(default_retry, hints)

        assert retry.fallback_models == ["xgboost", "tabnet"]


def test_compile_plan_no_hints(sample_spec):
    from prometheus.planner.compiler import compile_plan

    plan = compile_plan(sample_spec, "test-job-001")
    assert plan is not None
    assert plan.job_id == "test-job-001"
    assert plan.estimated_total_minutes > 0


def test_compile_plan_with_hints(sample_spec):
    from prometheus.planner.compiler import compile_plan

    hints = PlanningHints(
        evidence_count=10,
        estimated_duration_minutes=25,
        estimated_ram_mb=2000,
        estimated_vram_mb=0,
        gpu_recommended=False,
        fallback_models=["xgboost"],
        last_prediction_error_pct=15.0,
    )

    plan = compile_plan(sample_spec, "test-job-002", hints=hints)
    assert plan is not None
    assert plan.job_id == "test-job-002"


def test_compile_plan_below_threshold_hints(sample_spec):
    from prometheus.planner.compiler import compile_plan

    hints = PlanningHints(
        evidence_count=2,
        estimated_duration_minutes=999,
        estimated_ram_mb=9999,
        estimated_vram_mb=0,
        gpu_recommended=False,
        fallback_models=None,
    )

    plan = compile_plan(sample_spec, "test-job-003", hints=hints)

    # Below threshold — hints should not affect plan
    node = next(n for n in plan.nodes.values() if n.id == "furnace_train")
    assert node.id == "furnace_train"

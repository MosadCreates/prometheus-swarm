"""Unit tests for the Planner compiler."""

from __future__ import annotations

from typing import Any

import pytest

from prometheus.planner.compiler import compile_plan, _compute_confidence, _build_budget


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_TABULAR_SPEC: dict[str, Any] = {
    "dataset_analysis": {
        "modality": "tabular",
        "num_rows": 891,
        "num_columns": 11,
    },
    "recommended_pipeline": {
        "architecture": "lightgbm",
        "preprocessing_steps": ["median_imputation", "ordinal_encoding"],
    },
    "constraints": {},
    "success_criteria": {
        "primary_metric": "auc_roc",
        "min_acceptable": 0.75,
        "target": 0.85,
    },
}

_TEXT_SPEC: dict[str, Any] = {
    "dataset_analysis": {
        "modality": "text",
        "num_rows": 5000,
        "num_columns": 2,
    },
    "recommended_pipeline": {
        "architecture": "distilbert",
        "preprocessing_steps": ["tokenization"],
    },
    "constraints": {},
    "success_criteria": {
        "primary_metric": "f1",
        "min_acceptable": 0.75,
        "target": 0.85,
    },
}

_IMAGE_SPEC: dict[str, Any] = {
    "dataset_analysis": {
        "modality": "image",
        "num_rows": 10000,
        "num_columns": 5,
    },
    "recommended_pipeline": {
        "architecture": "efficientnet",
        "preprocessing_steps": ["resize", "normalize"],
    },
    "constraints": {},
    "success_criteria": {
        "primary_metric": "accuracy",
        "min_acceptable": 0.80,
        "target": 0.90,
    },
}

_LARGE_SPEC: dict[str, Any] = {
    "dataset_analysis": {
        "modality": "tabular",
        "num_rows": 12_000_000,
        "num_columns": 480,
    },
    "recommended_pipeline": {
        "architecture": "xgboost",
        "preprocessing_steps": ["median_imputation", "ordinal_encoding"],
    },
    "constraints": {
        "max_latency_ms": 200,
    },
    "success_criteria": {
        "primary_metric": "auc_roc",
        "min_acceptable": 0.75,
        "target": 0.85,
    },
}


# ---------------------------------------------------------------------------
# compile_plan — end-to-end
# ---------------------------------------------------------------------------


def test_compile_plan_tabular_lightgbm():
    plan = compile_plan(_TABULAR_SPEC, "job-001")
    assert plan.job_id == "job-001"
    assert plan.execution_plan_version == "1.0"
    assert plan.planner_version == "0.1.0"
    assert len(plan.nodes) >= 6
    assert len(plan.edges) >= 8
    assert plan.critical_path is not None


def test_compile_plan_text_distilbert():
    plan = compile_plan(_TEXT_SPEC, "job-002")
    assert plan.resource_budget.requirements.gpu_required is True
    assert plan.resource_budget.requirements.min_vram_mb >= 4096
    assert plan.confidence.score >= 0.80
    assert plan.confidence.assessment in ("high", "medium")


def test_compile_plan_image_efficientnet():
    plan = compile_plan(_IMAGE_SPEC, "job-003")
    assert plan.resource_budget.requirements.gpu_required is True
    assert plan.resource_budget.estimates.estimated_duration_minutes >= 10
    assert plan.confidence.score >= 0.70


def test_compile_plan_large_dataset():
    plan = compile_plan(_LARGE_SPEC, "job-004")
    assert plan.estimated_total_minutes >= 5
    assert plan.resource_budget.cost_optimization_hint in (
        "latency_optimized",
        "gpu_required",
        "cpu_preferred_large",
    )
    assert len(plan.artifacts) >= 3
    assert len(plan.critical_checkpoints) >= 3


def test_compile_plan_retry_policy():
    plan = compile_plan(_TABULAR_SPEC, "job-005")
    assert plan.retry_policy.max_attempts == 3
    assert len(plan.retry_policy.fallback_models) >= 1
    assert len(plan.retry_policy.fallback_strategies) >= 3


def test_compile_plan_confidence_factors():
    plan = compile_plan(_TABULAR_SPEC, "job-006")
    factors = plan.confidence.factors
    assert "architecture_maturity" in factors
    assert "dataset_size" in factors
    assert "modality_fit" in factors
    assert 0.0 <= plan.confidence.score <= 1.0


def test_compile_plan_empty_spec():
    plan = compile_plan({}, "job-007")
    assert plan.job_id == "job-007"
    assert len(plan.nodes) >= 6  # fallback to defaults


def test_compile_plan_serializable():
    plan = compile_plan(_TABULAR_SPEC, "job-008")
    dumped = plan.model_dump_json()
    # model_dump_json() produces compact JSON without spaces after colons
    assert '"job_id":"job-008"' in dumped
    assert '"execution_plan_version":"1.0"' in dumped


# ---------------------------------------------------------------------------
# Budget estimation
# ---------------------------------------------------------------------------


def test_budget_lightgbm():
    arch = {
        "base_minutes": 0.5,
        "minutes_per_row": 1 / 50000,
        "base_ram_mb": 256,
        "ram_per_row": 0.001,
        "disk_mb": 10,
        "base_vram_mb": 0,
        "vram_per_row": 0,
        "gpu": False,
        "cuda": None,
    }
    budget = _build_budget(arch, 1000, 10, {})
    assert budget.requirements.gpu_required is False
    assert budget.estimates.estimated_duration_minutes >= 1
    assert budget.estimates.estimated_ram_mb >= 256
    assert budget.cost_optimization_hint == "cpu_preferred"


def test_budget_distilbert():
    arch = {
        "base_minutes": 10.0,
        "minutes_per_row": 1 / 1000,
        "base_ram_mb": 2048,
        "ram_per_row": 0.01,
        "disk_mb": 500,
        "base_vram_mb": 4096,
        "vram_per_row": 0.005,
        "gpu": True,
        "cuda": "11.8",
    }
    budget = _build_budget(arch, 5000, 2, {})
    assert budget.requirements.gpu_required is True
    assert budget.requirements.cuda_version == "11.8"
    assert budget.estimates.estimated_duration_minutes >= 10
    assert budget.estimates.estimated_vram_mb >= 4096
    assert budget.cost_optimization_hint == "gpu_required"


def test_budget_latency_constraint():
    arch = {
        "base_minutes": 0.5,
        "minutes_per_row": 1 / 50000,
        "base_ram_mb": 256,
        "ram_per_row": 0.001,
        "disk_mb": 10,
        "base_vram_mb": 0,
        "vram_per_row": 0,
        "gpu": False,
        "cuda": None,
    }
    budget = _build_budget(arch, 10000, 10, {"max_latency_ms": 50})
    assert budget.cost_optimization_hint == "latency_optimized"


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------


def test_confidence_high():
    conf = _compute_confidence(
        _TABULAR_SPEC,
        "lightgbm",
        10000,
        10,
        "tabular",
        _build_budget(
            {
                "base_minutes": 0.5,
                "minutes_per_row": 1 / 50000,
                "base_ram_mb": 256,
                "ram_per_row": 0.001,
                "disk_mb": 10,
                "base_vram_mb": 0,
                "vram_per_row": 0,
                "gpu": False,
                "cuda": None,
            },
            10000,
            10,
            {},
        ),
    )
    assert conf.score >= 0.85
    assert conf.assessment == "high"


def test_confidence_low_for_small_dataset():
    conf = _compute_confidence(
        _TABULAR_SPEC,
        "lightgbm",
        50,
        3,
        "tabular",
        _build_budget(
            {
                "base_minutes": 0.5,
                "minutes_per_row": 1 / 50000,
                "base_ram_mb": 256,
                "ram_per_row": 0.001,
                "disk_mb": 10,
                "base_vram_mb": 0,
                "vram_per_row": 0,
                "gpu": False,
                "cuda": None,
            },
            50,
            3,
            {},
        ),
    )
    assert conf.score < 0.85


def test_confidence_poor_modality_fit():
    conf = _compute_confidence(
        _IMAGE_SPEC,
        "lightgbm",
        1000,
        3,
        "image",
        _build_budget(
            {
                "base_minutes": 0.5,
                "minutes_per_row": 1 / 50000,
                "base_ram_mb": 256,
                "ram_per_row": 0.001,
                "disk_mb": 10,
                "base_vram_mb": 0,
                "vram_per_row": 0,
                "gpu": False,
                "cuda": None,
            },
            1000,
            3,
            {},
        ),
    )
    # LightGBM is mature (0.95) and dataset is tiny (0.95), so overall
    # confidence stays medium even with poor modality fit (0.5 * 0.25 weight)
    assert conf.score < 0.85
    assert conf.assessment == "medium"


def test_confidence_has_factors():
    conf = _compute_confidence(
        _TABULAR_SPEC,
        "lightgbm",
        891,
        11,
        "tabular",
        _build_budget(
            {
                "base_minutes": 0.5,
                "minutes_per_row": 1 / 50000,
                "base_ram_mb": 256,
                "ram_per_row": 0.001,
                "disk_mb": 10,
                "base_vram_mb": 0,
                "vram_per_row": 0,
                "gpu": False,
                "cuda": None,
            },
            891,
            11,
            {},
        ),
    )
    assert len(conf.factors) >= 4


# ---------------------------------------------------------------------------
# Node/edge structure
# ---------------------------------------------------------------------------


def test_all_expected_nodes_present():
    plan = compile_plan(_TABULAR_SPEC, "job-010")
    expected = {
        "forge_generate",
        "furnace_train",
        "dissect_patch",
        "arbiter_evaluate",
        "harbor_deploy",
        "forge_retry",
    }
    node_ids = set(plan.nodes.keys())
    assert expected.issubset(node_ids), f"Missing nodes: {expected - node_ids}"


def test_all_decision_conditions_present():
    plan = compile_plan(_TABULAR_SPEC, "job-011")
    arbiter_outgoing = [e for e in plan.edges if e.from_node == "arbiter_evaluate"]
    conditions = {e.condition for e in arbiter_outgoing}
    assert "pass" in conditions
    assert "retry" in conditions
    assert "escalate" in conditions


def test_terminal_nodes_reachable():
    plan = compile_plan(_TABULAR_SPEC, "job-012")
    has_complete = any(e.to_node == "__plan_complete__" for e in plan.edges)
    has_failed = any(e.to_node == "__plan_failed__" for e in plan.edges)
    assert has_complete, "No edge to __plan_complete__"
    assert has_failed, "No edge to __plan_failed__"

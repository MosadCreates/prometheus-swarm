"""Unit tests for Forge Engineering Planner."""

import json
from typing import Any

import pytest

from agents.forge.planner import (
    _build_architecture_proposal,
    _estimate_budget,
    _estimate_metric_range,
    _estimate_ram_mb,
    _estimate_training_minutes,
    create_plan,
    format_plan_summary,
)
from agents.forge.tools import _design_header_block, write_training_script


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_BRIEF: dict[str, Any] = {
    "modality": "tabular",
    "task_type": "classification",
    "target_column": "Survived",
    "dataset": {
        "file_path": "/data/titanic.csv",
        "num_rows": 891,
        "num_columns": 11,
    },
    "data_quality": {
        "class_imbalance_ratio": None,
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "data_warnings": [],
    },
    "imbalance_strategy": "none",
}

_SAMPLE_REASONING: dict[str, Any] = {
    "problem_type": {
        "title": "Problem Type Identification",
        "rationale": "Target has 2 unique values and description mentions classification",
        "confidence": 0.95,
        "alternatives": ["classification", "regression"],
        "selected": "classification",
    },
    "data_quality": {
        "title": "Data Quality Assessment",
        "rationale": "No significant data quality issues detected",
        "confidence": 0.95,
        "alternatives": ["clean", "acceptable"],
        "selected": "clean",
    },
    "leakage": {
        "title": "Leakage Detection",
        "rationale": "No obvious leakage sources detected",
        "confidence": 0.90,
        "alternatives": [],
        "selected": "no_leakage_detected",
    },
    "preprocessing": {
        "title": "Preprocessing Strategy",
        "rationale": "Pipeline: median_imputation_numeric -> mode_imputation_categorical -> ordinal_encoding",
        "confidence": 0.88,
        "alternatives": ["passthrough"],
        "selected": "median_imputation_numeric -> mode_imputation_categorical -> ordinal_encoding",
    },
    "architecture": {
        "title": "Architecture Selection",
        "rationale": "Tabular data with 891 rows; LightGBM is fast and handles mixed data types well",
        "confidence": 0.85,
        "alternatives": ["lightgbm", "xgboost"],
        "selected": "lightgbm",
    },
    "validation": {
        "title": "Validation Strategy",
        "rationale": "Moderate dataset (891 rows); stratified 5-fold cross-validation",
        "confidence": 0.85,
        "alternatives": ["train_val_split", "stratified_5fold"],
        "selected": "stratified_5fold",
    },
    "risks": [],
    "overall_confidence": 0.85,
}


# ---------------------------------------------------------------------------
# create_plan — end-to-end
# ---------------------------------------------------------------------------


def test_create_plan_lightgbm_tabular():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    assert plan["architecture_selected"]["name"] == "lightgbm"
    assert len(plan["alternatives"]) >= 1


def test_create_plan_without_reasoning():
    plan = create_plan({}, _SAMPLE_BRIEF)
    assert isinstance(plan["architecture_selected"]["name"], str)
    assert len(plan["alternatives"]) >= 1


def test_create_plan_with_imbalance():
    brief = {
        **_SAMPLE_BRIEF,
        "data_quality": {
            **_SAMPLE_BRIEF["data_quality"],
            "class_imbalance_ratio": 30.0,
        },
    }
    plan = create_plan(_SAMPLE_REASONING, brief)
    mr = plan["architecture_selected"]["expected_metric_range"]
    assert mr is not None
    assert mr[0] < 0.80


def test_create_plan_text_modality():
    brief = {
        **_SAMPLE_BRIEF,
        "modality": "text",
        "dataset": {"num_rows": 5000, "num_columns": 2},
    }
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": "distilbert",
            "alternatives": ["distilbert", "lightgbm_with_tfidf"],
        },
    }
    plan = create_plan(reasoning, brief)
    assert plan["architecture_selected"]["name"] == "distilbert"
    assert plan["computational_budget"]["gpu_required"] is True


def test_create_plan_image_modality():
    brief = {
        **_SAMPLE_BRIEF,
        "modality": "image",
        "dataset": {"num_rows": 10000, "num_columns": 3},
    }
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": "efficientnet",
            "alternatives": ["efficientnet", "resnet"],
        },
    }
    plan = create_plan(reasoning, brief)
    assert plan["architecture_selected"]["name"] == "efficientnet"
    assert plan["computational_budget"]["gpu_required"] is True


def test_create_plan_large_tabular():
    brief = {
        **_SAMPLE_BRIEF,
        "dataset": {"num_rows": 2_000_000, "num_columns": 50},
    }
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": "tabnet",
            "alternatives": ["tabnet", "lightgbm", "xgboost"],
        },
    }
    plan = create_plan(reasoning, brief)
    assert plan["architecture_selected"]["name"] == "tabnet"


def test_plan_is_json_serializable():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    dumped = json.dumps(plan, indent=2)
    loaded = json.loads(dumped)
    assert loaded["architecture_selected"]["name"] == "lightgbm"


def test_alternatives_are_populated():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    assert len(plan["alternatives"]) > 0
    alt_names = [a["name"] for a in plan["alternatives"]]
    assert "xgboost" in alt_names or "lightgbm" in alt_names


# ---------------------------------------------------------------------------
# Architecture proposal fields
# ---------------------------------------------------------------------------


def test_architecture_proposal_has_pros_and_cons():
    proposal = _build_architecture_proposal("lightgbm", "classification", 891, 11, None)
    assert len(proposal.pros) >= 3
    assert len(proposal.cons) >= 1
    assert proposal.expected_training_minutes >= 1
    assert proposal.expected_ram_mb >= 256


def test_architecture_proposal_metric_range():
    proposal = _build_architecture_proposal("lightgbm", "classification", 891, 11, None)
    assert proposal.expected_metric_range is not None
    lo, hi = proposal.expected_metric_range
    assert 0.0 < lo < hi <= 1.0


def test_architecture_proposal_metric_range_with_imbalance():
    proposal = _build_architecture_proposal("lightgbm", "classification", 891, 11, 30.0)
    assert proposal.expected_metric_range is not None
    lo, hi = proposal.expected_metric_range
    assert lo < 0.75


def test_proposal_reason_for_selection():
    proposal = _build_architecture_proposal("lightgbm", "classification", 891, 11, None)
    assert "lightgbm" in proposal.reason_for_selection
    assert "classification" in proposal.reason_for_selection


# ---------------------------------------------------------------------------
# Estimation helpers
# ---------------------------------------------------------------------------


def test_estimate_training_minutes():
    t = _estimate_training_minutes("lightgbm", 1000, 10)
    assert 1 <= t <= 5


def test_estimate_training_minutes_large_data():
    t = _estimate_training_minutes("lightgbm", 2_000_000, 100)
    assert t > 1


def test_estimate_ram_mb():
    r = _estimate_ram_mb("lightgbm", 1000)
    assert 200 <= r <= 400


def test_estimate_ram_mb_distilbert():
    r = _estimate_ram_mb("distilbert", 5000)
    assert r >= 2000


def test_estimate_metric_range_classification():
    r = _estimate_metric_range("lightgbm", "classification", 50000, None)
    assert r is not None
    assert r[0] >= 0.75


def test_estimate_metric_range_regression():
    r = _estimate_metric_range("lightgbm", "regression", 50000, None)
    assert r is not None
    assert r[0] >= 0.65


def test_estimate_metric_range_unknown_arch():
    r = _estimate_metric_range("unknown_model", "classification", 1000, None)
    assert r is not None
    assert len(r) == 2


def test_estimate_budget_gpu_flag():
    budget = _estimate_budget("distilbert", 5000, 2)
    assert budget.gpu_required is True
    assert budget.estimated_training_minutes >= 1


def test_estimate_budget_no_gpu():
    budget = _estimate_budget("lightgbm", 1000, 10)
    assert budget.gpu_required is False


# ---------------------------------------------------------------------------
# format_plan_summary
# ---------------------------------------------------------------------------


def test_format_plan_summary_contains_architecture():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    summary = format_plan_summary(plan)
    assert "lightgbm" in summary
    assert "Architecture:" in summary


def test_format_plan_summary_contains_estimates():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    summary = format_plan_summary(plan)
    assert "training time" in summary.lower()
    assert "memory" in summary.lower()
    assert "Tuning:" in summary


def test_format_plan_summary_gpu_indication():
    brief = {
        **_SAMPLE_BRIEF,
        "modality": "text",
        "dataset": {"num_rows": 5000, "num_columns": 2},
    }
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": "distilbert",
            "alternatives": ["distilbert"],
        },
    }
    plan = create_plan(reasoning, brief)
    summary = format_plan_summary(plan)
    assert "GPU: required" in summary


# ---------------------------------------------------------------------------
# Script header integration
# ---------------------------------------------------------------------------


def test_script_header_includes_design_summary():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    summary = format_plan_summary(plan)
    header = _design_header_block(summary)
    assert "Design Summary:" in header
    assert "lightgbm" in header


def test_script_header_empty_when_no_summary():
    header = _design_header_block(None)
    assert header == ""


def test_script_header_empty_when_empty_string():
    header = _design_header_block("")
    assert header == ""


# ---------------------------------------------------------------------------
# Preprocessing pipeline
# ---------------------------------------------------------------------------


def test_preprocessing_pipeline_from_reasoning():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    pipeline = plan["preprocessing_pipeline"]
    assert len(pipeline) >= 2
    step_names = [s["name"] for s in pipeline]
    assert "median_imputation_numeric" in step_names
    assert "ordinal_encoding" in step_names


def test_preprocessing_pipeline_passthrough():
    reasoning = {
        **_SAMPLE_REASONING,
        "preprocessing": {
            **_SAMPLE_REASONING["preprocessing"],
            "selected": "passthrough",
        },
    }
    plan = create_plan(reasoning, _SAMPLE_BRIEF)
    assert len(plan["preprocessing_pipeline"]) == 1
    assert plan["preprocessing_pipeline"][0]["name"] == "passthrough"


# ---------------------------------------------------------------------------
# Hyperparameter strategy
# ---------------------------------------------------------------------------


def test_hyperparameter_strategy_lightgbm():
    plan = create_plan(_SAMPLE_REASONING, _SAMPLE_BRIEF)
    hp = plan["hyperparameter_strategy"]
    assert hp["approach"] == "optuna_bayesian"
    assert hp["max_trials"] >= 20
    assert "num_leaves" in hp["key_params_to_tune"]


def test_hyperparameter_strategy_distilbert():
    brief = {
        **_SAMPLE_BRIEF,
        "modality": "text",
        "dataset": {"num_rows": 5000, "num_columns": 2},
    }
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": "distilbert",
            "alternatives": ["distilbert"],
        },
    }
    plan = create_plan(reasoning, brief)
    hp = plan["hyperparameter_strategy"]
    assert hp["approach"] == "manual"


# ---------------------------------------------------------------------------
# Fallback plan
# ---------------------------------------------------------------------------


def test_fallback_plan_not_empty():
    plan = create_plan({}, _SAMPLE_BRIEF)
    assert plan["fallback_plan"]
    assert isinstance(plan["fallback_plan"], str)


@pytest.mark.parametrize("arch", ["lightgbm", "xgboost", "tabnet", "distilbert", "efficientnet"])
def test_fallback_plan_for_each_architecture(arch):
    reasoning = {
        **_SAMPLE_REASONING,
        "architecture": {
            **_SAMPLE_REASONING["architecture"],
            "selected": arch,
            "alternatives": [arch],
        },
    }
    plan = create_plan(reasoning, _SAMPLE_BRIEF)
    assert plan["fallback_plan"]
    assert "Fallback" in plan["fallback_plan"]

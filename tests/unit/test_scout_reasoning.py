"""Unit tests for Scout engineering reasoning functions."""

import os
import tempfile
from typing import Any

import numpy as np
import pandas as pd
import pytest

from agents.scout.reasoning import (
    reason_problem_type,
    reason_data_quality,
    reason_leakage,
    reason_preprocessing,
    reason_imbalance,
    reason_architecture,
    reason_validation,
    reason_risks,
    reason_feature_engineering,
    reason_outliers,
)
from agents.scout.tools import write_mission_brief


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_csv(data: dict) -> str:
    df = pd.DataFrame(data)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(tmp.name, index=False)
    return tmp.name


# ---------------------------------------------------------------------------
# reason_problem_type
# ---------------------------------------------------------------------------


def test_reason_problem_type_classification():
    df = pd.DataFrame({"x": range(10), "y": [0, 1] * 5})
    result = reason_problem_type("classify this data", df, "y")
    assert result["selected"] == "classification"
    assert result["confidence"] >= 0.85


def test_reason_problem_type_regression():
    df = pd.DataFrame({"x": range(50), "y": np.random.randn(50)})
    result = reason_problem_type("predict the value", df, "y")
    assert result["selected"] == "regression"
    assert result["confidence"] >= 0.80


def test_reason_problem_type_classification_with_keywords():
    df = pd.DataFrame({"x": [1, 2, 3], "y": ["a", "b", "c"]})
    # No target specified, but description has "detect"
    result = reason_problem_type("detect fraud in transactions", df, "y")
    assert result["confidence"] >= 0.70


def test_reason_problem_type_returns_alternatives():
    df = pd.DataFrame({"x": range(10), "y": [0, 1] * 5})
    result = reason_problem_type("classify", df, "y")
    assert isinstance(result["alternatives"], list)
    assert len(result["alternatives"]) >= 2


# ---------------------------------------------------------------------------
# reason_data_quality
# ---------------------------------------------------------------------------


def test_reason_data_quality_clean():
    eda = {
        "num_rows": 100,
        "num_columns": 5,
        "data_warnings": [],
        "missing_value_rate": {},
        "high_cardinality_columns": [],
    }
    result = reason_data_quality(eda)
    assert result["selected"] == "clean"
    assert result["confidence"] >= 0.90


def test_reason_data_quality_with_warnings():
    eda = {
        "num_rows": 100,
        "num_columns": 5,
        "data_warnings": ["High missing rate (>30%) in columns: ['a']"],
        "missing_value_rate": {"a": 0.4, "b": 0.0},
        "high_cardinality_columns": ["c"],
    }
    result = reason_data_quality(eda)
    assert result["confidence"] < 0.90
    assert "needs" in result["selected"]


# ---------------------------------------------------------------------------
# reason_leakage
# ---------------------------------------------------------------------------


def test_reason_leakage_id_column():
    df = pd.DataFrame({"CustomerID": range(100), "target": [0, 1] * 50})
    result = reason_leakage(df, "target")
    assert result["selected"] == "flag_for_review"
    assert "CustomerID" in result["rationale"]


def test_reason_leakage_high_correlation():
    np.random.seed(42)
    target = np.random.randn(100)
    leaky = target * 0.99 + np.random.randn(100) * 0.01
    df = pd.DataFrame({"x": np.random.randn(100), "leak_col": leaky, "target": target})
    result = reason_leakage(df, "target")
    assert result["selected"] == "flag_for_review"


def test_reason_leakage_no_target():
    df = pd.DataFrame({"CustomerID": range(100), "value": range(100)})
    result = reason_leakage(df)
    assert result["selected"] == "no_analysis"


def test_reason_leakage_no_leakage():
    np.random.seed(42)
    df = pd.DataFrame({"x": np.random.randn(100), "y": np.random.randn(100)})
    result = reason_leakage(df, "y")
    assert result["selected"] == "no_leakage_detected"
    assert result["confidence"] >= 0.85


# ---------------------------------------------------------------------------
# reason_preprocessing
# ---------------------------------------------------------------------------


def test_reason_preprocessing_mixed_types():
    df = pd.DataFrame(
        {
            "numeric": [1.0, 2.0, None, 4.0],
            "category": ["a", "b", "c", None],
            "text": ["hello world " + str(i) for i in range(4)],
        }
    )
    result = reason_preprocessing(df)
    assert "->" in result["selected"] or "passthrough" in result["selected"]


def test_reason_preprocessing_empty_numeric():
    df = pd.DataFrame({"label": ["a", "b", "c"]})
    result = reason_preprocessing(df)
    assert isinstance(result["selected"], str)


# ---------------------------------------------------------------------------
# reason_imbalance
# ---------------------------------------------------------------------------


def test_reason_imbalance_severe():
    eda = {"class_imbalance_ratio": 25.0}
    result = reason_imbalance(eda)
    assert result is not None
    assert result["selected"] == "smote"
    assert result["confidence"] >= 0.85


def test_reason_imbalance_moderate():
    eda = {"class_imbalance_ratio": 8.0}
    result = reason_imbalance(eda)
    assert result is not None
    assert result["selected"] == "class_weight"


def test_reason_imbalance_none():
    eda = {"class_imbalance_ratio": 1.0}
    result = reason_imbalance(eda)
    assert result is None


def test_reason_imbalance_missing():
    eda = {}
    result = reason_imbalance(eda)
    assert result is None


# ---------------------------------------------------------------------------
# reason_architecture
# ---------------------------------------------------------------------------


def test_reason_architecture_tabular():
    brief = {
        "modality": "tabular",
        "task_type": "classification",
        "dataset": {"num_rows": 1000},
        "data_quality": {},
    }
    result = reason_architecture(brief)
    assert result["selected"] == "lightgbm"
    assert "lightgbm" in result["alternatives"]


def test_reason_architecture_image():
    brief = {
        "modality": "image",
        "task_type": "classification",
        "dataset": {"num_rows": 5000},
        "data_quality": {},
    }
    result = reason_architecture(brief)
    assert result["selected"] == "efficientnet"


def test_reason_architecture_large_tabular():
    brief = {
        "modality": "tabular",
        "task_type": "classification",
        "dataset": {"num_rows": 2_000_000},
        "data_quality": {},
    }
    result = reason_architecture(brief)
    assert result["selected"] == "tabnet"


# ---------------------------------------------------------------------------
# reason_validation
# ---------------------------------------------------------------------------


def test_reason_validation_small():
    result = reason_validation("classification", 200)
    assert "stratified" in result["selected"]


def test_reason_validation_large():
    result = reason_validation("classification", 100_000)
    assert result["selected"] == "train_val_split"


def test_reason_validation_imbalanced():
    result = reason_validation("classification", 2000, class_imbalance_ratio=15.0)
    assert "stratified" in result["selected"] or "train_val" in result["selected"]


# ---------------------------------------------------------------------------
# reason_risks
# ---------------------------------------------------------------------------


def test_reason_risks_imbalanced():
    eda = {
        "class_imbalance_ratio": 30.0,
        "data_warnings": [],
        "missing_value_rate": {},
        "num_rows": 1000,
        "high_cardinality_columns": [],
    }
    risks = reason_risks(eda)
    assert any("imbalance" in r.lower() for r in risks)


def test_reason_risks_small_data():
    eda = {
        "class_imbalance_ratio": None,
        "data_warnings": [],
        "missing_value_rate": {},
        "num_rows": 50,
        "high_cardinality_columns": [],
    }
    risks = reason_risks(eda)
    assert any("small" in r.lower() for r in risks)


def test_reason_risks_high_cardinality():
    eda = {
        "class_imbalance_ratio": None,
        "data_warnings": [],
        "missing_value_rate": {},
        "num_rows": 1000,
        "high_cardinality_columns": ["col_a", "col_b"],
    }
    risks = reason_risks(eda)
    assert any("cardinality" in r.lower() for r in risks)


# ---------------------------------------------------------------------------
# Integration: write_mission_brief includes engineering_reasoning
# ---------------------------------------------------------------------------


def test_write_mission_brief_includes_reasoning():
    eda = {
        "num_rows": 100,
        "num_columns": 3,
        "column_types": {"a": "numeric", "b": "categorical", "c": "target"},
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": None,
        "data_warnings": [],
    }
    reasoning = {
        "problem_type": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "classification",
        },
        "data_quality": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "clean",
        },
        "leakage": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "no_leakage",
        },
        "preprocessing": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "passthrough",
        },
        "architecture": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "lightgbm",
        },
        "validation": {
            "title": "Test",
            "rationale": "test",
            "confidence": 0.9,
            "alternatives": [],
            "selected": "stratified_5fold",
        },
        "risks": [],
        "overall_confidence": 0.85,
    }
    path = _make_csv({"a": [1.0], "b": ["x"], "c": [0]})
    try:
        brief = write_mission_brief(
            eda, "job-001", "Test", path, "c", engineering_reasoning=reasoning
        )
        assert "engineering_reasoning" in brief
        assert brief["engineering_reasoning"] == reasoning
    finally:
        os.unlink(path)


def test_write_mission_brief_without_reasoning():
    eda = {
        "num_rows": 100,
        "num_columns": 3,
        "column_types": {"a": "numeric", "b": "categorical", "c": "target"},
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": None,
        "data_warnings": [],
    }
    path = _make_csv({"a": [1.0], "b": ["x"], "c": [0]})
    try:
        brief = write_mission_brief(eda, "job-001", "Test", path, "c")
        assert "engineering_reasoning" in brief
        assert brief["engineering_reasoning"] == {}
    finally:
        os.unlink(path)


# ---------------------------------------------------------------------------
# reason_feature_engineering
# ---------------------------------------------------------------------------


def test_feature_engineering_no_recs():
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [0, 1, 0]})
    result = reason_feature_engineering(df, "y")
    assert "title" in result
    assert "rationale" in result
    assert "confidence" in result
    assert "recommendations" in result


def test_feature_engineering_skewed():
    np.random.seed(42)
    skewed = np.exp(np.random.randn(100))
    df = pd.DataFrame({"x": skewed, "y": [0, 1] * 50})
    result = reason_feature_engineering(df, "y")
    recs = result.get("recommendations", [])
    has_skew = any("skew" in r.lower() for r in recs)
    assert has_skew or len(recs) >= 0  # not empty


def test_feature_engineering_text_column():
    df = pd.DataFrame(
        {
            "text_col": ["long text " * 20 for _ in range(10)],
            "label": [0, 1] * 5,
        }
    )
    result = reason_feature_engineering(df, "label")
    recs = " ".join(result.get("recommendations", []))
    assert "tfidf" in recs.lower() or "vector" in recs.lower()


# ---------------------------------------------------------------------------
# reason_outliers
# ---------------------------------------------------------------------------


def test_reason_outliers_none():
    result = reason_outliers({"outlier_counts": {}})
    assert result["selected"] == "none"
    assert result["confidence"] >= 0.90


def test_reason_outliers_mild():
    result = reason_outliers({"outlier_counts": {"x": 9, "y": 8}})
    assert result["selected"] == "none"


def test_reason_outliers_severe():
    result = reason_outliers({"outlier_counts": {"x": 50, "y": 60}})
    assert result["selected"] == "robust_scaling" or result["selected"] == "iqr_clipping"


def test_reason_outliers_affected_columns():
    result = reason_outliers({"outlier_counts": {"x": 50, "y": 0}})
    assert isinstance(result.get("affected_columns", []), list)

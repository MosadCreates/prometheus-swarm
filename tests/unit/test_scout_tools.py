"""Unit tests for Scout tools."""

import os
import tempfile
import pandas as pd
import numpy as np

from agents.scout.tools import (
    detect_modality,
    run_eda,
    infer_task_type,
    write_mission_brief,
    write_mission_spec,
)


def _make_csv(data: dict) -> str:
    df = pd.DataFrame(data)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
    df.to_csv(tmp.name, index=False)
    return tmp.name


def test_detect_modality_csv():
    path = _make_csv({"a": [1]})
    assert detect_modality(path) == "tabular"
    os.unlink(path)


def test_run_eda_binary_classification():
    data = {
        "feature1": [1.0, 2.0, 3.0, 4.0, 5.0],
        "feature2": ["a", "b", "c", "d", "e"],
        "target": [0, 1, 0, 1, 0],
    }
    path = _make_csv(data)
    result = run_eda(path, target_column="target")

    assert result["num_rows"] == 5
    assert result["num_columns"] == 3
    assert result["column_types"]["target"] == "target"
    assert result["column_types"]["feature1"] == "numeric"
    assert result["column_types"]["feature2"] == "categorical"
    os.unlink(path)


def test_imbalanced_detection():
    data = {
        "x": range(110),
        "y": [0] * 100 + [1] * 10,
    }
    path = _make_csv(data)
    result = run_eda(path, target_column="y")
    assert result["class_imbalance_ratio"] == 10.0
    os.unlink(path)


def test_infer_task_type_regression():
    data = {
        "x": range(50),
        "target": np.random.randn(50).tolist(),
    }
    path = _make_csv(data)
    result = infer_task_type("target", {}, path)
    assert result == "regression"
    os.unlink(path)


def test_write_mission_brief():
    eda = {
        "num_rows": 100,
        "num_columns": 5,
        "column_types": {"a": "numeric", "b": "target"},
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": None,
        "data_warnings": [],
    }
    brief = write_mission_brief(eda, "job-001", "Test problem", "/path/to/data.csv", "b")
    assert brief["job_id"] == "job-001"
    assert brief["task_type"] in ("classification", "regression")
    assert brief["modality"] == "tabular"


# ── Enhanced EDA tests ─────────────────────────────────────────────────


def test_eda_outlier_detection():
    data = {
        "normal": [1.0, 2.0, 3.0, 4.0, 5.0, 1.5, 2.5, 3.5, 4.5, 5.5],
        "has_outliers": [10, 12, 11, 13, 9, 100, 8, 11, 12, 10],
        "target": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
    }
    path = _make_csv(data)
    result = run_eda(path, target_column="target")
    assert "outlier_counts" in result
    assert "duplicate_rows" in result
    assert "numeric_stats" in result
    assert "numeric_columns" in result
    os.unlink(path)


def test_eda_duplicate_detection():
    data = {
        "x": [1, 2, 3, 1, 2],
        "y": ["a", "b", "c", "a", "b"],
    }
    path = _make_csv(data)
    result = run_eda(path)
    assert result["duplicate_rows"] == 2
    os.unlink(path)


def test_eda_numeric_stats():
    np.random.seed(42)
    data = {
        "values": [1.0, 2.0, 3.0, 4.0, 5.0],
        "label": ["a", "b", "c", "d", "e"],
    }
    path = _make_csv(data)
    result = run_eda(path)
    stats = result["numeric_stats"]
    assert "values" in stats
    assert stats["values"]["mean"] == 3.0
    assert stats["values"]["min"] == 1.0
    assert stats["values"]["max"] == 5.0
    assert stats["values"]["unique"] == 5
    os.unlink(path)


def test_eda_correlation_with_target():
    np.random.seed(42)
    x = np.random.randn(100)
    y = x * 0.8 + np.random.randn(100) * 0.2
    data = {"x": x.tolist(), "y": y.tolist()}
    path = _make_csv(data)
    result = run_eda(path, target_column="y")
    assert "correlation_with_target" in result
    assert abs(result["correlation_with_target"]["x"]) > 0.5
    os.unlink(path)


# ── MissionSpecification tests ─────────────────────────────────────────


def test_write_mission_spec_basic():
    eda = {
        "num_rows": 100,
        "num_columns": 5,
        "column_types": {"a": "numeric", "b": "target"},
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": None,
        "data_warnings": [],
        "outlier_counts": {},
        "duplicate_rows": 0,
        "numeric_stats": {},
        "categorical_stats": {},
        "correlation_with_target": {},
        "memory_usage_bytes": 1024,
        "numeric_columns": ["a"],
        "categorical_columns": [],
        "text_columns": [],
    }
    reasoning = {
        "problem_type": {
            "title": "Task",
            "rationale": "test",
            "confidence": 0.9,
            "selected": "classification",
        },
        "architecture": {
            "title": "Arch",
            "rationale": "test",
            "confidence": 0.85,
            "selected": "lightgbm",
            "alternatives": ["xgboost"],
            "expected_metric_range": [0.75, 0.88],
        },
        "overall_confidence": 0.85,
    }
    spec = write_mission_spec(
        eda, "job-001", "Test problem", "/path/to/data.csv", "b", engineering_reasoning=reasoning
    )
    assert spec["spec_version"] == "2.0"
    assert spec["job_id"] == "job-001"
    assert spec["objective"]["task_type"] in ("classification", "regression")
    assert spec["objective"]["modality"] == "tabular"
    assert "dataset_analysis" in spec
    assert "data_quality" in spec
    assert "risks" in spec
    assert "engineering_decisions" in spec
    assert "candidate_models" in spec
    assert "confidence" in spec
    assert "success_criteria" in spec


def test_write_mission_spec_contains_eda_enrichments():
    eda = {
        "num_rows": 100,
        "num_columns": 5,
        "column_types": {"a": "numeric", "b": "target"},
        "missing_value_rate": {"a": 0.0, "b": 0.0},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": 8.0,
        "data_warnings": ["Class imbalance: majority/minority ratio = 8.0"],
        "outlier_counts": {"a": 3},
        "duplicate_rows": 2,
        "numeric_stats": {"a": {"mean": 5.0, "min": 1.0, "max": 10.0}},
        "categorical_stats": {},
        "correlation_with_target": {},
        "memory_usage_bytes": 2048,
        "numeric_columns": ["a"],
        "categorical_columns": [],
        "text_columns": [],
    }
    reasoning = {
        "problem_type": {
            "title": "Task",
            "rationale": "test",
            "confidence": 0.9,
            "selected": "classification",
        },
        "architecture": {
            "title": "Arch",
            "rationale": "test",
            "confidence": 0.85,
            "selected": "lightgbm",
            "alternatives": ["xgboost"],
        },
        "overall_confidence": 0.85,
    }
    spec = write_mission_spec(
        eda, "job-002", "Test", "/path.csv", "b", engineering_reasoning=reasoning
    )
    dq = spec["data_quality"]
    assert dq["class_imbalance_ratio"] == 8.0
    assert dq["outlier_counts"] == {"a": 3}
    assert dq["duplicate_rows"] == 2
    assert len(dq["data_warnings"]) > 0


def test_write_mission_spec_without_reasoning():
    eda = {
        "num_rows": 100,
        "num_columns": 3,
        "column_types": {"a": "numeric", "b": "categorical", "c": "target"},
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "class_imbalance_ratio": None,
        "data_warnings": [],
        "outlier_counts": {},
        "duplicate_rows": 0,
        "numeric_stats": {},
        "categorical_stats": {},
        "correlation_with_target": {},
        "memory_usage_bytes": 512,
        "numeric_columns": ["a"],
        "categorical_columns": ["b"],
        "text_columns": [],
    }
    path = _make_csv({"a": [1.0], "b": ["x"], "c": [0]})
    try:
        spec = write_mission_spec(eda, "job-003", "Test", path, "c")
        assert spec["spec_version"] == "2.0"
        assert spec["candidate_models"]["primary"]["name"] in ("lightgbm", "xgboost")
    finally:
        os.unlink(path)

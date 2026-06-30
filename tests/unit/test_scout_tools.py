"""Unit tests for Scout tools."""

import os
import tempfile
import pandas as pd
import numpy as np

from agents.scout.tools import detect_modality, run_eda, infer_task_type, write_mission_brief


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
    brief = write_mission_brief(
        eda, "job-001", "Test problem", "/path/to/data.csv", "b"
    )
    assert brief["job_id"] == "job-001"
    assert brief["task_type"] in ("classification", "regression")
    assert brief["modality"] == "tabular"

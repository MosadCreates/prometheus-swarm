"""Test that serialize_to_onnx correctly converts a sklearn Pipeline wrapping LightGBM.

Trains a tiny Pipeline (ColumnTransformer + LGBMClassifier) on synthetic data,
pickles it, calls serialize_to_onnx with feature/numeric/categorical columns,
and runs inference via onnxruntime to confirm the multi-input scheme works.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from agents.harbor.tools import serialize_to_onnx


def _train_mini_pipeline() -> tuple[Pipeline, list[str], list[str], list[str]]:
    """Train a tiny Pipeline with mixed numeric/categorical columns."""
    df = pd.DataFrame({
        "Age": [25.0, 30.0, 35.0, 22.0, 40.0],
        "Sex": ["M", "F", "M", "F", "M"],
        "target": [0, 1, 0, 1, 0],
    })
    X = df[["Age", "Sex"]]
    y = df["target"]

    import lightgbm as lgb

    preprocessor = ColumnTransformer([
        ("num", "passthrough", ["Age"]),
        ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["Sex"]),
    ])
    model = Pipeline([
        ("preprocessor", preprocessor),
        ("estimator", lgb.LGBMClassifier(n_estimators=10, random_state=42, verbose=-1)),
    ])
    model.fit(X, y)

    feature_names = ["Age", "Sex"]
    numeric_cols = ["Age"]
    categorical_cols = ["Sex"]
    return model, feature_names, numeric_cols, categorical_cols


def test_serialize_onnx_pipeline_lightgbm():
    """Serialize a Pipeline+LGBMClassifier and verify ONNX inference works."""
    model, feature_names, numeric_cols, categorical_cols = _train_mini_pipeline()

    with tempfile.TemporaryDirectory() as tmpdir:
        pkl_path = os.path.join(tmpdir, "model.pkl")
        joblib.dump(model, pkl_path)

        onnx_path = os.path.join(tmpdir, "model.onnx")
        success, msg = serialize_to_onnx(
            pkl_path,
            onnx_path,
            feature_names=feature_names,
            numeric_cols=numeric_cols,
            categorical_cols=categorical_cols,
        )

        assert success, f"ONNX conversion failed: {msg}"
        assert os.path.exists(onnx_path), f"ONNX file not found at {onnx_path}"

        # Load and run inference
        import onnxruntime as ort

        session = ort.InferenceSession(onnx_path)
        input_name = session.get_inputs()[0].name

        # Test with a single row
        test_input = np.array([[25.0, 0.0]], dtype=np.float32)
        outputs = session.run(None, {input_name: test_input})
        assert len(outputs) > 0
        pred = outputs[0]
        assert pred.shape[0] == 1  # one prediction
        # Output can be 1D (label) or 2D (probabilities) depending on converter
        assert pred.ndim in (1, 2)

        # Test with batch
        batch_input = np.array([[25.0, 0.0], [30.0, 1.0]], dtype=np.float32)
        batch_outputs = session.run(None, {input_name: batch_input})
        assert batch_outputs[0].shape[0] == 2
        assert batch_outputs[0].ndim in (1, 2)

        # Verify preprocess config was saved alongside ONNX
        config_path = onnx_path.replace(".onnx", "_preprocess.json")
        assert os.path.exists(config_path), f"Preprocess config not found at {config_path}"

        import json
        with open(config_path) as f:
            config = json.load(f)
        assert "numeric_cols" in config
        assert "categorical_cols" in config
        assert "cat_encoder" in config


def test_serialize_onnx_bare_lightgbm():
    """Serialize a bare LGBMClassifier (not wrapped in Pipeline)."""
    import lightgbm as lgb

    X = np.array([[25.0, 0.0], [30.0, 1.0], [35.0, 0.0], [22.0, 1.0], [40.0, 0.0]], dtype=np.float32)
    y = np.array([0, 1, 0, 1, 0])

    model = lgb.LGBMClassifier(n_estimators=10, random_state=42, verbose=-1)
    model.fit(X, y)

    with tempfile.TemporaryDirectory() as tmpdir:
        pkl_path = os.path.join(tmpdir, "model.pkl")
        joblib.dump(model, pkl_path)

        onnx_path = os.path.join(tmpdir, "model.onnx")
        success, msg = serialize_to_onnx(pkl_path, onnx_path)
        assert success, f"Bare LightGBM ONNX conversion failed: {msg}"
        assert os.path.exists(onnx_path)

        import onnxruntime as ort
        session = ort.InferenceSession(onnx_path)
        test_input = np.array([[25.0, 0.0]], dtype=np.float32)
        outputs = session.run(None, {session.get_inputs()[0].name: test_input})
        assert outputs[0].shape[0] == 1


def test_serialize_onnx_fails_on_missing_checkpoint():
    """serialize_to_onnx returns (False, ...) when checkpoint does not exist."""
    success, msg = serialize_to_onnx(
        "/nonexistent/path.pkl",
        "/tmp/out.onnx",
    )
    assert not success
    assert "not found" in msg

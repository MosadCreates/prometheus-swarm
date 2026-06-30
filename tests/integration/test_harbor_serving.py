"""Integration test: Harbor generated FastAPI app serves predictions correctly.

Trains a tiny sklearn Pipeline (ColumnTransformer + LGBMClassifier), generates
a FastAPI serving app via Harbor's generate_fastapi_app, loads it via Starlette's
TestClient (no real server needed), sends /predict requests, and verifies responses.
"""

import os
import sys
import tempfile

import joblib
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from agents.harbor.tools import generate_fastapi_app, serialize_to_onnx


@pytest.fixture(scope="module")
def model_and_serving():
    """Train a tiny sklearn Pipeline and generate a FastAPI serving app dir."""
    import lightgbm as lgb

    df = pd.DataFrame(
        {
            "Age": [25.0, 30.0, 35.0, 22.0, 40.0, 28.0, 33.0, 45.0, 27.0, 38.0],
            "Sex": ["M", "F", "M", "F", "M", "F", "M", "F", "M", "F"],
            "target": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        }
    )
    X = df[["Age", "Sex"]]
    y = df["target"]

    preprocessor = ColumnTransformer(
        [
            ("num", "passthrough", ["Age"]),
            ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), ["Sex"]),
        ]
    )
    model = Pipeline(
        [
            ("preprocessor", preprocessor),
            ("estimator", lgb.LGBMClassifier(n_estimators=10, random_state=42, verbose=-1)),
        ]
    )
    model.fit(X, y)
    return model


@pytest.fixture(scope="module")
def serving_dir(model_and_serving):
    """Create a serving directory with model + generated FastAPI app."""
    tmpdir = tempfile.mkdtemp()

    pkl_path = os.path.join(tmpdir, "model.pkl")
    joblib.dump(model_and_serving, pkl_path)

    onnx_path = os.path.join(tmpdir, "model.onnx")
    success, msg = serialize_to_onnx(
        pkl_path,
        onnx_path,
        feature_names=["Age", "Sex"],
        numeric_cols=["Age"],
        categorical_cols=["Sex"],
    )

    model_format = "onnx" if success else "pickle"
    model_path = onnx_path if success else pkl_path

    generate_fastapi_app(
        model_path=os.path.abspath(model_path),
        output_dir=tmpdir,
        model_format=model_format,
        feature_names=["Age", "Sex"],
        numeric_cols=["Age"],
        categorical_cols=["Sex"],
    )

    return tmpdir, model_format


@pytest.fixture(scope="module")
def test_client(serving_dir):
    """Load the generated app via TestClient with startup events."""
    tmpdir, _ = serving_dir

    import importlib.util
    import sys

    app_path = os.path.join(tmpdir, "app.py")
    spec = importlib.util.spec_from_file_location("generated_app", app_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generated_app"] = mod
    spec.loader.exec_module(mod)

    from starlette.testclient import TestClient

    with TestClient(mod.app) as client:
        yield client


class TestHarborServing:
    def test_health_endpoint(self, test_client):
        r = test_client.get("/health")
        assert r.status_code == 200
        data = r.json()
        # Accept either "healthy" or "ok" for compatibility
        assert data.get("status") in ("healthy", "ok")

    def test_predict_single(self, test_client):
        r = test_client.post("/predict", json={"Age": 25.0, "Sex": "M"})
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        assert "predictions" in data

    def test_predict_batch(self, test_client):
        r = test_client.post(
            "/predict",
            json=[
                {"Age": 25.0, "Sex": "M"},
                {"Age": 30.0, "Sex": "F"},
            ],
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        data = r.json()
        predictions = data.get("predictions", [])
        assert len(predictions) == 2

    def test_invalid_input_returns_error(self, test_client):
        r = test_client.post("/predict", json={"bad_key": "not_a_number"})
        # Should return 400 or higher — missing required columns
        assert r.status_code >= 400

    def test_metrics_endpoint(self, test_client):
        r = test_client.get("/metrics")
        assert r.status_code == 200
        assert "prometheus" in r.text.lower() or "#" in r.text or "help" in r.text.lower()

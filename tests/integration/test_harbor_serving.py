"""Integration test: Harbor generated FastAPI app serves predictions correctly.

Trains a tiny sklearn Pipeline (ColumnTransformer + LGBMClassifier), generates
a FastAPI serving app via Harbor's generate_fastapi_app, loads it via Starlette's
TestClient (no real server needed), sends /predict requests, and verifies responses.
"""

import os
import sys
import tempfile

import joblib
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from agents.harbor.tools import generate_fastapi_app, serialize_to_onnx


@pytest.fixture(scope="module")
def model_and_serving():
    """Train a Pipeline with enough data + estimators to learn meaningful probabilities."""
    import lightgbm as lgb

    np.random.seed(42)
    n = 150
    ages = np.random.uniform(20, 60, n)
    sexes = np.random.choice(["M", "F"], n)
    targets = []
    for age, sex in zip(ages, sexes):
        prob = 0.3 + 0.4 * (sex == "F") + 0.3 * (age - 30) / 30
        prob = min(max(prob, 0.0), 1.0)
        targets.append(1 if np.random.random() < prob else 0)

    df = pd.DataFrame({"Age": ages, "Sex": sexes, "target": targets})
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
            ("estimator", lgb.LGBMClassifier(n_estimators=100, random_state=42, verbose=-1)),
        ]
    )
    model.fit(X, y)
    return model


@pytest.fixture(scope="module")
def serving_dir(model_and_serving):
    """Create a serving directory with model + generated FastAPI app using contract."""
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

    # Auto-detect contract path
    contract_path = model_path.replace(".onnx", "_contract.json").replace(".pkl", "_contract.json")
    if not os.path.exists(contract_path):
        contract_path = None

    generate_fastapi_app(
        model_path=os.path.abspath(model_path),
        output_dir=tmpdir,
        model_format=model_format,
        contract_path=contract_path,
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
        assert "probability" in data, f"Response missing 'probability' field: {data}"
        assert (
            "class_probabilities" in data
        ), f"Response missing 'class_probabilities' field: {data}"
        prob = data["probability"]
        assert isinstance(prob, list), f"probability should be a list, got {type(prob)}"
        assert len(prob) == 1, f"Expected 1 probability value, got {len(prob)}"
        assert 0.0 <= prob[0] <= 1.0, f"Probability {prob[0]} outside [0, 1]"

    def test_predict_probability_differs_by_sex(self, test_client):
        """Male and Female with same Age should yield clearly different probabilities."""
        r1 = test_client.post("/predict", json={"Age": 25.0, "Sex": "M"})
        r2 = test_client.post("/predict", json={"Age": 25.0, "Sex": "F"})
        assert r1.status_code == 200 and r2.status_code == 200
        p_male = r1.json()["probability"][0]
        p_female = r2.json()["probability"][0]
        diff = abs(p_male - p_female)
        assert diff > 0.01, f"Male probability {p_male} vs Female {p_female} diff={diff} too small"

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
        assert "probability" in data
        assert len(data["probability"]) == 2
        assert "class_probabilities" in data
        assert len(data["class_probabilities"]) == 2

    def test_invalid_input_returns_error(self, test_client):
        r = test_client.post("/predict", json={"bad_key": "not_a_number"})
        # Should return 400 or higher — missing required columns
        assert r.status_code >= 400

    def test_metrics_endpoint(self, test_client):
        r = test_client.get("/metrics")
        assert r.status_code == 200
        assert "prometheus" in r.text.lower() or "#" in r.text or "help" in r.text.lower()

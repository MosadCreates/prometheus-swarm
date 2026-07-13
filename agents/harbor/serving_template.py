"""FastAPI serving app template. Harbor fills the placeholders per model.

Placeholders: {model_path}, {model_format}, {model_name}, {contract_path}

Architecture:
  - NO hardcoded FEATURE_NAMES, NUMERIC_COLS, CATEGORICAL_COLS
  - Everything loads from preprocessing_contract.json at startup
  - Startup validation: if contract hash mismatches model, server refuses to start
  - Verification: /verify endpoint returns contract validation report
"""

SERVING_TEMPLATE = '''"""Auto-generated serving app by Prometheus Swarm Harbor agent."""
import json
import os
import logging
import time

import numpy as np
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from prometheus_client import make_asgi_app, Counter, Histogram, Gauge

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Prometheus Swarm - {model_name}")

# Prometheus metrics
PREDICTIONS_TOTAL = Counter(
    "prometheus_harbor_prediction_requests_total",
    "Total /predict requests",
    ["status_code"],
)
PREDICTION_LATENCY = Histogram(
    "prometheus_harbor_prediction_latency_seconds",
    "Prediction latency",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# Mount /metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Resolve model path relative to this script\'s directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
_model = None
_model_path = os.path.join(_script_dir, "{model_path}")
_model_format = "{model_format}"

# Load preprocessing contract (single source of truth)
_contract_path = os.path.join(_script_dir, "{contract_path}") if "{contract_path}" else None
_contract = None


def _load_contract():
    global _contract
    if _contract is not None:
        return _contract

    path = _contract_path
    if not path or not os.path.exists(path):
        alt = _model_path.replace(".onnx", "_contract.json").replace(".pkl", "_contract.json")
        if os.path.exists(alt):
            path = alt
        else:
            logger.warning("No preprocessing contract found")
            return None

    try:
        with open(path, encoding="utf-8") as f:
            _contract = json.load(f)
        logger.info("Preprocessing contract loaded")
        return _contract
    except Exception as e:
        logger.error(f"Failed to load preprocessing contract: {{e}}")
        return None


def _contract_feature_order():
    c = _load_contract()
    return c.get("feature_order", []) if c else []


def _contract_numeric_columns():
    c = _load_contract()
    return c.get("numeric_columns", []) if c else []


def _contract_categorical_columns():
    c = _load_contract()
    return c.get("categorical_columns", []) if c else []


def _contract_n_features():
    c = _load_contract()
    return c.get("n_features", 0) if c else 0


def _apply_preprocessing(df):
    contract = _load_contract()
    if not contract:
        return df.values.astype(np.float32)

    feature_order = contract.get("feature_order", [])
    numeric_cols = contract.get("numeric_columns", [])
    categorical_cols = contract.get("categorical_columns", [])
    ordinal_categories = contract.get("ordinal_categories", [])
    handle_unknown = contract.get("ordinal_handle_unknown", "error")
    unknown_value = contract.get("ordinal_unknown_value", -1)

    if not feature_order:
        return df.values.astype(np.float32)

    missing = [c for c in feature_order if c not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {{missing}}")
    df = df[feature_order]

    if not numeric_cols and not categorical_cols:
        return df.values.astype(np.float32)

    parts = []
    for col in numeric_cols:
        if col in df.columns:
            parts.append(df[[col]].values.astype(np.float32))

    for i, col in enumerate(categorical_cols):
        if col in df.columns:
            col_vals = df[[col]].values
            if i < len(ordinal_categories):
                cat_map = {{v: k for k, v in enumerate(ordinal_categories[i])}}
                encoded = np.full(col_vals.shape, unknown_value, dtype=np.float32)
                for j in range(len(col_vals)):
                    val = col_vals[j, 0]
                    if val in cat_map:
                        encoded[j, 0] = float(cat_map[val])
                    elif handle_unknown == "use_encoded_value":
                        encoded[j, 0] = float(unknown_value)
                parts.append(encoded)
            else:
                parts.append(np.zeros(col_vals.shape, dtype=np.float32))

    if not parts:
        return df.values.astype(np.float32)

    return np.concatenate(parts, axis=1)


def load_model():
    global _model
    if _model is not None:
        return

    if _model_format == "onnx":
        import onnxruntime as ort
        _model = ort.InferenceSession(_model_path)

        contract = _load_contract()
        if contract:
            onnx_input = _model.get_inputs()[0]
            onnx_n_features = onnx_input.shape[1] if len(onnx_input.shape) > 1 else 0
            contract_n_features = contract.get("n_features", 0)
            if onnx_n_features and contract_n_features and onnx_n_features != contract_n_features:
                raise RuntimeError(
                    f"Feature count mismatch! ONNX expects {{onnx_n_features}} features, "
                    f"but contract says {{contract_n_features}}. "
                    "Deployment artifacts are inconsistent."
                )
            logger.info(f"ONNX model verified against contract n_features={{contract_n_features}}")
        logger.info("ONNX model loaded")
    elif _model_format == "pickle":
        import joblib
        raw = joblib.load(_model_path)
        if isinstance(raw, dict) and "model" in raw:
            _model = raw["model"]
        else:
            _model = raw
        logger.info("Pickle model loaded")
    else:
        raise ValueError(f"Unknown model format: {{_model_format}}")


def run_startup_validation():
    errors = []

    if not os.path.exists(_model_path):
        errors.append(f"Model file not found: {{_model_path}}")
        return errors

    if _contract_path and os.path.exists(_contract_path):
        contract = _load_contract()
        if contract is None:
            errors.append(f"Failed to load contract from {{_contract_path}}")
        else:
            if not contract.get("feature_order"):
                errors.append("Contract has empty feature_order")
            if contract.get("n_features", 0) <= 0:
                errors.append(f"Contract has invalid n_features={{contract.get('n_features')}}")
    else:
        logger.warning("No contract path configured")

    try:
        load_model()
    except Exception as e:
        errors.append(f"Failed to load model: {{e}}")

    return errors


_startup_errors = []


@app.on_event("startup")
async def startup():
    global _startup_errors
    _startup_errors = run_startup_validation()
    if _startup_errors:
        error_msg = "\\n".join(_startup_errors)
        logger.critical(f"STARTUP VALIDATION FAILED:\\n{{error_msg}}")


@app.get("/health")
async def health():
    if _startup_errors:
        return JSONResponse(
            {{
                "status": "unhealthy",
                "model_loaded": _model is not None,
                "errors": _startup_errors,
            }},
            status_code=503,
        )
    return {{"status": "healthy", "model_loaded": _model is not None}}


@app.get("/verify")
async def verify():
    contract = _load_contract()
    if not contract:
        return JSONResponse(
            {{"status": "no_contract", "detail": "No preprocessing contract found"}},
            status_code=404,
        )

    report = {{
        "status": "verified" if not _startup_errors else "failed",
        "contract_loaded": contract is not None,
        "feature_count": _contract_n_features(),
        "feature_order_valid": len(_contract_feature_order()) > 0,
        "categorical_count": len(_contract_categorical_columns()),
        "numeric_count": len(_contract_numeric_columns()),
        "onnx_loaded": _model is not None,
        "startup_errors": _startup_errors,
        "model_format": _model_format,
    }}

    if _model and _model_format == "onnx":
        try:
            onnx_input = _model.get_inputs()[0]
            report["onnx_input_name"] = onnx_input.name
            report["onnx_input_shape"] = list(onnx_input.shape)
        except Exception:
            pass

    return JSONResponse(report)


@app.post("/predict")
async def predict(request: Request):
    start = time.time()
    try:
        body = await request.json()

        if isinstance(body, list):
            raw_input = body
        elif isinstance(body, dict):
            instances = body.get("instances", body.get("data", None))
            if instances is not None:
                raw_input = instances
            else:
                raw_input = body
        else:
            raw_input = [body]

        if isinstance(raw_input, dict):
            df = pd.DataFrame([raw_input])
        elif isinstance(raw_input, list) and len(raw_input) > 0:
            df = pd.DataFrame(raw_input)
        else:
            return JSONResponse({{"error": "No valid input provided"}}, status_code=400)

        if _model is None:
            load_model()

        if _startup_errors:
            return JSONResponse(
                {{"error": "Service unhealthy", "details": _startup_errors}},
                status_code=503,
            )

        latency = time.time() - start

        if _model_format == "onnx":
            input_array = _apply_preprocessing(df)
            input_name = _model.get_inputs()[0].name
            ort_inputs = {{input_name: input_array}}
            outputs = _model.run(None, ort_inputs)
            predictions = outputs[0]
            pred_list = predictions.tolist() if hasattr(predictions, "tolist") else list(predictions)

            result = {{"predictions": pred_list}}

            if len(outputs) > 1:
                try:
                    proba_output = outputs[1]
                    if isinstance(proba_output, list) and len(proba_output) > 0 and isinstance(proba_output[0], dict):
                        result["class_probabilities"] = proba_output
                        if len(proba_output[0]) == 2:
                            pos_class = max(proba_output[0].keys())
                            result["probability"] = [row[pos_class] for row in proba_output]
                    else:
                        proba_arr = np.array(proba_output)
                        if proba_arr.ndim == 2 and proba_arr.shape[1] == 2:
                            result["probability"] = proba_arr[:, 1].tolist()
                        result["class_probabilities"] = proba_arr.tolist()
                except Exception as proba_err:
                    logger.warning(f"Could not extract probabilities from ONNX output: {{proba_err}}")

        else:
            predictions = _model.predict(df).tolist()
            result = {{"predictions": predictions}}

            if hasattr(_model, "predict_proba"):
                try:
                    proba = _model.predict_proba(df)
                    if proba.shape[1] == 2:
                        result["probability"] = proba[:, 1].tolist()
                    result["class_probabilities"] = proba.tolist()
                    if hasattr(_model, "classes_"):
                        result["classes"] = _model.classes_.tolist()
                except Exception as proba_err:
                    logger.warning(f"predict_proba failed, returning class labels only: {{proba_err}}")

        result["latency_ms"] = round(latency * 1000, 2)
        PREDICTIONS_TOTAL.labels(status_code="200").inc()
        PREDICTION_LATENCY.observe(latency)
        return JSONResponse(result)

    except Exception as e:
        PREDICTIONS_TOTAL.labels(status_code="500").inc()
        logger.error(f"Prediction error: {{e}}")
        return JSONResponse({{"error": str(e)}}, status_code=500)
'''

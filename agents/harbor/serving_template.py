"""FastAPI serving app template. Harbor fills the placeholders per model.

Placeholders: {model_path}, {model_format}, {model_name},
              {feature_names}, {numeric_cols}, {categorical_cols}
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

# Resolve model path relative to this script's directory
_script_dir = os.path.dirname(os.path.abspath(__file__))
_model = None
_model_path = os.path.join(_script_dir, "{model_path}")
_model_format = "{model_format}"

# Column configuration
FEATURE_NAMES = {feature_names}
NUMERIC_COLS = {numeric_cols}
CATEGORICAL_COLS = {categorical_cols}

# Preprocessing config (loaded from companion JSON file for Pipeline-extracted ONNX models)
_preprocess_config = None


def _load_preprocess_config():
    global _preprocess_config
    config_path = _model_path.replace(".onnx", "_preprocess.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            _preprocess_config = json.load(f)
        logger.info(f"Preprocessing config loaded from {{config_path}}")


def _apply_preprocessing(df: pd.DataFrame) -> np.ndarray:
    """Apply preprocessing to match what the training Pipeline's ColumnTransformer did.

    Steps:
    1. Reorder columns to match FEATURE_NAMES
    2. Encode categorical columns with OrdinalEncoder mappings
    3. Combine numeric + encoded categorical into a single float array
    """
    if FEATURE_NAMES:
        missing = [c for c in FEATURE_NAMES if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns: {{missing}}")
        df = df[FEATURE_NAMES]

    config = _preprocess_config or {{}}
    numeric_cols = config.get("numeric_cols", NUMERIC_COLS)
    categorical_cols = config.get("categorical_cols", CATEGORICAL_COLS)

    if not numeric_cols and not categorical_cols:
        return df.values.astype(np.float32)

    parts = []
    for col in (numeric_cols or []):
        if col in df.columns:
            parts.append(df[[col]].values.astype(np.float32))

    cat_encoder = config.get("cat_encoder")
    if cat_encoder and categorical_cols:
        known_categories = cat_encoder.get("categories", [])
        unknown_value = cat_encoder.get("unknown_value", -1)
        for i, col in enumerate(categorical_cols):
            if col in df.columns:
                col_vals = df[[col]].values
                if i < len(known_categories):
                    cat_map = {{v: k for k, v in enumerate(known_categories[i])}}
                    encoded = np.full(col_vals.shape, unknown_value, dtype=np.float32)
                    for j in range(len(col_vals)):
                        val = col_vals[j, 0]
                        if val in cat_map:
                            encoded[j, 0] = float(cat_map[val])
                    parts.append(encoded)
                else:
                    parts.append(np.zeros(col_vals.shape, dtype=np.float32))
    elif categorical_cols:
        for col in categorical_cols:
            if col in df.columns:
                parts.append(np.zeros((len(df), 1), dtype=np.float32))

    if not parts:
        return df.values.astype(np.float32)

    return np.concatenate(parts, axis=1)


def load_model():
    global _model
    if _model_format == "onnx":
        import onnxruntime as ort
        _model = ort.InferenceSession(_model_path)
        _load_preprocess_config()
        logger.info(f"ONNX model loaded from {{_model_path}}")
    elif _model_format == "pickle":
        import joblib
        raw = joblib.load(_model_path)
        if isinstance(raw, dict) and "model" in raw:
            _model = raw["model"]
        else:
            _model = raw
        logger.info(f"Pickle model loaded from {{_model_path}}")
    else:
        raise ValueError(f"Unknown model format: {{_model_format}}")


@app.on_event("startup")
async def startup():
    load_model()


@app.get("/health")
async def health():
    return {{"status": "healthy", "model_loaded": _model is not None}}


@app.post("/predict")
async def predict(request: Request):
    start = time.time()
    try:
        body = await request.json()

        # Handle both batch (list) and single (dict) inputs
        if isinstance(body, list):
            raw_input = body
        elif isinstance(body, dict):
            # Try body["instances"] first for ML serving convention, else full body
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
            # Lazy-load model if startup event didn't trigger (e.g. in tests)
            load_model()

        if _model_format == "onnx":
            input_array = _apply_preprocessing(df)
            input_name = _model.get_inputs()[0].name
            ort_inputs = {{input_name: input_array}}
            predictions = _model.run(None, ort_inputs)[0]
        else:
            predictions = _model.predict(df).tolist()

        latency = time.time() - start
        PREDICTIONS_TOTAL.labels(status_code="200").inc()
        PREDICTION_LATENCY.observe(latency)

        pred_list = predictions.tolist() if hasattr(predictions, "tolist") else predictions
        return JSONResponse({{
            "predictions": pred_list,
            "latency_ms": round(latency * 1000, 2),
        }})

    except Exception as e:
        PREDICTIONS_TOTAL.labels(status_code="500").inc()
        logger.error(f"Prediction error: {{e}}")
        return JSONResponse({{"error": str(e)}}, status_code=500)
'''

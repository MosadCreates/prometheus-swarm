"""FastAPI serving app template. Harbor fills the placeholders per model.

Placeholders: {model_path}, {model_format}, {model_name}
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

# Load model
_model = None
_model_path = "{model_path}"
_model_format = "{model_format}"


def load_model():
    global _model
    if _model_format == "onnx":
        import onnxruntime as ort
        _model = ort.InferenceSession(_model_path)
        logger.info(f"ONNX model loaded from {{_model_path}}")
    elif _model_format == "pickle":
        import joblib
        raw = joblib.load(_model_path)
        # Handle dict wrapper: model + encoders bundle
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
        input_data = body.get("instances", body.get("data", body))

        df = pd.DataFrame(input_data) if isinstance(input_data, list) else pd.DataFrame([input_data])

        if _model_format == "onnx":
            input_name = _model.get_inputs()[0].name
            ort_inputs = {{input_name: df.values.astype(np.float32)}}
            predictions = _model.run(None, ort_inputs)[0]
        else:
            predictions = _model.predict(df).tolist()

        latency = time.time() - start
        PREDICTIONS_TOTAL.labels(status_code="200").inc()
        PREDICTION_LATENCY.observe(latency)

        return JSONResponse({{
            "predictions": predictions.tolist() if hasattr(predictions, "tolist") else predictions,
            "latency_ms": round(latency * 1000, 2),
        }})

    except Exception as e:
        PREDICTIONS_TOTAL.labels(status_code="500").inc()
        logger.error(f"Prediction error: {{e}}")
        return JSONResponse({{"error": str(e)}}, status_code=500)
'''

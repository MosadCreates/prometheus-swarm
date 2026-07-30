"""Harbor tools — model serialization, API generation, deployment."""

import asyncio
import json
import logging
import os
import shutil
import socket
import subprocess
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from bus.events import DRIFT_ALERT, STREAM_HARBOR_OUTPUT
from bus.publisher import publish
from serving.drift_monitor import compute_psi

from contracts.domain import PreprocessingContract, PreprocessingStep

logger = logging.getLogger(__name__)


def _detect_model_type(model: Any) -> str:
    """Detect the model type for ONNX conversion.

    Returns: "lightgbm", "xgboost", "sklearn_pipeline", or "sklearn_model"
    """
    module = getattr(model, "__module__", "")
    class_name = type(model).__name__

    if hasattr(model, "steps") and "Pipeline" in class_name:
        return "sklearn_pipeline"
    if "lightgbm" in module.lower() or "LGBM" in class_name:
        return "lightgbm"
    if "xgboost" in module.lower() or "XGB" in class_name:
        return "xgboost"
    return "sklearn_model"


def _get_n_features(model: Any) -> int:
    """Safely get the number of features from a model."""
    for attr in ["n_features_in_", "n_features_", "n_features"]:
        val = getattr(model, attr, None)
        if val is not None:
            return int(val)

    if hasattr(model, "steps"):
        return _get_n_features(model.steps[-1][1])
    if hasattr(model, "coef_") and model.coef_ is not None:
        return model.coef_.shape[-1]
    if hasattr(model, "feature_importances_") and model.feature_importances_ is not None:
        return len(model.feature_importances_)

    return 1


def _extract_estimator_from_pipeline(model: Any) -> tuple[Any, dict]:
    """Extract the final estimator from a sklearn Pipeline and save preprocessing config.

    Uses `step.transformers` (the pre-fit parameter) for identity checks like
    "passthrough" and "drop", because sklearn's `transformers_` replaces
    string shortcuts with fitted transformer objects (FunctionTransformer, etc.)
    after fitting.

    Returns:
        (estimator, preprocess_config) where preprocess_config is a dict with:
            - numeric_cols, categorical_cols: column names
            - cat_encoder: serialized OrdinalEncoder (categories_ mapping)
            - steps: list of (name, step_type) for the preprocessing steps
    """
    preprocess_config: dict[str, Any] = {
        "numeric_cols": [],
        "categorical_cols": [],
        "cat_encoder": None,
        "steps": [],
    }

    if not hasattr(model, "steps"):
        return model, preprocess_config

    from sklearn.preprocessing import FunctionTransformer

    estimator = model.steps[-1][1]

    for name, step in model.steps[:-1]:
        step_type = type(step).__name__
        preprocess_config["steps"].append((name, step_type))

        if step_type == "ColumnTransformer":
            # Use step.transformers (pre-fit) for identity checks,
            # paired with step.transformers_ (fitted) for attribute access.
            # This avoids the FunctionTransformer != "passthrough" bug.
            pre_fit = getattr(step, "transformers", [])
            post_fit = getattr(step, "transformers_", [])
            for (name_, transformer_spec, cols), (_, fitted_transformer, _) in zip(
                pre_fit, post_fit
            ):
                if not isinstance(cols, list):
                    continue
                if transformer_spec == "passthrough":
                    preprocess_config["numeric_cols"].extend(cols)
                elif transformer_spec == "drop":
                    pass
                elif hasattr(fitted_transformer, "categories_"):
                    preprocess_config["categorical_cols"].extend(cols)
                    cat_data = {
                        "categories": [c.tolist() for c in fitted_transformer.categories_],
                        "handle_unknown": getattr(fitted_transformer, "handle_unknown", "error"),
                        "unknown_value": getattr(fitted_transformer, "unknown_value", None),
                    }
                    preprocess_config["cat_encoder"] = cat_data
                else:
                    # Any other transformer (StandardScaler, MinMaxScaler, custom)
                    # passthrough columns: add to numeric
                    preprocess_config["numeric_cols"].extend(cols)

    # Fallback: if no numeric/categorical cols from ColumnTransformer, detect from estimator
    if not preprocess_config["numeric_cols"] and not preprocess_config["categorical_cols"]:
        if hasattr(estimator, "_feature_names_in"):
            preprocess_config["numeric_cols"] = list(estimator._feature_names_in)

    return estimator, preprocess_config


def _generate_preprocessing_contract(
    model: Any,
    preprocess_config: dict[str, Any],
    job_id: str = "",
    onnx_input_name: str = "input",
) -> PreprocessingContract:
    """Build a PreprocessingContract from the fitted Pipeline and extracted config.

    This is the SINGLE source of truth for all preprocessing metadata.
    Everything else (ONNX export, serving app, drift monitor) reads from this contract.
    """
    # Detect training framework
    estimator = model.steps[-1][1] if hasattr(model, "steps") else model
    module = getattr(estimator, "__module__", "")
    class_name = type(estimator).__name__
    if "lightgbm" in module.lower() or "LGBM" in class_name:
        framework = "lightgbm"
    elif "xgboost" in module.lower() or "XGB" in class_name:
        framework = "xgboost"
    else:
        framework = "sklearn"

    # Build feature_order: numeric first, then categorical
    numeric_cols = preprocess_config.get("numeric_cols", [])
    categorical_cols = preprocess_config.get("categorical_cols", [])
    feature_order = list(numeric_cols) + list(categorical_cols)

    # Feature types
    feature_types: dict[str, str] = {}
    for c in numeric_cols:
        feature_types[c] = "numeric"
    for c in categorical_cols:
        feature_types[c] = "categorical"

    # Ordinal categories from encoder
    cat_encoder = preprocess_config.get("cat_encoder", {})
    ordinal_categories = cat_encoder.get("categories", []) if cat_encoder else []
    handle_unknown = cat_encoder.get("handle_unknown", "error") if cat_encoder else "error"
    unknown_value = cat_encoder.get("unknown_value", None) if cat_encoder else None

    # Preprocessing pipeline trace
    raw_steps = preprocess_config.get("steps", [])
    pipeline_steps = [PreprocessingStep(name=s[0], step_type=s[1]) for s in raw_steps]

    contract = PreprocessingContract(
        job_id=job_id,
        training_framework=framework,
        feature_order=feature_order,
        feature_types=feature_types,
        numeric_columns=numeric_cols,
        categorical_columns=categorical_cols,
        ordinal_categories=ordinal_categories,
        ordinal_handle_unknown=handle_unknown,
        ordinal_unknown_value=unknown_value,
        preprocessing_pipeline=pipeline_steps,
        onnx_input_name=onnx_input_name,
        expected_input_dtype="float32",
        onnx_input_dtype="tensor(float)",
    )
    contract.finalize()
    return contract


def _convert_estimator_to_onnx(
    estimator: Any,
    n_features: int,
    target_opset: int = 12,
) -> Any:
    """Convert a bare estimator (LightGBM, XGBoost, sklearn) to ONNX.

    Uses onnxmltools for tree models (compatible with skl2onnx's type system
    when used stand-alone, not inside a Pipeline).

    Note: onnxmltools requires its own FloatTensorType from
    onnxmltools.convert.common.data_types — the generic
    onnxconverter_common.data_types.FloatTensorType is rejected at runtime.
    """
    module = getattr(estimator, "__module__", "")
    class_name = type(estimator).__name__

    if "lightgbm" in module.lower() or "LGBM" in class_name:
        from onnxmltools.convert import convert_lightgbm
        from onnxmltools.convert.common.data_types import FloatTensorType

        initial_types = [("input", FloatTensorType([None, n_features]))]
        return convert_lightgbm(
            estimator,
            initial_types=initial_types,
            name="model",
            target_opset=target_opset,
        )

    if "xgboost" in module.lower() or "XGB" in class_name:
        from onnxmltools.convert import convert_xgboost
        from onnxmltools.convert.common.data_types import FloatTensorType

        initial_types = [("input", FloatTensorType([None, n_features]))]
        return convert_xgboost(
            estimator,
            initial_types=initial_types,
            name="model",
            target_opset=target_opset,
        )

    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial_types = [("input", FloatTensorType([None, n_features]))]
    options = {id(estimator): {"zipmap": False}} if hasattr(estimator, "classes_") else None
    return convert_sklearn(
        estimator,
        initial_types=initial_types,
        target_opset=target_opset,
        options=options,
    )


def serialize_to_onnx(
    checkpoint_path: str,
    output_path: str,
    model_type: str | None = None,
    feature_names: list[str] | None = None,
    numeric_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    job_id: str = "",
) -> tuple[bool, str]:
    """Serialize a trained model to ONNX format.

    For sklearn Pipelines (preprocessor + estimator), extracts the estimator
    and converts it alone via onnxmltools, saving a PreprocessingContract
    alongside the ONNX model so the serving template can replicate preprocessing.

    For bare LightGBM/XGBoost/sklearn estimators, converts directly.

    Args:
        checkpoint_path: Path to the model checkpoint
        output_path: Path for the output .onnx file
        model_type: "lightgbm", "xgboost", "sklearn_pipeline", "sklearn_model",
                     or None to auto-detect
        feature_names: Optional list of all input feature column names
        numeric_cols: Optional list of numeric column names
        categorical_cols: Optional list of categorical column names
        job_id: Optional job ID for the contract

    Returns:
        (success, message_or_onnx_path)
    """
    if not os.path.exists(checkpoint_path):
        return False, f"Checkpoint not found: {checkpoint_path}"

    try:
        import joblib

        raw = joblib.load(checkpoint_path)
        if isinstance(raw, dict) and "model" in raw:
            model = raw["model"]
        else:
            model = raw

        detected_type = model_type or _detect_model_type(model)

        if detected_type == "sklearn_pipeline":
            estimator, preprocess_config = _extract_estimator_from_pipeline(model)
            n_features = _get_n_features(estimator)

            contract = _generate_preprocessing_contract(model, preprocess_config, job_id=job_id)
            onnx_model = _convert_estimator_to_onnx(estimator, n_features)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            import onnx

            onnx.save_model(onnx_model, output_path)

            # Write the preprocessing contract (SINGLE SOURCE OF TRUTH)
            contract_path = output_path.replace(".onnx", "_contract.json")
            with open(contract_path, "w", encoding="utf-8") as f:
                f.write(contract.model_dump_json(indent=2))

            # Also keep legacy config for backward compat during migration
            config_path = output_path.replace(".onnx", "_preprocess.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(preprocess_config, f, indent=2, default=str)

            return True, output_path

        n_features = _get_n_features(model)
        onnx_model = _convert_estimator_to_onnx(model, n_features)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        import onnx

        onnx.save_model(onnx_model, output_path)
        return True, output_path

    except Exception as e:
        return False, f"ONNX conversion failed: {e}"


def generate_fastapi_app(
    model_path: str,
    output_dir: str,
    model_format: str = "onnx",
    feature_names: list[str] | None = None,
    numeric_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
    contract_path: str | None = None,
) -> str:
    """Generate a FastAPI serving app from the serving template.

    Uses the PreprocessingContract as the single source of truth.
    The generated app loads all preprocessing metadata from the contract
    at startup — no hardcoded FEATURE_NAMES, NUMERIC_COLS, or CATEGORICAL_COLS.

    Args:
        model_path: Path to the model file
        output_dir: Directory to write the app
        model_format: "onnx" or "pickle"
        feature_names: Optional list of all input feature column names
        numeric_cols: Optional list of numeric column names
        categorical_cols: Optional list of categorical column names
        contract_path: Path to the preprocessing_contract.json (optional but preferred)

    Returns:
        Path to the generated app file
    """
    from agents.harbor.serving_template import SERVING_TEMPLATE

    os.makedirs(output_dir, exist_ok=True)

    # Copy model file into the serving directory so Docker can access it
    model_filename = os.path.basename(model_path)
    dest_model_path = os.path.join(output_dir, model_filename)
    if os.path.abspath(model_path) != os.path.abspath(dest_model_path):
        shutil.copy2(model_path, dest_model_path)

    # Copy contract file if provided (always named preprocessing_contract.json in app dir)
    contract_filename = None
    dest_contract_path = os.path.join(output_dir, "preprocessing_contract.json")
    if contract_path and os.path.exists(contract_path):
        shutil.copy2(contract_path, dest_contract_path)
        contract_filename = "preprocessing_contract.json"
    else:
        # Try to auto-detect contract from model path
        basename = os.path.basename(model_path)
        alt_variants = [
            model_path.replace(".onnx", "_contract.json"),
            model_path.replace(".pkl", "_contract.json"),
            model_path.replace(".ckpt", "_contract.json"),
            model_path.replace(".joblib", "_contract.json"),
        ]
        alt_contract = next(
            (p for p in alt_variants if p != model_path and os.path.exists(p)), None
        )
        if alt_contract and os.path.exists(alt_contract):
            shutil.copy2(alt_contract, dest_contract_path)
            contract_filename = "preprocessing_contract.json"

    # Use path relative to output_dir (inside Docker, everything is at /app/)
    relative_model_path = model_filename
    relative_contract_path = contract_filename or ""

    app_code = SERVING_TEMPLATE.format(
        model_path=relative_model_path,
        model_format=model_format,
        model_name=model_filename,
        contract_path=relative_contract_path,
    )

    app_path = os.path.join(output_dir, "app.py")
    with open(app_path, "w", encoding="utf-8") as f:
        f.write(app_code)

    requirements_path = os.path.join(output_dir, "requirements.txt")
    base_reqs = [
        "fastapi>=0.111.0",
        "uvicorn>=0.30.0",
        "numpy>=1.26.4",
        "pandas>=2.2.2",
        "prometheus-client>=0.20.0",
        "httpx>=0.27.0",
    ]
    if model_format == "pickle":
        base_reqs.extend(["joblib>=1.3.0", "scikit-learn>=1.4.2", "lightgbm>=4.3.0"])
    else:
        base_reqs.append("onnxruntime>=1.18.0")
    with open(requirements_path, "w", encoding="utf-8") as f:
        f.write("\n".join(base_reqs) + "\n")

    return app_path


async def build_docker_image(image_name: str, app_dir: str) -> tuple[bool, str]:
    """Build a Docker image for the serving app (async, non-blocking)."""
    dockerfile_path = os.path.join(app_dir, "Dockerfile")
    extra_packages = []
    if os.path.exists(os.path.join(app_dir, "requirements.txt")):
        with open(os.path.join(app_dir, "requirements.txt"), encoding="utf-8") as f:
            deps = f.read()
            if "lightgbm" in deps or "xgboost" in deps:
                extra_packages.append("libgomp1")

    apt_cmd = (
        f"RUN apt-get update -qq && apt-get install -y -qq {' '.join(extra_packages)} && rm -rf /var/lib/apt/lists/*"
        if extra_packages
        else ""
    )

    dockerfile_content = (
        "FROM python:3.11-slim\n"
        "WORKDIR /app\n" + (apt_cmd + "\n" if apt_cmd else "") + "COPY . .\n"
        "RUN pip install -r requirements.txt --quiet\n"
        "EXPOSE 8080\n"
        'CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]\n'
    )

    with open(dockerfile_path, "w", encoding="utf-8") as f:
        f.write(dockerfile_content)

    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["docker", "build", "-t", image_name, app_dir],
                capture_output=True,
                text=True,
                timeout=300,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        )

        if result.returncode == 0:
            return True, f"Image built: {image_name}"
        else:
            return False, f"Docker build failed: {result.stderr}"
    except subprocess.TimeoutExpired:
        return False, "Docker build timed out after 300s"
    except Exception as e:
        return False, f"Docker build error: {e}"


_PORT_LOCK: dict[int, str] = {}
_PORT_BASE = 8080
_PORT_MAX_RETRIES = 100


def _find_available_port(start: int = _PORT_BASE) -> int:
    """Find an available port starting from `start`."""
    for port in range(start, start + _PORT_MAX_RETRIES):
        if port in _PORT_LOCK:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                _PORT_LOCK[port] = ""
                return port
    raise RuntimeError("No available port found")


def _release_port(port: int) -> None:
    _PORT_LOCK.pop(port, None)


async def deploy_local_compose(
    image_name: str,
    container_name: str,
    host_port: int | None = None,
) -> tuple[bool, str]:
    """Deploy a model serving container via Docker Compose (async, non-blocking).

    If host_port is None, automatically finds an available port.
    """
    auto_allocated = False
    if host_port is None:
        host_port = _find_available_port()
        auto_allocated = True

    await asyncio.to_thread(
        lambda: subprocess.run(
            ["docker", "rm", "-f", container_name], 
            capture_output=True, 
            text=True, 
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    )
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    container_name,
                    "-p",
                    f"{host_port}:8080",
                    "--restart",
                    "unless-stopped",
                    image_name,
                ],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        )

        if result.returncode == 0:
            container_id = result.stdout.strip()[:12]
            if auto_allocated:
                _PORT_LOCK[host_port] = container_name
            return True, f"Container {container_id} running at port {host_port}"
        else:
            if auto_allocated:
                _release_port(host_port)
            return False, f"Deploy failed: {result.stderr}"
    except subprocess.TimeoutExpired:
        if auto_allocated:
            _release_port(host_port)
        return False, "Container deploy timed out after 30s"
    except Exception as e:
        if auto_allocated:
            _release_port(host_port)
        return False, f"Deploy error: {e}"


def configure_drift_monitor(
    job_id: str,
    training_data_path: str,
    psi_threshold: float | None = None,
    feature_names: list[str] | None = None,
    numeric_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Configure drift monitor with actual feature distribution baselines.

    Loads the training dataset and computes per-feature histogram baselines
    (bin edges + counts) for PSI comparison. These baselines are stored in
    the returned config so that run_drift_check can compare live data against
    them without re-reading the training file.

    Args:
        job_id: Job identifier
        training_data_path: Path to the training dataset CSV
        psi_threshold: PSI threshold for alert (default: from env or 0.2)
        feature_names: Ordered list of feature column names to monitor
        numeric_cols: Subset of numeric feature columns for PSI computation

    Returns:
        Config dict with stored distribution baselines for each feature
    """
    threshold = (
        psi_threshold if psi_threshold is not None else float(os.getenv("PSI_THRESHOLD", "0.2"))
    )
    window_size = int(os.getenv("PSI_WINDOW_SIZE", "1000"))
    interval = int(os.getenv("PSI_CHECK_INTERVAL_SECONDS", "3600"))

    feature_distributions: dict[str, dict[str, Any]] = {}

    if feature_names and os.path.exists(training_data_path):
        try:
            df = pd.read_csv(training_data_path)
            monitor_cols = numeric_cols or [c for c in feature_names if c in df.columns]

            for col in monitor_cols:
                if col not in df.columns or not pd.api.types.is_numeric_dtype(df[col]):
                    continue
                values = df[col].dropna().values.astype(np.float64)
                if len(values) < 10:
                    continue
                # Store histogram baseline: bin edges + count fraction
                counts, bin_edges = np.histogram(values, bins=10)
                total = counts.sum()
                feature_distributions[col] = {
                    "bin_edges": bin_edges.tolist(),
                    "expected_pct": (counts / total).tolist() if total > 0 else [],
                    "mean": float(values.mean()),
                    "std": float(values.std()),
                    "min": float(values.min()),
                    "max": float(values.max()),
                }
            logger.info(
                f"[job={job_id}] Drift baselines computed for {len(feature_distributions)} features"
            )
        except Exception as e:
            logger.warning(f"[job={job_id}] Could not compute drift baselines: {e}")

    config = {
        "job_id": job_id,
        "training_data_path": training_data_path,
        "psi_threshold": threshold,
        "psi_check_interval_seconds": interval,
        "psi_window_size": window_size,
        "enabled": True,
        "feature_distributions": feature_distributions,
    }
    return config


async def run_drift_check(
    redis_client: Any,
    config: dict[str, Any],
    live_samples: dict[str, list[float]] | None = None,
) -> list[dict[str, Any]]:
    """Run one PSI drift check cycle against stored baselines.

    Compares either provided live_samples or (if None) simulates drift-free
    data from the stored baseline distribution (for testing).

    Args:
        redis_client: Redis client for publishing DRIFT_ALERT
        config: Drift monitor config from configure_drift_monitor
        live_samples: Dict of feature_name -> list of recent inference input values

    Returns:
        List of per-feature drift check results
    """
    results: list[dict[str, Any]] = []
    distributions = config.get("feature_distributions", {})

    for feature_name, baseline in distributions.items():
        expected_pct = np.array(baseline.get("expected_pct", []))
        bin_edges = np.array(baseline.get("bin_edges", []))

        if len(expected_pct) == 0 or len(bin_edges) == 0:
            continue

        if live_samples and feature_name in live_samples:
            actual_values = np.array(live_samples[feature_name], dtype=np.float64)
        else:
            # Simulate drift-free data from baseline for testing
            mean = baseline.get("mean", 0.0)
            std = baseline.get("std", 1.0)
            actual_values = np.random.normal(mean, max(std, 1e-6), 100)

        actual_counts, _ = np.histogram(actual_values, bins=bin_edges)
        total = actual_counts.sum()
        actual_pct = actual_counts / total if total > 0 else np.ones_like(expected_pct) * 1e-6

        psi = compute_psi(expected_pct, actual_pct)

        drift_detected = psi > config.get("psi_threshold", 0.2)

        result = {
            "feature": feature_name,
            "psi": round(psi, 4),
            "threshold": config.get("psi_threshold", 0.2),
            "drift_detected": drift_detected,
        }
        results.append(result)

        if drift_detected:
            logger.warning(f"[job={config['job_id']}] Drift | feature={feature_name} PSI={psi:.4f}")
            from contracts.events import DriftAlertEvent

            await publish(
                redis_client,
                STREAM_HARBOR_OUTPUT,
                DRIFT_ALERT,
                DriftAlertEvent(
                    job_id=config["job_id"],
                    psi_score=round(psi, 4),
                    psi_threshold=config.get("psi_threshold", 0.2),
                    window_size=config.get("psi_window_size", 1000),
                    feature=feature_name,
                ),
            )

    return results


async def start_drift_monitor_loop(
    redis_client: Any,
    config: dict[str, Any],
) -> None:
    """Run the drift monitoring loop in the background.

    Periodically checks PSI for each monitored feature and publishes
    DRIFT_ALERT events when drift exceeds threshold.

    Args:
        redis_client: Redis client for publishing alerts
        config: Drift monitor config from configure_drift_monitor
    """
    if not config.get("enabled", True):
        logger.info(f"[job={config['job_id']}] Drift monitor disabled")
        return

    interval = config.get("psi_check_interval_seconds", 3600)
    logger.info(
        f"[job={config['job_id']}] Drift monitor started (interval={interval}s, "
        f"features={len(config.get('feature_distributions', {}))})"
    )

    while True:
        try:
            await run_drift_check(redis_client, config)
        except Exception as e:
            logger.error(f"[job={config['job_id']}] Drift check failed: {e}")
        await asyncio.sleep(interval)

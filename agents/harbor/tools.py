"""Harbor tools — model serialization, API generation, deployment."""

import json
import logging
import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

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

    estimator = model.steps[-1][1]

    for name, step in model.steps[:-1]:
        step_type = type(step).__name__
        preprocess_config["steps"].append((name, step_type))

        if step_type == "ColumnTransformer":
            for name_, transformer, cols in step.transformers_:
                if isinstance(cols, list):
                    if transformer == "passthrough" or transformer == "drop":
                        pass
                    elif hasattr(transformer, "categories_"):
                        preprocess_config["categorical_cols"].extend(cols)
                        cat_data = {
                            "categories": [c.tolist() for c in transformer.categories_],
                            "handle_unknown": getattr(transformer, "handle_unknown", "error"),
                            "unknown_value": getattr(transformer, "unknown_value", None),
                        }
                        preprocess_config["cat_encoder"] = cat_data
                    elif hasattr(transformer, "get_feature_names_out"):
                        pass
                if hasattr(transformer, "_feature_names_in"):
                    preprocess_config["numeric_cols"].extend(list(transformer._feature_names_in))
                elif isinstance(step, str) and step == "drop":
                    pass

    # Fallback: if no numeric/categorical cols from ColumnTransformer, detect from estimator
    if not preprocess_config["numeric_cols"] and not preprocess_config["categorical_cols"]:
        if hasattr(estimator, "_feature_names_in"):
            preprocess_config["numeric_cols"] = list(estimator._feature_names_in)

    return estimator, preprocess_config


def _convert_estimator_to_onnx(
    estimator: Any,
    n_features: int,
    target_opset: int = 12,
) -> Any:
    """Convert a bare estimator (LightGBM, XGBoost, sklearn) to ONNX.

    Uses onnxmltools for tree models (compatible with skl2onnx's type system
    when used stand-alone, not inside a Pipeline).
    """
    module = getattr(estimator, "__module__", "")
    class_name = type(estimator).__name__

    from onnxconverter_common.data_types import FloatTensorType

    if "lightgbm" in module.lower() or "LGBM" in class_name:
        import onnxmltools
        from onnxmltools.convert import convert_lightgbm
        initial_types = [("input", FloatTensorType([None, n_features]))]
        return convert_lightgbm(estimator, initial_types=initial_types, name="model", target_opset=target_opset)

    if "xgboost" in module.lower() or "XGB" in class_name:
        import onnxmltools
        from onnxmltools.convert import convert_xgboost
        initial_types = [("input", FloatTensorType([None, n_features]))]
        return convert_xgboost(estimator, initial_types=initial_types, name="model", target_opset=target_opset)

    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    initial_types = [("input", FloatTensorType([None, n_features]))]
    options = {id(estimator): {"zipmap": False}} if hasattr(estimator, "classes_") else None
    return convert_sklearn(estimator, initial_types=initial_types, target_opset=target_opset, options=options)


def serialize_to_onnx(
    checkpoint_path: str,
    output_path: str,
    model_type: str | None = None,
    feature_names: list[str] | None = None,
    numeric_cols: list[str] | None = None,
    categorical_cols: list[str] | None = None,
) -> tuple[bool, str]:
    """Serialize a trained model to ONNX format.

    For sklearn Pipelines (preprocessor + estimator), extracts the estimator
    and converts it alone via onnxmltools, saving preprocessing config alongside
    the ONNX model so the serving template can replicate preprocessing.

    For bare LightGBM/XGBoost/sklearn estimators, converts directly.

    Args:
        checkpoint_path: Path to the model checkpoint
        output_path: Path for the output .onnx file
        model_type: "lightgbm", "xgboost", "sklearn_pipeline", "sklearn_model",
                     or None to auto-detect
        feature_names: Optional list of all input feature column names
        numeric_cols: Optional list of numeric column names
        categorical_cols: Optional list of categorical column names

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
            if numeric_cols:
                preprocess_config["numeric_cols"] = numeric_cols
            if categorical_cols:
                preprocess_config["categorical_cols"] = categorical_cols
            onnx_model = _convert_estimator_to_onnx(estimator, n_features)

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            import onnx
            onnx.save_model(onnx_model, output_path)

            config_path = output_path.replace(".onnx", "_preprocess.json")
            with open(config_path, "w") as f:
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
) -> str:
    """Generate a FastAPI serving app from the serving template.

    Args:
        model_path: Path to the model file
        output_dir: Directory to write the app
        model_format: "onnx" or "pickle"
        feature_names: Optional list of all input feature column names
        numeric_cols: Optional list of numeric column names
        categorical_cols: Optional list of categorical column names

    Returns:
        Path to the generated app file
    """
    from agents.harbor.serving_template import SERVING_TEMPLATE

    os.makedirs(output_dir, exist_ok=True)

    # Copy model file into the serving directory so Docker can access it
    import shutil
    model_filename = os.path.basename(model_path)
    dest_model_path = os.path.join(output_dir, model_filename)
    if os.path.abspath(model_path) != os.path.abspath(dest_model_path):
        shutil.copy2(model_path, dest_model_path)

    # Use path relative to output_dir (inside Docker, everything is at /app/)
    relative_model_path = model_filename

    app_code = SERVING_TEMPLATE.format(
        model_path=relative_model_path,
        model_format=model_format,
        model_name=model_filename,
        feature_names=json.dumps(feature_names or []),
        numeric_cols=json.dumps(numeric_cols or []),
        categorical_cols=json.dumps(categorical_cols or []),
    )

    app_path = os.path.join(output_dir, "app.py")
    with open(app_path, "w") as f:
        f.write(app_code)

    requirements_path = os.path.join(output_dir, "requirements.txt")
    base_reqs = [
        "fastapi>=0.111.0",
        "uvicorn>=0.30.0",
        "numpy>=1.26.4",
        "pandas>=2.2.2",
        "prometheus-client>=0.20.0",
    ]
    if model_format == "pickle":
        base_reqs.extend(["joblib>=1.3.0", "scikit-learn>=1.4.2", "lightgbm>=4.3.0"])
    else:
        base_reqs.append("onnxruntime>=1.18.0")
    with open(requirements_path, "w") as f:
        f.write("\n".join(base_reqs) + "\n")

    return app_path


def build_docker_image(image_name: str, app_dir: str) -> tuple[bool, str]:
    """Build a Docker image for the serving app."""
    dockerfile_path = os.path.join(app_dir, "Dockerfile")
    extra_packages = []
    if os.path.exists(os.path.join(app_dir, "requirements.txt")):
        with open(os.path.join(app_dir, "requirements.txt")) as f:
            deps = f.read()
            if "lightgbm" in deps or "xgboost" in deps:
                extra_packages.append("libgomp1")

    apt_cmd = f"RUN apt-get update -qq && apt-get install -y -qq {' '.join(extra_packages)} && rm -rf /var/lib/apt/lists/*" if extra_packages else ""

    dockerfile_content = (
        f"FROM python:3.11-slim\n"
        f"WORKDIR /app\n"
        + (apt_cmd + "\n" if apt_cmd else "")
        + f"COPY . .\n"
        f"RUN pip install -r requirements.txt --quiet\n"
        f"EXPOSE 8080\n"
        f'CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]\n'
    )

    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)

    try:
        result = subprocess.run(
            ["docker", "build", "-t", image_name, app_dir],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            return True, f"Image built: {image_name}"
        else:
            return False, f"Docker build failed: {result.stderr}"
    except Exception as e:
        return False, f"Docker build error: {e}"


def deploy_local_compose(
    image_name: str,
    container_name: str,
    host_port: int = 8080,
) -> tuple[bool, str]:
    """Deploy a model serving container via Docker Compose."""
    try:
        result = subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container_name,
                "-p", f"{host_port}:8080",
                "--restart", "unless-stopped",
                image_name,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            container_id = result.stdout.strip()[:12]
            return True, f"Container {container_id} running at port {host_port}"
        else:
            return False, f"Deploy failed: {result.stderr}"
    except Exception as e:
        return False, f"Deploy error: {e}"


def configure_drift_monitor(
    job_id: str,
    training_data_path: str,
    psi_threshold: float = 0.2,
) -> dict[str, Any]:
    """Configure drift monitor settings.

    Returns config dict (PSI check runs in background via orchestrator).
    """
    config = {
        "job_id": job_id,
        "training_data_path": training_data_path,
        "psi_threshold": psi_threshold,
        "psi_check_interval_seconds": 3600,
        "psi_window_size": 1000,
        "enabled": True,
    }
    return config

"""Harbor tools — model serialization, API generation, deployment."""

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def serialize_to_onnx(
    checkpoint_path: str,
    output_path: str,
    model_type: str = "lightgbm",
) -> tuple[bool, str]:
    """Serialize a trained model to ONNX format.

    Args:
        checkpoint_path: Path to the model checkpoint
        output_path: Path for the output .onnx file
        model_type: "lightgbm", "xgboost", "sklearn"

    Returns:
        (success, message_or_onnx_path)
    """
    if not os.path.exists(checkpoint_path):
        return False, f"Checkpoint not found: {checkpoint_path}"

    try:
        import joblib

        raw = joblib.load(checkpoint_path)
        # Handle dict wrapper (model + encoders bundle)
        if isinstance(raw, dict) and "model" in raw:
            model = raw["model"]
        else:
            model = raw

        import onnxmltools

        if model_type == "lightgbm":
            from onnxmltools.convert import convert_lightgbm
            from onnxconverter_common.data_types import FloatTensorType

            n_features = getattr(model, "n_features_in_", getattr(model, "n_features_", 1))
            initial_types = [("input", FloatTensorType([None, n_features]))]
            onnx_model = convert_lightgbm(model, initial_types=initial_types, name="model")
        elif model_type == "xgboost":
            from onnxmltools.convert import convert_xgboost
            from onnxconverter_common.data_types import FloatTensorType

            n_features = getattr(model, "n_features_in_", getattr(model, "n_features_", 1))
            initial_types = [("input", FloatTensorType([None, n_features]))]
            onnx_model = convert_xgboost(model, initial_types=initial_types, name="model")
        elif model_type == "sklearn":
            initial_types = [("input", None)]  # Will be refined per model
            onnx_model = onnxmltools.convert_sklearn(model, initial_types=initial_types)
        else:
            return False, f"Unsupported model type: {model_type}"

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        onnxmltools.utils.save_model(onnx_model, output_path)
        return True, output_path

    except Exception as e:
        return False, f"ONNX conversion failed: {e}"


def generate_fastapi_app(
    model_path: str,
    output_dir: str,
    model_format: str = "onnx",
) -> str:
    """Generate a FastAPI serving app from the serving template.

    Args:
        model_path: Path to the model file
        output_dir: Directory to write the app
        model_format: "onnx" or "pickle"

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

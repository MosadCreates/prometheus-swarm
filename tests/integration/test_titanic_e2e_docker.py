"""
Phase 1 gate test: Titanic end-to-end through real Docker training.
Requires: Docker running, prometheus-training-base image built, Redis running.
This test is the definitive proof that the system can train a real model.
"""

import os
import subprocess
import pytest

from runtime.paths import get_paths, get_job_paths

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(300)]

TITANIC_PATH = str(get_paths().data / "titanic.csv")
TRAINING_IMAGE = "prometheus-training-base"


@pytest.fixture(autouse=True)
def require_docker_and_data():
    """Skip if Docker or training image or Titanic CSV not available."""
    result = subprocess.run(
        ["docker", "images", "-q", TRAINING_IMAGE], capture_output=True, text=True
    )
    if not result.stdout.strip():
        pytest.skip(
            f"Docker image '{TRAINING_IMAGE}' not found. "
            f"Build it: docker build -t {TRAINING_IMAGE} training/base_training_image/"
        )
    if not os.path.exists(TITANIC_PATH):
        pytest.skip(
            f"Titanic dataset not found at {TITANIC_PATH}. "
            "Download from kaggle.com/competitions/titanic and copy train.csv to data/titanic.csv"
        )


async def test_scout_produces_valid_mission_brief():
    """Scout correctly identifies Titanic as tabular classification."""
    from agents.scout.tools import detect_modality, run_eda, write_mission_brief

    modality = detect_modality(TITANIC_PATH)
    assert modality == "tabular"
    eda = run_eda(TITANIC_PATH, target_column="Survived")
    assert eda["num_rows"] == 891
    assert eda["column_types"]["Survived"] == "target"
    brief = write_mission_brief(
        eda, "test-titanic-docker", "Predict Titanic survival", TITANIC_PATH, "Survived"
    )
    assert brief["task_type"] == "classification"
    assert brief["modality"] == "tabular"
    assert brief["evaluation_metric"] == "auc_roc"


async def test_forge_generates_runnable_script():
    """Forge generates a syntactically valid Python training script."""
    import ast
    from agents.forge.decision_tree import select_architecture
    from agents.forge.tools import write_training_script

    mission_brief = {
        "job_id": "test-titanic-docker",
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "Survived",
        "evaluation_metric": "auc_roc",
        "recommended_architecture_family": "lightgbm",
        "imbalance_strategy": "none",
        "dataset": {
            "file_path": TITANIC_PATH,
            "num_rows": 891,
            "num_columns": 12,
            "column_types": {},
        },
        "data_quality": {
            "class_imbalance_ratio": None,
            "missing_value_rate": {},
            "high_cardinality_columns": [],
            "data_warnings": [],
        },
    }
    architecture = select_architecture(mission_brief)
    assert architecture == "lightgbm"
    script_path = write_training_script(mission_brief, "test-titanic-docker", scripts_dir="scripts")
    assert os.path.exists(script_path)
    with open(script_path, encoding="utf-8") as f:
        code = f.read()
    ast.parse(code)  # raises SyntaxError if invalid
    assert "lightgbm" in code.lower() or "lgbm" in code.lower()
    assert "Survived" in code


async def test_furnace_trains_model_in_docker():
    """
    Furnace launches a real Docker container, trains LightGBM on Titanic,
    and produces a checkpoint. This is the core proof that Docker training works.
    """
    from training.docker_manager import DockerManager
    import uuid

    job_id = f"test-titanic-{uuid.uuid4().hex[:8]}"

    # Generate a training script for this job
    from agents.forge.tools import write_training_script

    mission_brief = {
        "job_id": job_id,
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "Survived",
        "evaluation_metric": "auc_roc",
        "recommended_architecture_family": "lightgbm",
        "imbalance_strategy": "none",
        "dataset": {
            "file_path": TITANIC_PATH,
            "num_rows": 891,
            "num_columns": 12,
            "column_types": {},
        },
        "data_quality": {
            "class_imbalance_ratio": None,
            "missing_value_rate": {},
            "high_cardinality_columns": [],
            "data_warnings": [],
        },
    }
    actual_script_path = write_training_script(mission_brief, job_id, scripts_dir="scripts")
    assert os.path.exists(actual_script_path)

    # Launch Docker container and train
    docker = DockerManager(training_image=TRAINING_IMAGE)
    try:
        await docker.launch_container(
            job_id=job_id,
            run_cmd=[f"/app/scripts/{os.path.basename(actual_script_path)}"],
            volumes={
                str(get_paths().scripts): {"bind": "/app/scripts", "mode": "ro"},
                str(get_paths().data): {"bind": "/app/data", "mode": "ro"},
                str(get_paths().outputs): {"bind": "/app/outputs", "mode": "rw"},
            },
            environment={
                "JOB_ID": job_id,
                "DATA_DIR": "/app/data",
                "OUTPUTS_DIR": "/app/outputs",
                "PYTHONUNBUFFERED": "1",
            },
        )
        exit_code, logs = await docker.wait_for_exit(job_id, timeout=180)
    finally:
        await docker.kill_container(job_id)
        # Clean up
        if os.path.exists(actual_script_path):
            os.remove(actual_script_path)

    assert exit_code == 0, (
        f"Training container exited with code {exit_code}.\n" f"Container logs:\n{logs[-3000:]}"
    )

    # Verify checkpoint was produced (check file exists and is non-empty)
    checkpoint_path = str(get_job_paths(job_id).checkpoint_path)
    assert os.path.exists(checkpoint_path), (
        f"Checkpoint not found at {checkpoint_path}. " f"Logs:\n{logs[-2000:]}"
    )
    assert os.path.getsize(checkpoint_path) > 0, "Checkpoint file is empty"

    # Verify model quality from container logs
    import re

    acc_match = re.search(r"Accuracy:\s*([\d.]+)", logs)
    if acc_match:
        accuracy = float(acc_match.group(1))
        assert accuracy > 0.75, (
            f"Accuracy {accuracy:.4f} < 0.75 threshold. "
            "Model trained but quality is below Phase 1 gate."
        )
        print(f"\nTitanic Docker E2E: Accuracy = {accuracy:.4f} — PASS")
    else:
        # Fallback: just confirm checkpoint exists and model was saved
        assert "Model saved" in logs, "Model was not reported as saved in logs"
        print(
            f"\nTitanic Docker E2E: Checkpoint verified ({os.path.getsize(checkpoint_path)} bytes) — PASS"
        )

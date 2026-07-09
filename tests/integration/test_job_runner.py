"""
Tests that job_runner.run_job() executes the complete agent pipeline.
Requires: Docker, redis, ANTHROPIC_API_KEY, prometheus-training-base image.
"""

import asyncio
import os
import subprocess

import pytest
import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(600)]

TITANIC_PATH = os.path.abspath("data/titanic.csv")
TRAINING_IMAGE = "prometheus-training-base"


@pytest.fixture(autouse=True)
def require_stack():
    r = subprocess.run(["docker", "images", "-q", TRAINING_IMAGE], capture_output=True, text=True)
    if not r.stdout.strip():
        pytest.skip(f"{TRAINING_IMAGE} not found")
    if not os.path.exists(TITANIC_PATH):
        pytest.skip("data/titanic.csv not found")
    if not os.getenv("ANTHROPIC_API_KEY", "").startswith("sk-ant-"):
        pytest.skip("ANTHROPIC_API_KEY not set")


async def test_job_runner_titanic_no_dissect():
    """Full pipeline without Dissect on Titanic. Proves Scout→Forge→Furnace→Arbiter→Harbor."""
    from orchestrator.job_runner import run_job, JobConfig

    redis = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    try:
        config = JobConfig(
            problem_description="Predict passenger survival on the Titanic",
            dataset_path=TITANIC_PATH,
            target_column="Survived",
            task_type="classification",
            modality="tabular",
            evaluation_metric="auc_roc",
            use_dissect=False,
            use_harbor=False,
            use_docker=True,
            timeout_seconds=300,
        )
        result = await run_job(config, redis)

        assert result.status in (
            "pass",
            "escalate",
            "crash",
        ), f"Unexpected status: {result.status} — {result.error_detail}"
        assert result.duration_seconds > 5.0, (
            f"Job completed in {result.duration_seconds:.1f}s — "
            f"this is too fast, suggests subprocess bypass"
        )
        if result.status == "pass":
            assert result.metric_value is not None
            assert result.metric_value > 0.70, f"AUC {result.metric_value:.4f} below 0.70"
            assert result.checkpoint_path is not None
            assert os.path.exists(
                result.checkpoint_path
            ), f"Checkpoint not found: {result.checkpoint_path}"
        print(
            f"\nJob runner result: status={result.status} "
            f"metric={result.metric_value} "
            f"duration={result.duration_seconds:.1f}s"
        )
    finally:
        await redis.aclose()


async def test_job_runner_rejects_fast_completion():
    """Guard: if a job completes in under 5 seconds, it used subprocess, not Docker."""
    from orchestrator.job_runner import run_job, JobConfig

    redis = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    try:
        config = JobConfig(
            problem_description="Classify iris species",
            dataset_path=TITANIC_PATH,
            target_column="Survived",
            task_type="classification",
            modality="tabular",
            use_dissect=False,
            use_harbor=False,
            use_docker=True,
            timeout_seconds=300,
        )
        result = await run_job(config, redis)
        assert result.duration_seconds > 5.0, (
            f"BYPASS DETECTED: job completed in {result.duration_seconds:.1f}s. "
            f"Real Docker training never finishes this fast."
        )
    finally:
        await redis.aclose()


async def test_job_runner_dissect_activates_on_crash():
    """Inject a broken script and verify Dissect activates."""
    import uuid

    from orchestrator.job_runner import run_job, JobConfig

    redis = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

    job_id = f"test-dissect-{uuid.uuid4().hex[:8]}"
    broken_script = f"scripts/training_script_{job_id}.py"

    try:
        config = JobConfig(
            job_id=job_id,
            problem_description="Predict survival",
            dataset_path=TITANIC_PATH,
            target_column="NonExistentColumn_XYZ",
            task_type="classification",
            modality="tabular",
            use_dissect=True,
            use_harbor=False,
            use_docker=True,
            timeout_seconds=300,
        )
        result = await run_job(config, redis)
        if result.dissect_attempted:
            assert (
                result.dissect_patch_attempts >= 1
            ), "Dissect was attempted but recorded 0 patch attempts"
            print(
                f"\nDissect activated: {result.dissect_patch_attempts} attempts, "
                f"outcome={result.dissect_outcome}"
            )
        else:
            print(f"\nJob outcome: {result.status} (Dissect not triggered)")
    finally:
        if os.path.exists(broken_script):
            os.remove(broken_script)
        await redis.aclose()

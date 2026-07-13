"""End-to-end pipeline runner for Titanic."""

import asyncio
import json
import logging
import os
import pickle
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")

from dotenv import load_dotenv  # noqa: E402
from runtime.paths import get_job_paths, get_paths

load_dotenv()


async def main():
    job_id = "titanic-e2e"
    jp = get_job_paths(job_id)
    titanic_path = str(get_paths().data / "titanic.csv")
    checkpoint_path = str(jp.checkpoint_path)

    # ── Phase 1: Scout ──────────────────────────────────────────────
    print("\n=== PHASE 1: SCOUT ===")
    from agents.scout.agent import ScoutAgent

    scout = ScoutAgent(job_id=job_id)
    await scout.redis.connect()
    brief = await scout.run_with_data(
        problem_description="Predict which passengers survived the Titanic disaster.",
        file_path=titanic_path,
        target_column="Survived",
    )
    print(f"  Modality: {brief['modality']}")
    print(f"  Task: {brief['task_type']}")
    print(f"  Target: {brief['target_column']}")

    # ── Phase 2: Forge ──────────────────────────────────────────────
    print("\n=== PHASE 2: FORGE ===")
    from agents.forge.agent import ForgeAgent

    forge = ForgeAgent(job_id=job_id)
    await forge.redis.connect()
    script_path = await forge.run_with_brief(brief)
    print(f"  Script: {script_path}")

    # Verify script is valid Python
    with open(script_path) as f:
        code = f.read()
    compile(code, script_path, "exec")
    print("  Syntax: OK")

    # ── Phase 3: Training ───────────────────────────────────────────
    print("\n=== PHASE 3: TRAINING ===")
    env = os.environ.copy()
    env["JOB_ID"] = job_id

    result = subprocess.run(
        [sys.executable, script_path],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    print(f"  stdout: {result.stdout.strip()}")
    if result.stderr:
        print(f"  stderr: {result.stderr.strip()}")
    print(f"  Exit code: {result.returncode}")

    if result.returncode != 0:
        print("\nFAILED: Training script crashed")
        return

    if not os.path.exists(checkpoint_path):
        print(f"\nFAILED: Checkpoint not found at {checkpoint_path}")
        return
    print(f"  Checkpoint: {checkpoint_path}")

    # ── Phase 4: Arbiter ────────────────────────────────────────────
    print("\n=== PHASE 4: ARBITER ===")
    from agents.arbiter.tools import (
        compute_classification_metrics,
        make_decision,
        generate_failure_analysis,
    )
    import pandas as pd

    # Load model and real test data
    df = pd.read_csv(titanic_path)
    target_col = brief["target_column"]
    df = df.dropna(subset=[target_col])

    # Drop text columns
    df = df.copy()
    cols_to_drop = [c for c in ["Name", "Ticket", "Cabin"] if c in df.columns]
    df = df.drop(columns=cols_to_drop)

    split_idx = int(len(df) * 0.8)
    test_df = df.iloc[split_idx:]
    y_test = test_df[target_col].values

    feature_cols = [c for c in test_df.columns if c != target_col]
    X_test_raw = test_df[feature_cols]

    # Load model (Pipeline includes preprocessing, pass raw data)
    with open(checkpoint_path, "rb") as f:
        ckpt = pickle.load(f)

    if isinstance(ckpt, dict) and "model" in ckpt:
        model = ckpt["model"]
        encoder = ckpt.get("target_encoder")
        if encoder is not None and y_test.dtype == object:
            y_test = encoder.transform(y_test)
    else:
        model = ckpt

    # Predict (Pipeline handles preprocessing internally)
    y_pred = model.predict(X_test_raw)
    y_prob = model.predict_proba(X_test_raw)[:, 1] if hasattr(model, "predict_proba") else None

    metrics = compute_classification_metrics(
        y_true=y_test.tolist(),
        y_pred=y_pred.tolist(),
        y_prob=y_prob.tolist() if y_prob is not None else None,
    )
    decision, reason = make_decision("classification", metrics, crash_count=0)
    _ = generate_failure_analysis(metrics, decision, reason)

    print(f"  AUC: {metrics.get('auc_roc', 0):.4f}")
    print(f"  Accuracy: {metrics.get('accuracy', 0):.4f}")
    print(f"  Decision: {decision}")
    print(f"  Reason: {reason}")

    # Write eval report
    from datetime import datetime, timezone

    eval_report = {
        "job_id": job_id,
        "decision": decision,
        "reason": reason,
        "metrics": metrics,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    os.makedirs(str(jp.job_dir), exist_ok=True)
    with open(str(jp.eval_report_path), "w") as f:
        json.dump(eval_report, f, indent=2)

    if decision != "pass":
        print(f"\nFAILED: Arbiter decision={decision}")
        return

    # ── Phase 5: Harbor ─────────────────────────────────────────────
    print("\n=== PHASE 5: HARBOR ===")
    from agents.harbor.tools import (
        serialize_to_onnx,
        generate_fastapi_app,
        build_docker_image,
        deploy_local_compose,
        configure_drift_monitor,
    )
    from bus.events import ENDPOINT_LIVE, STREAM_HARBOR_OUTPUT
    from bus.publisher import publish
    from memory.redis_client import RedisClient

    output_dir = str(jp.serving_dir)
    os.makedirs(output_dir, exist_ok=True)

    # ONNX conversion (try, fallback to pickle)
    onnx_path = f"{output_dir}/model.onnx"
    onnx_success, onnx_result = serialize_to_onnx(checkpoint_path, onnx_path, model_type="lightgbm")
    model_format = "onnx" if onnx_success else "pickle"
    model_path = onnx_path if onnx_success else checkpoint_path
    print(f"  Format: {model_format}")

    # Generate FastAPI app
    app_path = generate_fastapi_app(
        model_path=os.path.abspath(model_path),
        output_dir=output_dir,
        model_format=model_format,
    )
    print(f"  App: {app_path}")

    # Build Docker image
    safe_id = job_id[:8].strip("-").strip("_")
    image_name = f"prometheus-model-{safe_id}"
    build_ok, build_msg = build_docker_image(image_name, output_dir)
    print(f"  Docker build: {'OK' if build_ok else 'FAIL'} - {build_msg}")

    if build_ok:
        # Deploy
        container_name = f"prometheus-serving-{safe_id}"
        deploy_ok, deploy_msg = deploy_local_compose(image_name, container_name, host_port=8081)
        print(f"  Deploy: {'OK' if deploy_ok else 'FAIL'} - {deploy_msg}")

        # Configure drift monitoring
        _ = configure_drift_monitor(
            job_id=job_id,
            training_data_path=str(jp.training_data_csv_path),
        )

        # Publish ENDPOINT_LIVE
        redis = RedisClient()
        await redis.connect()
        await publish(
            redis._client,
            STREAM_HARBOR_OUTPUT,
            ENDPOINT_LIVE,
            {
                "job_id": job_id,
                "endpoint_url": "http://localhost:8081",
                "val_metric": metrics.get("auc_roc", 0),
                "p95_latency_ms": 0.0,
                "model_format": model_format,
            },
        )
        endpoint_url = "http://localhost:8081"
        print(f"  Endpoint: {endpoint_url}/docs")
        await redis.close()
    else:
        endpoint_url = "N/A"

    # ── Summary ─────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  TITANIC PIPELINE COMPLETE")
    print(f"  Job ID: {job_id}")
    print(f"  Checkpoint: {checkpoint_path}")
    print(f"  AUC: {metrics.get('auc_roc', 0):.4f}")
    print(f"  Decision: {decision.upper()}")
    print(f"  Endpoint: {endpoint_url}")
    print(f"{'='*60}")

    await scout.redis.close()
    await forge.redis.close()


if __name__ == "__main__":
    asyncio.run(main())

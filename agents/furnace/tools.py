"""Furnace tools. Manages training container lifecycle and monitoring."""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def launch_training_container(
    script_path: str,
    job_id: str,
    image_name: str = "prometheus-training-base",
) -> int:
    logger.info(f"[job={job_id}] Launching training for {script_path}")
    abs_path = os.path.abspath(script_path)

    cmd = [sys.executable, abs_path]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    logger.info(f"[job={job_id}] Training process started (PID: {process.pid})")
    return process.pid


async def monitor_loss(output_line: str, job_id: str) -> dict | None:
    if "Accuracy:" in output_line:
        parts = output_line.strip().split()
        if len(parts) >= 2:
            return {"type": "metric", "name": "accuracy", "value": float(parts[1])}
    elif "AUC-ROC:" in output_line:
        parts = output_line.strip().split()
        if len(parts) >= 2:
            return {"type": "metric", "name": "auc_roc", "value": float(parts[1])}
    elif "RMSE:" in output_line:
        parts = output_line.strip().split()
        if len(parts) >= 2:
            return {"type": "metric", "name": "rmse", "value": float(parts[1])}
    elif "Model saved to" in output_line:
        path = output_line.strip().split("Model saved to ", 1)[1].strip()
        return {"type": "checkpoint", "path": path}
    return None

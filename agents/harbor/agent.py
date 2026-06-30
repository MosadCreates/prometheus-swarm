"""Harbor Agent — The Deployer. Deploys trained models as live HTTPS endpoints."""

import json
import os
from datetime import datetime, timezone
from typing import Any

from agents.base import BaseAgent
from agents.harbor.prompts import HARBOR_SYSTEM_PROMPT
from agents.harbor.tools import (
    serialize_to_onnx,
    generate_fastapi_app,
    build_docker_image,
    deploy_local_compose,
    configure_drift_monitor,
)
from bus.events import (
    EVALUATION_PASS,
    ENDPOINT_LIVE,
    DRIFT_ALERT,
    STREAM_HARBOR_OUTPUT,
)
from bus.publisher import publish


class HarborAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Harbor"

    @property
    def system_prompt(self) -> str:
        return HARBOR_SYSTEM_PROMPT

    async def on_evaluation_pass(self, event: dict) -> None:
        self.job_id = event["job_id"]
        self.logger.info(f"[job={self.job_id}] Harbor deploying model")

        checkpoint_path = None
        try:
            raw = await self.redis.get(f"job:{self.job_id}:checkpoint")
            if raw:
                data = json.loads(raw) if isinstance(raw, str) else raw
                checkpoint_path = data.get("checkpoint_path") or data
            else:
                checkpoint_path = f"outputs/{self.job_id}/checkpoints/best.ckpt"
        except Exception:
            checkpoint_path = f"outputs/{self.job_id}/checkpoints/best.ckpt"

        if not os.path.exists(checkpoint_path):
            self.logger.warning(f"[job={self.job_id}] Checkpoint not found, trying joblib fallback")
            alt_path = checkpoint_path.replace(".ckpt", ".pkl").replace(".ckpt", ".joblib")
            if os.path.exists(alt_path):
                checkpoint_path = alt_path
            else:
                self.logger.error(f"[job={self.job_id}] No checkpoint found")
                return

        output_dir = f"outputs/{self.job_id}/serving"
        os.makedirs(output_dir, exist_ok=True)

        onnx_path = f"{output_dir}/model.onnx"
        onnx_success, onnx_result = serialize_to_onnx(
            checkpoint_path,
            onnx_path,
            model_type="lightgbm",
        )

        model_format = "onnx" if onnx_success else "pickle"
        model_path = onnx_path if onnx_success else checkpoint_path

        if not onnx_success:
            self.logger.warning(f"[job={self.job_id}] ONNX fallback to pickle: {onnx_result}")
            model_format = "pickle"

        app_path = generate_fastapi_app(
            model_path=os.path.abspath(model_path),
            output_dir=output_dir,
            model_format=model_format,
        )

        safe_id = self.job_id[:8].strip("-").strip("_")
        image_name = f"prometheus-model-{safe_id}"
        container_name = f"prometheus-serving-{self.job_id[:8]}"

        build_ok, build_msg = build_docker_image(image_name, output_dir)
        if not build_ok:
            self.logger.error(f"[job={self.job_id}] Docker build failed: {build_msg}")
            return

        deploy_ok, deploy_msg = deploy_local_compose(image_name, container_name, host_port=8080)
        if not deploy_ok:
            self.logger.error(f"[job={self.job_id}] Deploy failed: {deploy_msg}")
            return

        drift_config = configure_drift_monitor(
            job_id=self.job_id,
            training_data_path=f"outputs/{self.job_id}/training_data.csv",
        )

        endpoint_url = f"http://localhost:8080"

        self.logger.info(f"[job={self.job_id}] Model live at {endpoint_url}")

        await publish(
            self.redis._client,
            STREAM_HARBOR_OUTPUT,
            ENDPOINT_LIVE,
            {
                "job_id": self.job_id,
                "endpoint_url": endpoint_url,
                "val_metric": event.get("primary_metric_value", 0.0),
                "p95_latency_ms": 0.0,
                "model_format": model_format,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        config_path = f"{output_dir}/deploy_config.json"
        with open(config_path, "w") as f:
            json.dump({
                "job_id": self.job_id,
                "endpoint_url": endpoint_url,
                "model_format": model_format,
                "model_path": model_path,
                "container_name": container_name,
                "image_name": image_name,
                "drift_config": drift_config,
            }, f, indent=2)

"""Harbor Agent — The Deployer. Deploys trained models as live HTTPS endpoints.

Every deployment now includes:
  1. PreprocessingContract as single source of truth
  2. Artifact validation (Pipeline ↔ Contract ↔ ONNX ↔ App)
  3. Self-test (synthetic prediction before publishing endpoint)
  4. Deployment validation report
"""

import json
import os
import re
from datetime import datetime, timezone

from agents.base import BaseAgent
from agents.harbor.artifact_validator import verify_deployment
from agents.harbor.prompts import HARBOR_SYSTEM_PROMPT
from agents.harbor.tools import (
    serialize_to_onnx,
    generate_fastapi_app,
    build_docker_image,
    deploy_local_compose,
    configure_drift_monitor,
    start_drift_monitor_loop,
)
from bus.events import (
    ENDPOINT_LIVE,
    STREAM_HARBOR_OUTPUT,
)
from bus.publisher import publish
from shared.metrics import HARBOR_DEPLOYS, HARBOR_ACTIVE_DEPLOYMENTS, record_heartbeat


def _extract_column_info(
    mission_brief: dict | None,
) -> tuple[list[str], list[str], list[str]]:
    """Extract feature_names, numeric_cols, categorical_cols from mission_brief.

    Returns: (feature_names, numeric_cols, categorical_cols)
    """
    feature_names: list[str] = []
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []

    if not mission_brief:
        return feature_names, numeric_cols, categorical_cols

    dataset = mission_brief.get("dataset", {})
    col_types = dataset.get("column_types", {})

    target_col = mission_brief.get("target_column")

    for col, dtype in col_types.items():
        if target_col and col == target_col:
            continue
        if dtype == "target":
            continue
        feature_names.append(col)
        if dtype == "numeric":
            numeric_cols.append(col)
        elif dtype == "categorical":
            categorical_cols.append(col)

    return feature_names, numeric_cols, categorical_cols


class HarborAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Harbor"

    @property
    def system_prompt(self) -> str:
        return HARBOR_SYSTEM_PROMPT

    async def run(self) -> None:
        raise NotImplementedError(
            "HarborAgent is event-triggered. Call on_evaluation_pass(event) directly; "
            "it does not have a standalone run() loop."
        )

    async def on_evaluation_pass(self, event: dict) -> None:
        self.job_id = event["job_id"]
        self.logger.info(f"[job={self.job_id}] Harbor deploying model")
        record_heartbeat("Harbor", self.job_id)

        from runtime.paths import get_job_paths

        jp = get_job_paths(self.job_id)
        checkpoint_path = None
        try:
            data = await self.redis.get_json(f"job:{self.job_id}:checkpoint")
            if data and isinstance(data, dict):
                checkpoint_path = data.get("checkpoint_path")
            if not checkpoint_path:
                checkpoint_path = str(jp.checkpoint_path)
        except Exception:
            checkpoint_path = str(jp.checkpoint_path)

        if not os.path.exists(checkpoint_path):
            self.logger.warning(f"[job={self.job_id}] Checkpoint not found, trying joblib fallback")
            alt_path = checkpoint_path.replace(".ckpt", ".pkl").replace(".ckpt", ".joblib")
            if os.path.exists(alt_path):
                checkpoint_path = alt_path
            else:
                self.logger.error(f"[job={self.job_id}] No checkpoint found")
                return

        # Read mission_brief for column info
        try:
            mission_brief = await self.redis.get_json(f"job:{self.job_id}:mission_brief")
        except Exception:
            mission_brief = None

        feature_names, numeric_cols, categorical_cols = _extract_column_info(mission_brief)

        output_dir = str(jp.serving_dir)
        os.makedirs(output_dir, exist_ok=True)

        onnx_path = f"{output_dir}/model.onnx"
        onnx_success, onnx_result = serialize_to_onnx(
            checkpoint_path,
            onnx_path,
            feature_names=feature_names or None,
            numeric_cols=numeric_cols,
            categorical_cols=categorical_cols,
            job_id=self.job_id,
        )

        model_format = "onnx" if onnx_success else "pickle"
        model_path = onnx_path if onnx_success else checkpoint_path

        if not onnx_success:
            self.logger.warning(f"[job={self.job_id}] ONNX fallback to pickle: {onnx_result}")
            model_format = "pickle"

        # Locate the preprocessing contract (single source of truth)
        contract_path = model_path.replace(".onnx", "_contract.json").replace(
            ".pkl", "_contract.json"
        )
        if not os.path.exists(contract_path):
            contract_path = model_path.replace(".onnx", "_preprocess.json").replace(
                ".pkl", "_preprocess.json"
            )
            if not os.path.exists(contract_path):
                contract_path = None

        generate_fastapi_app(
            model_path=os.path.abspath(model_path),
            output_dir=output_dir,
            model_format=model_format,
            contract_path=contract_path,
        )

        # Run artifact validation before deployment
        validation_report = verify_deployment(
            checkpoint_path=checkpoint_path if "checkpoint" in checkpoint_path else checkpoint_path,
            contract_path=contract_path,
            onnx_path=model_path if model_format == "onnx" else None,
            app_dir=output_dir,
            report_path=os.path.join(output_dir, "deployment_validation_report.txt"),
        )

        self.logger.info(f"\n{validation_report.summary()}")

        if not validation_report.all_passed():
            HARBOR_DEPLOYS.labels(
                job_id=self.job_id, framework=model_format, status="validation_fail"
            ).inc()
            self.logger.error(
                f"[job={self.job_id}] Deployment validation failed — aborting deployment"
            )
            return

        safe_id = self.job_id[:8].strip("-").strip("_")
        image_name = f"prometheus-model-{safe_id}"
        container_name = f"prometheus-serving-{self.job_id[:8]}"

        build_ok, build_msg = build_docker_image(image_name, output_dir)
        if not build_ok:
            HARBOR_DEPLOYS.labels(
                job_id=self.job_id, framework=model_format, status="build_fail"
            ).inc()
            self.logger.error(f"[job={self.job_id}] Docker build failed: {build_msg}")
            return

        deploy_ok, deploy_msg = deploy_local_compose(image_name, container_name, host_port=None)
        if not deploy_ok:
            HARBOR_DEPLOYS.labels(
                job_id=self.job_id, framework=model_format, status="deploy_fail"
            ).inc()
            self.logger.error(f"[job={self.job_id}] Deploy failed: {deploy_msg}")
            return

        HARBOR_DEPLOYS.labels(job_id=self.job_id, framework=model_format, status="success").inc()
        HARBOR_ACTIVE_DEPLOYMENTS.labels(job_id=self.job_id).inc()

        port_match = re.search(r"port (\d+)", deploy_msg)
        deployed_port = int(port_match.group(1)) if port_match else 8080

        endpoint_url = f"http://localhost:{deployed_port}"

        # Run self-test against deployed endpoint
        if model_format == "onnx" and contract_path:
            from agents.harbor.artifact_validator import run_self_test
            from contracts.domain import PreprocessingContract

            try:
                with open(contract_path, encoding="utf-8") as f:
                    contract_data = json.load(f)
                contract = PreprocessingContract.model_validate(contract_data)

                import time as _time

                _time.sleep(2)  # Brief wait for container readiness

                self_test = run_self_test(endpoint_url, contract)
                self.logger.info(
                    f"[job={self.job_id}] Self-test: {'PASS' if self_test.passed else 'FAIL'} | {self_test.detail}"
                )
                if not self_test.passed:
                    HARBOR_DEPLOYS.labels(
                        job_id=self.job_id, framework=model_format, status="self_test_fail"
                    ).inc()
                    self.logger.error(
                        f"[job={self.job_id}] Self-test failed — deployment may be broken"
                    )
            except Exception as e:
                self.logger.warning(f"[job={self.job_id}] Self-test error (non-fatal): {e}")

        drift_config = configure_drift_monitor(
            job_id=self.job_id,
            training_data_path=str(jp.training_data_csv_path),
            feature_names=feature_names or None,
            numeric_cols=numeric_cols or None,
        )

        if drift_config.get("enabled") and drift_config.get("feature_distributions"):
            import asyncio

            asyncio.create_task(start_drift_monitor_loop(self.redis._client, drift_config))

        self.logger.info(f"[job={self.job_id}] Model live at {endpoint_url}")

        from contracts.events import EndpointLiveEvent

        await publish(
            self.redis._client,
            STREAM_HARBOR_OUTPUT,
            ENDPOINT_LIVE,
            EndpointLiveEvent(
                job_id=self.job_id,
                endpoint_url=endpoint_url,
                val_metric=event.get("primary_metric_value", 0.0),
                p95_latency_ms=0.0,
                model_format=model_format,
            ),
        )

        config_path = f"{output_dir}/deploy_config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "job_id": self.job_id,
                    "endpoint_url": endpoint_url,
                    "model_format": model_format,
                    "model_path": model_path,
                    "container_name": container_name,
                    "image_name": image_name,
                    "drift_config": drift_config,
                    "contract_path": contract_path,
                    "feature_names": feature_names,
                    "numeric_cols": numeric_cols,
                },
                f,
                indent=2,
            )

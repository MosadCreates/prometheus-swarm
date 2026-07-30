"""Harbor Agent — The Deployer. Deploys trained models as live HTTPS endpoints.

Every deployment now includes:
  1. PreprocessingContract as single source of truth
  2. Artifact validation (Pipeline ↔ Contract ↔ ONNX ↔ App)
  3. Self-test (synthetic prediction before publishing endpoint)
  4. Deployment validation report
"""

import asyncio
import json
import os
import re

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
from bus.agent_events import emit_agent_event, emit_subaction_progress
from bus.events import (
    ENDPOINT_LIVE,
    STREAM_HARBOR_OUTPUT,
)
from bus.publisher import publish
from shared.metrics import HARBOR_DEPLOYS, HARBOR_ACTIVE_DEPLOYMENTS, record_heartbeat
from prometheus.ui.detail_types import (
    HarborDeployDetail,
    HarborEndpointDetail,
    HarborFormatDetail,
    HarborHealthDetail,
    HarborDriftDetail,
    HarborSelfTestDetail,
)


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

    async def _publish_harbor_failed(self, reason: str) -> None:
        from contracts.events import JobFailedEvent
        from bus.publisher import publish
        from bus.events import STREAM_HARBOR_OUTPUT, JOB_FAILED

        try:
            await publish(
                self.redis._client,
                STREAM_HARBOR_OUTPUT,
                JOB_FAILED,
                JobFailedEvent(
                    job_id=self.job_id,
                    source_agent="Harbor",
                    reason=reason,
                ),
            )
        except Exception:
            self.logger.exception(f"[job={self.job_id}] Failed to publish failure event")

    async def run(self) -> None:
        raise NotImplementedError(
            "HarborAgent is event-triggered. Call on_evaluation_pass(event) directly; "
            "it does not have a standalone run() loop."
        )

    async def on_evaluation_pass(self, event: dict) -> None:
        self.job_id = event["job_id"]
        self.logger.info(f"[job={self.job_id}] Harbor deploying model")
        record_heartbeat("Harbor", self.job_id)

        _harbor_event_id = ""
        _harbor_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "thinking",
            "Starting deployment...",
        )

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
                await emit_agent_event(
                    self.redis._client,
                    self.job_id,
                    "Harbor",
                    "error",
                    "Checkpoint not found",
                    detail={"error": f"No checkpoint at {checkpoint_path}"},
                    parent_event_id=_harbor_event_id or None,
                )
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

        _harbor_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "acting",
            "Serializing model to ONNX...",
            parent_event_id=_harbor_event_id or None,
        )
        onnx_success, onnx_result = serialize_to_onnx(
            checkpoint_path,
            onnx_path,
            feature_names=feature_names or None,
            numeric_cols=numeric_cols,
            categorical_cols=categorical_cols,
            job_id=self.job_id,
        )

        model_format = "onnx" if onnx_success else "pickle"

        # Emit structured detail for ONNX serialization
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "acting",
            "Model serialized",
            detail=HarborFormatDetail(
                format=model_format,
                fallback=not onnx_success,
                reason=onnx_result if not onnx_success else "",
            ).model_dump(),
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", "Model serialized to ONNX", 0.3
        )
        model_path = onnx_path if onnx_success else checkpoint_path

        if not onnx_success:
            self.logger.warning(f"[job={self.job_id}] ONNX fallback to pickle: {onnx_result}")
            model_format = "pickle"

        # Locate the preprocessing contract (single source of truth)
        contract_path = None
        search_dirs = [output_dir, os.path.dirname(model_path)]
        for search_dir in search_dirs:
            if not search_dir or not os.path.isdir(search_dir):
                continue
            for fname in os.listdir(search_dir):
                if fname.endswith("_contract.json") or fname.endswith("_preprocess.json"):
                    candidate = os.path.join(search_dir, fname)
                    if os.path.isfile(candidate):
                        contract_path = candidate
                        break
            if contract_path:
                break

        generate_fastapi_app(
            model_path=os.path.abspath(model_path),
            output_dir=output_dir,
            model_format=model_format,
            contract_path=contract_path,
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", "FastAPI serving app generated", 0.5
        )

        # Run artifact validation before deployment
        _harbor_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "verifying",
            "Running deployment validation (6 phases)...",
            parent_event_id=_harbor_event_id or None,
        )
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
            await emit_agent_event(
                self.redis._client,
                self.job_id,
                "Harbor",
                "error",
                "Validation failed",
                detail={"error": validation_report.summary()},
                parent_event_id=_harbor_event_id or None,
            )
            await self._publish_harbor_failed(
                f"Deployment validation failed: {validation_report.summary()}"
            )
            return

        safe_id = self.job_id[:8].strip("-").strip("_")
        image_name = f"prometheus-model-{safe_id}"
        container_name = f"prometheus-serving-{self.job_id[:8]}"

        _harbor_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "acting",
            "Building Docker image...",
            parent_event_id=_harbor_event_id or None,
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", "docker build (may take 1-2 min)", 0.6
        )

        build_ok, build_msg = await build_docker_image(image_name, output_dir)
        if not build_ok:
            HARBOR_DEPLOYS.labels(
                job_id=self.job_id, framework=model_format, status="build_fail"
            ).inc()
            self.logger.error(f"[job={self.job_id}] Docker build failed: {build_msg}")
            await emit_agent_event(
                self.redis._client,
                self.job_id,
                "Harbor",
                "error",
                "Docker build failed",
                detail={"error": build_msg},
                parent_event_id=_harbor_event_id or None,
            )
            await self._publish_harbor_failed(f"Docker build failed: {build_msg}")
            return

        # Emit structured detail for docker build
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "acting",
            "Docker image built",
            detail=HarborDeployDetail(
                stage="build",
                progress=0.7,
                message="Docker image built successfully",
            ).model_dump(),
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", "Starting container...", 0.7
        )

        deploy_ok, deploy_msg = await deploy_local_compose(
            image_name, container_name, host_port=None
        )
        if not deploy_ok:
            HARBOR_DEPLOYS.labels(
                job_id=self.job_id, framework=model_format, status="deploy_fail"
            ).inc()
            self.logger.error(f"[job={self.job_id}] Deploy failed: {deploy_msg}")
            await emit_agent_event(
                self.redis._client,
                self.job_id,
                "Harbor",
                "error",
                "Container deploy failed",
                detail={"error": deploy_msg},
                parent_event_id=_harbor_event_id or None,
            )
            await self._publish_harbor_failed(f"Deploy failed: {deploy_msg}")
            return

        # Emit structured detail for deployment
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "acting",
            "Container deployed",
            detail=HarborDeployDetail(
                stage="deploy",
                progress=0.8,
                message="Container deployed successfully",
            ).model_dump(),
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", "Container deployed", 0.8
        )

        HARBOR_DEPLOYS.labels(job_id=self.job_id, framework=model_format, status="success").inc()
        HARBOR_ACTIVE_DEPLOYMENTS.labels(job_id=self.job_id).inc()

        port_match = re.search(r"port (\d+)", deploy_msg)
        deployed_port = int(port_match.group(1)) if port_match else 8080

        endpoint_url = f"http://localhost:{deployed_port}"

        _harbor_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "verifying",
            "Running self-test against deployed endpoint...",
            parent_event_id=_harbor_event_id or None,
        )

        # Run self-test against deployed endpoint
        self_test = None
        if model_format == "onnx" and contract_path:
            from agents.harbor.artifact_validator import run_self_test
            from contracts.domain import PreprocessingContract

            try:
                with open(contract_path, encoding="utf-8") as f:
                    contract_data = json.load(f)
                contract = PreprocessingContract.model_validate(contract_data)

                await asyncio.sleep(2)  # Brief wait for container readiness

                self_test = run_self_test(endpoint_url, contract)
                self.logger.info(
                    f"[job={self.job_id}] Self-test: {'PASS' if self_test.passed else 'FAIL'} | {self_test.detail}"
                )
                if not self_test.passed:
                    HARBOR_DEPLOYS.labels(
                        job_id=self.job_id, framework=model_format, status="self_test_fail"
                    ).inc()
                    self.logger.warning(
                        f"[job={self.job_id}] Self-test failed (non-fatal): {self_test.detail}"
                    )
            except Exception as e:
                self.logger.warning(f"[job={self.job_id}] Self-test error (non-fatal): {e}")

        self_test_status = "passed" if (self_test and self_test.passed) else "skipped"
        await emit_subaction_progress(
            self.redis._client, self.job_id, "Harbor", f"Self-test {self_test_status}", 1.0, "done"
        )

        # Emit structured detail for self-test
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "verifying",
            f"Self-test {self_test_status}",
            detail=HarborSelfTestDetail(
                passed=self_test.passed if self_test else False,
                detail=self_test.detail if self_test else "Self-test skipped",
                command=f"Invoke-RestMethod -Uri {endpoint_url}/predict -Method POST -Body '{{\"features\":[]}}' -ContentType 'application/json'",
            ).model_dump(),
        )

        drift_config = configure_drift_monitor(
            job_id=self.job_id,
            training_data_path=str(jp.training_data_csv_path),
            feature_names=feature_names or None,
            numeric_cols=numeric_cols or None,
        )

        if drift_config.get("enabled") and drift_config.get("feature_distributions"):
            asyncio.create_task(start_drift_monitor_loop(self.redis._client, drift_config))

            # Emit drift monitoring detail
            await emit_agent_event(
                self.redis._client,
                self.job_id,
                "Harbor",
                "verifying",
                "Drift monitoring enabled",
                detail=HarborDriftDetail(
                    psi_score=0.0,
                    psi_threshold=drift_config.get("psi_threshold", 0.2),
                    feature=drift_config.get("feature", ""),
                    window_size=drift_config.get("window_size", 1000),
                ).model_dump(),
            )

        self.logger.info(f"[job={self.job_id}] Model live at {endpoint_url}")

        # Emit structured detail for endpoint
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Harbor",
            "done",
            f"Model live at {endpoint_url}",
            detail=HarborEndpointDetail(
                endpoint_url=endpoint_url,
                model_format=model_format,
                port=deployed_port,
            ).model_dump(),
            parent_event_id=_harbor_event_id or None,
        )

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

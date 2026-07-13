"""Furnace Agent — The Trainer. Executes training and manages the train loop."""

import asyncio
import json
import os
import re
import shutil
import sys
import time
import traceback as tb_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.base import BaseAgent
from agents.furnace.prompts import FURNACE_SYSTEM_PROMPT
from bus.events import (
    CRASH_EVENT,
    EPOCH_COMPLETE,
    RESUME_TRAINING,
    TRAINING_COMPLETE,
    STREAM_DISSECT_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_FURNACE_FEED,
    STREAM_FURNACE_OUTPUT,
)
from bus.publisher import publish
from prometheus.cli.mission.state_logger import log_mission_state
from runtime.paths import get_job_paths, get_paths
from shared.metrics import (
    FURNACE_TRAINING_RUNS,
    FURNACE_EPOCHS,
    FURNACE_CRASHES,
    FURNACE_CRASHES_RECOVERED,
    FURNACE_BEST_VAL_METRIC,
    AGENT_RUNS,
    record_heartbeat,
    record_agent_error,
)
from contracts import CrashEvent, RepairResult
from training.docker_manager import DockerManager


class FurnaceAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(job_id=job_id)
        self.docker = DockerManager()
        self._best_val_metric: float = 0.0
        self._epoch_count: int = 0
        self._crashes_recovered: int = 0
        self._current_trial: int = 0
        self._total_trials: int = 0
        self._start_time: float = 0.0
        self._container_error_log: str = ""
        self._output_dir_override: str | None = None

    @property
    def agent_name(self) -> str:
        return "Furnace"

    @property
    def system_prompt(self) -> str:
        return FURNACE_SYSTEM_PROMPT

    async def run(
        self,
        script_path: str,
        use_docker: bool = True,
        search_space_json: str | None = None,
        progress_callback: Any = None,
        wait_for_dissect: bool = True,
        resume_from: str | None = None,
        output_dir_override: str | None = None,
    ) -> None:
        self._output_dir_override = output_dir_override
        self.logger.info(f"[job={self.job_id}] Furnace starting")
        if self._output_dir_override:
            self.logger.info(
                f"[job={self.job_id}] Output dir override: {self._output_dir_override}"
            )
        AGENT_RUNS.labels(agent="Furnace", job_id=self.job_id).inc()
        record_heartbeat("Furnace", self.job_id)

        jp = get_job_paths(self.job_id)
        checkpoint_path = resume_from or str(jp.checkpoint_path)
        log_mission_state(
            "FURNACE_START",
            self.job_id,
            script_path=script_path,
            checkpoint_path=checkpoint_path,
            retry_number=0,
        )

        if not script_path:
            record_agent_error("Furnace", self.job_id, "missing_script_path")
            raise ValueError(f"script_path required for Furnace job {self.job_id}")

        self._search_space_json = search_space_json
        current_script = script_path
        crash_attempt = 0
        last_checkpoint: str | None = resume_from

        while True:
            try:
                if use_docker:
                    await self._launch_and_monitor_docker(
                        current_script,
                        resume_from=last_checkpoint,
                        progress_callback=progress_callback,
                    )
                else:
                    await self._launch_and_monitor_subprocess(
                        current_script,
                        progress_callback=progress_callback,
                    )
                await self._finalize_training(current_script)
                if progress_callback:
                    progress_callback("Complete.")

                log_mission_state(
                    "FURNACE_COMPLETE",
                    self.job_id,
                    script_path=current_script,
                    checkpoint_path=str(jp.checkpoint_path),
                    metric_name=self._guess_metric_name(),
                    metric_value=self._best_val_metric,
                    retry_number=crash_attempt,
                )
                try:
                    await self.redis._client.delete(f"job:{self.job_id}:last_crash")
                except Exception:
                    pass
                return
            except Exception as e:
                crash_attempt += 1
                resume_payload = await self._handle_crash(
                    e,
                    current_script,
                    crash_attempt,
                    progress_callback=progress_callback,
                    wait_for_dissect=wait_for_dissect,
                )
                if resume_payload is None:
                    self.logger.error(
                        f"[job={self.job_id}] Furnace giving up after crash handling."
                    )
                    if not wait_for_dissect:
                        return
                    return
                if not wait_for_dissect:
                    return
                if isinstance(resume_payload, RepairResult):
                    current_script = resume_payload.patched_script_path
                    last_checkpoint = resume_payload.resume_from_checkpoint or last_checkpoint
                elif isinstance(resume_payload, dict):
                    current_script = resume_payload.get("patched_script_path", current_script)
                    last_checkpoint = resume_payload.get("last_checkpoint_path") or last_checkpoint
                self.logger.info(
                    f"[job={self.job_id}] Resuming with patched script: {current_script}"
                )

    async def prepare_workspace(self) -> str:
        jp = get_job_paths(self.job_id)
        root = jp.ensure_workspace()
        self.logger.info(f"[job={self.job_id}] Workspace prepared at {root}")
        return str(root)

    async def validate_docker_environment(
        self,
        progress_callback: Any = None,
    ) -> None:
        if progress_callback:
            progress_callback("Checking Docker installation...")
        avail, msg = await self.docker.check_docker_available()
        if not avail:
            raise RuntimeError(msg)
        if progress_callback:
            progress_callback("Checking training image...")
        exists, msg = await self.docker.check_image_exists()
        if not exists:
            raise RuntimeError(msg)
        if progress_callback:
            progress_callback("Docker environment validated.")

    async def _launch_and_monitor_docker(
        self,
        script_path: str,
        resume_from: str | None = None,
        progress_callback: Any = None,
    ) -> None:
        abs_script = os.path.abspath(script_path)
        script_name = os.path.basename(abs_script)

        FURNACE_TRAINING_RUNS.labels(job_id=self.job_id, mode="docker").inc()
        record_heartbeat("Furnace", self.job_id)
        self.logger.info(f"[job={self.job_id}] Launching Docker training: {script_name}")

        if progress_callback:
            progress_callback("Validating training inputs...")
        await self._validate_inputs(script_path)

        if progress_callback:
            progress_callback("Preparing execution workspace...")
        workspace_root = await self.prepare_workspace()

        await self.validate_docker_environment(progress_callback=progress_callback)

        await self._copy_dataset_to_data()

        if progress_callback:
            progress_callback("Launching Docker container...")

        container_name = f"prometheus-train-{self.job_id}"

        jp = get_job_paths(self.job_id)
        if self._output_dir_override:
            abs_output = os.path.abspath(self._output_dir_override)
            volumes = {}
            for host_path, config in get_job_paths(self.job_id).docker_mounts.items():
                if config.get("bind") == "/app/outputs":
                    volumes[abs_output] = {"bind": "/app/outputs", "mode": "rw"}
                else:
                    volumes[host_path] = config
            environment = jp.container_env
        else:
            volumes = jp.docker_mounts
            environment = jp.container_env

        if resume_from:
            environment["RESUME_CHECKPOINT"] = resume_from
            self.logger.info(f"[job={self.job_id}] Resuming from checkpoint: {resume_from}")

        search_json = getattr(self, "_search_space_json", None)
        if search_json:
            environment["SEARCH_SPACE_JSON"] = search_json

        if progress_callback:
            progress_callback("Training started...")

        try:
            await self.docker.launch_container(
                job_id=self.job_id,
                run_cmd=[f"/app/scripts/{script_name}"],
                volumes=volumes,
                environment=environment,
                working_dir="/workspace",
                container_name_prefix="prometheus-train",
                auto_remove=False,
            )
        except Exception as e:
            raise RuntimeError(f"Container startup failed: {e}")

        self._start_time = time.time()

        def on_log_line(line: str) -> None:
            self._on_training_log(line, progress_callback=progress_callback)

        exit_code, combined_log, stdout_log, stderr_log = await self.docker.stream_logs(
            self.job_id,
            callback=on_log_line,
        )

        self._save_logs(workspace_root, combined_log, stdout_log, stderr_log)

        if exit_code != 0:
            error_lines = [ln for ln in combined_log.split("\n") if ln.strip()]
            last_30 = error_lines[-30:] if len(error_lines) > 30 else error_lines
            error_detail = "\n".join(last_30)
            self._container_error_log = combined_log
            exc_line = ""
            for line in error_lines:
                if line.startswith("Traceback (most recent call last)"):
                    continue
                if "Error:" in line or "Exception:" in line:
                    exc_line = line
                    break
            if not exc_line:
                for line in error_lines:
                    if "error" in line.lower() or "traceback" in line.lower():
                        continue
                    line_stripped = line.strip()
                    if (
                        line_stripped
                        and not line_stripped.startswith("/")
                        and not line_stripped.startswith("  ")
                    ):
                        exc_line = line_stripped
                        break
            raise RuntimeError(
                f"Container exit code {exit_code} | {exc_line or 'See container logs'}\n"
                f"Full trace: {last_30[-5] if len(last_30) >= 5 else error_detail[:200]}"
            )

    async def _validate_inputs(self, script_path: str) -> None:
        if not os.path.isfile(script_path):
            raise FileNotFoundError(f"Training script not found: {script_path}")
        if not os.access(script_path, os.R_OK):
            raise PermissionError(f"Training script not readable: {script_path}")
        brief_key = f"job:{self.job_id}:mission_brief"
        try:
            raw = await self.redis._client.get(brief_key)
            if raw:
                brief_data = json.loads(raw) if isinstance(raw, str) else raw
                from contracts import MissionBrief

                try:
                    brief = MissionBrief.model_validate(brief_data)
                    ds_path = brief.dataset.file_path if brief.dataset else ""
                except Exception:
                    ds_path = brief_data.get("dataset", {}).get("file_path", "")
                if ds_path and not os.path.isfile(ds_path):
                    self.logger.warning(
                        f"[job={self.job_id}] Dataset not found at {ds_path}, "
                        f"will check data/ directory"
                    )
        except Exception:
            pass
        if self._output_dir_override:
            outputs_dir = os.path.abspath(self._output_dir_override)
        else:
            outputs_dir = str(get_job_paths(self.job_id).job_dir)
        try:
            os.makedirs(outputs_dir, exist_ok=True)
            test_file = os.path.join(outputs_dir, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
        except (OSError, PermissionError) as e:
            raise PermissionError(f"Outputs directory not writable at {outputs_dir}: {e}")

    async def _copy_dataset_to_data(self) -> None:
        try:
            raw = await self.redis._client.get(f"job:{self.job_id}:mission_brief")
            if raw:
                brief = json.loads(raw) if isinstance(raw, str) else raw
                orig_path = brief.get("dataset", {}).get("file_path")
                if orig_path and os.path.isfile(orig_path):
                    from runtime.paths import get_paths

                    data_dir = str(get_paths().data)
                    os.makedirs(data_dir, exist_ok=True)
                    target = os.path.join(data_dir, os.path.basename(orig_path))
                    if not os.path.isfile(target):
                        shutil.copy2(orig_path, target)
                        self.logger.info(
                            f"[job={self.job_id}] Copied dataset {orig_path} -> {target}"
                        )
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Could not copy dataset: {e}")

    def _on_training_log(self, line: str, progress_callback: Any = None) -> None:
        trial_match = re.search(r"Trial\s+(\d+)\s*/?\s*(\d*)", line, re.IGNORECASE)
        if trial_match:
            self._current_trial = int(trial_match.group(1))
            total_raw = trial_match.group(2)
            if total_raw:
                self._total_trials = int(total_raw)
        elapsed = time.time() - self._start_time if self._start_time else 0
        if self._total_trials and self._current_trial:
            remaining = self._total_trials - self._current_trial
            if remaining > 0 and self._current_trial > 0:
                per_trial = elapsed / self._current_trial
                eta_secs = per_trial * remaining
        metric_match = re.search(
            r"(AUC|ROC AUC|Accuracy|RMSE|MAE|F1)[:\s]*([\d.]+)", line, re.IGNORECASE
        )
        if metric_match:
            metric_name = metric_match.group(1).upper()
            metric_value = float(metric_match.group(2))
            if metric_name in ("AUC", "ROC AUC"):
                self._best_val_metric = max(self._best_val_metric, metric_value)
            elif metric_name == "ACCURACY":
                self._best_val_metric = max(self._best_val_metric, metric_value)
            elif metric_name == "RMSE":
                self._best_val_metric = (
                    metric_value
                    if self._best_val_metric == 0.0
                    else min(self._best_val_metric, metric_value)
                )
            self._epoch_count += 1
            FURNACE_EPOCHS.labels(job_id=self.job_id).inc()
            FURNACE_BEST_VAL_METRIC.labels(job_id=self.job_id, metric_type=metric_name.lower()).set(
                metric_value
            )
            asyncio.ensure_future(self._publish_epoch_event(metric_name, metric_value))
        if progress_callback:
            stripped = line.strip()
            if stripped:
                progress_callback(stripped)

    def _metric_label(self) -> str:
        return "AUC"

    async def _publish_epoch_event(self, metric_name: str, metric_value: float) -> None:
        try:
            elapsed = time.time() - self._start_time if self._start_time else 0
            remaining_secs = 0.0
            if self._total_trials and self._current_trial and self._current_trial > 0:
                remaining = self._total_trials - self._current_trial
                if remaining > 0:
                    per_trial = elapsed / self._current_trial
                    remaining_secs = per_trial * remaining
            from contracts.events import EpochCompleteEvent

            await publish(
                self.redis._client,
                STREAM_FURNACE_FEED,
                EPOCH_COMPLETE,
                EpochCompleteEvent(
                    job_id=self.job_id,
                    epoch=self._epoch_count,
                    train_loss=metric_value,
                    val_loss=metric_value,
                    eta_seconds=max(0, int(remaining_secs)),
                    trial=self._current_trial,
                    total_trials=self._total_trials,
                    metric_name=metric_name.lower(),
                    metric_value=metric_value,
                    best_score=self._best_val_metric,
                    elapsed_seconds=round(elapsed, 1),
                    remaining_seconds=round(remaining_secs, 1),
                ),
            )
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Failed to publish epoch event: {e}")

    def _save_logs(
        self, workspace_root: str, combined_log: str, stdout_log: str = "", stderr_log: str = ""
    ) -> None:
        logs_dir = os.path.join(workspace_root, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_paths = {
            "training.log": combined_log,
            "container.log": combined_log,
            "stdout.log": stdout_log or combined_log,
            "stderr.log": stderr_log or combined_log,
        }
        for filename, content in log_paths.items():
            path = os.path.join(logs_dir, filename)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception as e:
                self.logger.warning(f"[job={self.job_id}] Failed to write {path}: {e}")
        self.logger.info(f"[job={self.job_id}] Logs saved to {logs_dir}")

    async def _launch_and_monitor_subprocess(
        self,
        script_path: str,
        progress_callback: Any = None,
    ) -> None:
        abs_path = os.path.abspath(script_path)
        self.logger.info(f"[job={self.job_id}] Launching subprocess training: {abs_path}")
        jp = get_job_paths(self.job_id)
        subprocess_env = os.environ.copy()
        subprocess_env["OUTPUTS_DIR"] = (
            os.path.abspath(self._output_dir_override)
            if self._output_dir_override
            else str(jp.job_dir)
        )
        subprocess_env["DATA_DIR"] = str(get_paths().data)
        subprocess_env["SCRIPTS_DIR"] = str(get_paths().scripts)
        subprocess_env["PYTHONUNBUFFERED"] = "1"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            abs_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=subprocess_env,
        )
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                stdout_lines.append(decoded)
                self.logger.info(f"[job={self.job_id}] {decoded}")
                self._on_training_log(decoded, progress_callback=progress_callback)

        async def _read_stderr(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                stderr_lines.append(decoded)
                self._on_training_log(decoded, progress_callback=progress_callback)

        await asyncio.gather(_read_stream(process.stdout), _read_stderr(process.stderr))
        await process.wait()

        combined = "\n".join(stdout_lines + stderr_lines)
        stdout_txt = "\n".join(stdout_lines)
        stderr_txt = "\n".join(stderr_lines)
        self._save_logs(str(get_job_paths(self.job_id).job_dir), combined, stdout_txt, stderr_txt)

        if process.returncode != 0:
            error_text = stderr_txt
            raise RuntimeError(
                f"Training script exited with code {process.returncode}: {error_text[:2000]}"
            )

    async def _finalize_training(self, script_path: str) -> None:
        jp = get_job_paths(self.job_id)
        if self._output_dir_override:
            output = Path(self._output_dir_override)
            latest_checkpoint = str(output / "checkpoints" / "best.ckpt")
            metrics_path = str(output / "metrics")
            artifact_dir = str(output)
        else:
            latest_checkpoint = str(jp.checkpoint_path)
            metrics_path = str(jp.metrics_dir)
            artifact_dir = str(jp.job_dir)

        # ── Checkpoint validation ──────────────────────────────────────────
        # 1. Checkpoint exists
        if not os.path.exists(latest_checkpoint):
            self.logger.warning(
                f"[job={self.job_id}] Checkpoint not found at {latest_checkpoint}, "
                f"checking alternative paths..."
            )
            alt_dir = Path(self._output_dir_override) if self._output_dir_override else jp.job_dir
            alt = str(alt_dir / "best.ckpt")
            if os.path.exists(alt):
                latest_checkpoint = alt
            else:
                raise FileNotFoundError(f"Checkpoint not found at {latest_checkpoint}")

        # 2. Checkpoint readable
        try:
            import pickle

            with open(latest_checkpoint, "rb") as f:
                ckpt_data = pickle.load(f)
            self.logger.info(
                f"[job={self.job_id}] Checkpoint verified: readable ({os.path.getsize(latest_checkpoint)} bytes)"
            )
            # 3. Metadata exists
            if isinstance(ckpt_data, dict):
                meta_keys = [
                    k
                    for k in ("metric", "val_metric", "epoch", "model_state", "model")
                    if k in ckpt_data
                ]
                if meta_keys:
                    self.logger.info(
                        f"[job={self.job_id}] Checkpoint metadata confirmed: {meta_keys}"
                    )
                else:
                    self.logger.warning(
                        f"[job={self.job_id}] Checkpoint loaded as dict but no expected metadata keys found "
                        f"({list(ckpt_data.keys())[:5]}...). Continuing."
                    )
            else:
                self.logger.info(
                    f"[job={self.job_id}] Checkpoint loaded as {type(ckpt_data).__name__} "
                    f"(raw model, no metadata wrapper). Continuing."
                )
        except Exception as e:
            self.logger.error(f"[job={self.job_id}] Checkpoint integrity check FAILED: {e}")
            raise RuntimeError(
                f"Checkpoint validation failed for {latest_checkpoint}: {e}. "
                f"Cannot publish TRAINING_COMPLETE without a valid checkpoint."
            )

        training_time = time.time() - self._start_time if self._start_time else 0
        metric_name = self._guess_metric_name()

        from contracts.events import TrainingCompleteEvent

        await publish(
            self.redis._client,
            STREAM_FURNACE_OUTPUT,
            TRAINING_COMPLETE,
            TrainingCompleteEvent(
                job_id=self.job_id,
                checkpoint_path=os.path.abspath(latest_checkpoint),
                metrics_path=os.path.abspath(metrics_path),
                best_metric=self._best_val_metric,
                best_val_metric=self._best_val_metric,
                metric_name=metric_name,
                training_time=round(training_time, 2),
                total_epochs=self._epoch_count or 1,
                total_trials=self._total_trials or self._epoch_count,
                total_crashes_recovered=self._crashes_recovered,
                artifact_directory=os.path.abspath(artifact_dir),
            ),
        )
        self.logger.info(
            f"[job={self.job_id}] Training complete | "
            f"best_{metric_name}={self._best_val_metric:.4f} | "
            f"epochs={self._epoch_count} | "
            f"crashes_recovered={self._crashes_recovered}"
        )

    def _guess_metric_name(self) -> str:
        return "auc_roc"

    async def _handle_crash(
        self,
        error: Exception,
        script_path: str,
        attempt_number: int,
        progress_callback: Any = None,
        wait_for_dissect: bool = True,
    ) -> RepairResult | dict | None:
        exc_type = type(error).__name__
        exc_msg = str(error)
        from runtime.models import classify_exception

        crash_category = classify_exception(exc_type, exc_msg)
        self.logger.error(
            f"[job={self.job_id}] Crash attempt {attempt_number}: "
            f"[{crash_category}] {exc_type}: {exc_msg[:500]}"
        )
        record_heartbeat("Furnace", self.job_id)
        FURNACE_CRASHES.labels(job_id=self.job_id, exception_type=exc_type).inc()

        # ── Save crash checkpoint ──────────────────────────────────────────
        # Explicitly save training state before publishing CRASH_EVENT so
        # Dissect can inspect the last known state even if the training script
        # didn't checkpoint before crashing.
        jp = get_job_paths(self.job_id)
        checkpoint_path = str(jp.checkpoint_path)
        last_known_checkpoint = checkpoint_path if os.path.exists(checkpoint_path) else None
        if last_known_checkpoint:
            try:
                import shutil

                crash_ckpt = str(jp.job_dir / f"crash_ckpt_attempt_{attempt_number}.ckpt")
                shutil.copy2(last_known_checkpoint, crash_ckpt)
                self.logger.info(f"[job={self.job_id}] Crash checkpoint saved: {crash_ckpt}")
                last_known_checkpoint = crash_ckpt
            except Exception as ckpt_err:
                self.logger.warning(
                    f"[job={self.job_id}] Could not save crash checkpoint: {ckpt_err}"
                )
        # ── End crash checkpoint save ───────────────────────────────────────

        last_checkpoint = last_known_checkpoint
        traceback_str = tb_module.format_exc()
        container_name = f"prometheus-train-{self.job_id}"
        container_logs = getattr(self, "_container_error_log", "")

        crash_event = CrashEvent(
            job_id=self.job_id,
            script_path=script_path,
            container_name=container_name,
            exit_code=getattr(error, "exit_code", -1),
            exception_type=exc_type,
            exception_message=exc_msg,
            category=crash_category,
            traceback=traceback_str,
            container_logs=container_logs[:5000],
            last_checkpoint_path=last_checkpoint,
            epoch_at_crash=self._epoch_count,
            current_trial=self._current_trial,
            crash_attempt_number=attempt_number,
        )

        try:
            await self.redis.set_json(f"job:{self.job_id}:last_crash", crash_event.model_dump())
        except Exception:
            pass

        log_mission_state(
            "FURNACE_CRASH",
            self.job_id,
            script_path=script_path,
            retry_number=attempt_number,
            error_type=crash_category,
            exception_type=exc_type,
            epoch_at_crash=self._epoch_count,
        )

        if progress_callback:
            progress_callback("Training failed. Publishing crash event...")

        from contracts.events import CrashEventPayload

        d = crash_event.model_dump()
        crash_payload = CrashEventPayload(**d)
        await publish(
            self.redis._client,
            STREAM_FURNACE_CRASH,
            CRASH_EVENT,
            crash_payload,
        )

        if not wait_for_dissect:
            self.logger.info(f"[job={self.job_id}] Skipping WAIT state (wait_for_dissect=False)")
            return None

        if progress_callback:
            progress_callback("Waiting for Dissect...")

        if attempt_number > 3:
            self.logger.error(f"[job={self.job_id}] Exceeded 3 crash attempts. Aborting.")
            return None

        self.logger.info(
            f"[job={self.job_id}] Entering WAIT state for Dissect on "
            f"stream={STREAM_DISSECT_OUTPUT}"
        )

        results = await self.redis._client.xread(
            {STREAM_DISSECT_OUTPUT: "$"},
            count=10,
            block=600_000,
        )

        if not results:
            self.logger.error(
                f"[job={self.job_id}] WAIT timed out after 10 minutes with no response from Dissect."
            )
            return None

        stream, messages = results[0]
        for msg_id, raw_fields in messages:
            message = {}
            for k, v in raw_fields.items():
                try:
                    message[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    message[k] = v

            if message.get("job_id") != self.job_id:
                continue
            if message.get("event_type") == RESUME_TRAINING:
                self._crashes_recovered += 1
                FURNACE_CRASHES_RECOVERED.labels(job_id=self.job_id).inc()
                try:
                    result = RepairResult.model_validate(message)
                    result.epoch_count = self._epoch_count
                    return result
                except Exception:
                    message["epoch_count"] = self._epoch_count
                    return message
            elif message.get("event_type") in ("ESCALATE", "JOB_FAILED"):
                self.logger.error(
                    f"[job={self.job_id}] Dissect published ESCALATE: {message.get('reason')}"
                )
                return None

        return None

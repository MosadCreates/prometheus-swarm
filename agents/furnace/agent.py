"""Furnace Agent — The Trainer. Executes training and manages the train loop."""

import asyncio
import json
import os
import re
import sys
import traceback as tb_module

from agents.base import BaseAgent
from agents.furnace.prompts import FURNACE_SYSTEM_PROMPT
from bus.events import (
    CRASH_EVENT,
    EPOCH_COMPLETE,
    ESCALATE,
    RESUME_TRAINING,
    TRAINING_COMPLETE,
    STREAM_DISSECT_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_FURNACE_FEED,
    STREAM_FURNACE_OUTPUT,
)
from bus.publisher import publish
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
from training.docker_manager import DockerManager


class FurnaceAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(job_id=job_id)
        self.docker = DockerManager()
        self._best_val_metric: float = 0.0
        self._epoch_count: int = 0
        self._crashes_recovered: int = 0

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
    ) -> None:
        self.logger.info(f"[job={self.job_id}] Furnace starting")
        AGENT_RUNS.labels(agent="Furnace", job_id=self.job_id).inc()
        record_heartbeat("Furnace", self.job_id)
        if not script_path:
            record_agent_error("Furnace", self.job_id, "missing_script_path")
            raise ValueError(f"script_path required for Furnace job {self.job_id}")

        self._search_space_json = search_space_json
        current_script = script_path
        crash_attempt = 0
        last_checkpoint: str | None = None

        while True:
            try:
                if use_docker:
                    await self._launch_and_monitor_docker(
                        current_script, resume_from=last_checkpoint
                    )
                else:
                    await self._launch_and_monitor_subprocess(current_script)
                await self._finalize_training(current_script)
                return
            except Exception as e:
                crash_attempt += 1
                resume_payload = await self._handle_crash(
                    e,
                    current_script,
                    crash_attempt,
                )
                if resume_payload is None:
                    self.logger.error(
                        f"[job={self.job_id}] Furnace giving up after crash handling."
                    )
                    return
                current_script = resume_payload["patched_script_path"]
                last_checkpoint = resume_payload.get("last_checkpoint_path") or last_checkpoint
                self.logger.info(
                    f"[job={self.job_id}] Resuming with patched script: " f"{current_script}"
                )

    async def _launch_and_monitor_docker(
        self, script_path: str, resume_from: str | None = None
    ) -> None:
        """Launch training in a Docker container and wait for completion."""
        abs_script = os.path.abspath(script_path)
        script_name = os.path.basename(abs_script)

        FURNACE_TRAINING_RUNS.labels(job_id=self.job_id, mode="docker").inc()
        record_heartbeat("Furnace", self.job_id)
        self.logger.info(f"[job={self.job_id}] Launching Docker training: {script_name}")

        volumes = {
            os.path.abspath("scripts"): {"bind": "/app/scripts", "mode": "ro"},
            os.path.abspath("data"): {"bind": "/app/data", "mode": "ro"},
            os.path.abspath("outputs"): {"bind": "/app/outputs", "mode": "rw"},
        }

        environment = {
            "JOB_ID": self.job_id,
            "DATA_DIR": "/app/data",
            "OUTPUTS_DIR": "/app/outputs",
            "PYTHONUNBUFFERED": "1",
        }

        if resume_from:
            environment["RESUME_CHECKPOINT"] = resume_from
            self.logger.info(f"[job={self.job_id}] Resuming from checkpoint: {resume_from}")

        search_json = getattr(self, "_search_space_json", None)
        if search_json:
            environment["SEARCH_SPACE_JSON"] = search_json

        await self.docker.launch_container(
            job_id=self.job_id,
            run_cmd=[f"/app/scripts/{script_name}"],
            volumes=volumes,
            environment=environment,
        )

        exit_code, logs = await self.docker.wait_for_exit(
            self.job_id,
            timeout=3600,
        )

        await self.docker.kill_container(self.job_id)

        for log_line in logs.split("\n"):
            await self._publish_epoch_from_line(log_line)

        if exit_code != 0:
            raise RuntimeError(f"Training script exited with code {exit_code}: " f"{logs[:2000]}")

    async def _publish_epoch_from_line(self, line: str) -> None:
        self._epoch_count += 1
        FURNACE_EPOCHS.labels(job_id=self.job_id).inc()
        match = re.search(r"Accuracy:\s*([\d.]+)", line)
        if match:
            val = float(match.group(1))
            self._best_val_metric = max(self._best_val_metric, val)
            FURNACE_BEST_VAL_METRIC.labels(job_id=self.job_id, metric_type="accuracy").set(val)
            await publish(
                self.redis._client,
                STREAM_FURNACE_FEED,
                EPOCH_COMPLETE,
                {
                    "job_id": self.job_id,
                    "epoch": self._epoch_count,
                    "train_loss": max(0.0, 1.0 - val * 2),
                    "val_loss": max(0.0, 1.0 - val * 2),
                    "accuracy": val,
                    "eta_seconds": max(0, 60 - self._epoch_count * 2),
                },
            )
            return
        match = re.search(r"RMSE:\s*([\d.]+)", line)
        if match:
            val = float(match.group(1))
            self._best_val_metric = (
                val if self._best_val_metric == 0.0 else min(self._best_val_metric, val)
            )
            FURNACE_BEST_VAL_METRIC.labels(job_id=self.job_id, metric_type="rmse").set(val)
            await publish(
                self.redis._client,
                STREAM_FURNACE_FEED,
                EPOCH_COMPLETE,
                {
                    "job_id": self.job_id,
                    "epoch": self._epoch_count,
                    "train_loss": val,
                    "val_loss": val,
                    "eta_seconds": max(0, 60 - self._epoch_count * 2),
                },
            )
            return

    async def _launch_and_monitor_subprocess(self, script_path: str) -> None:
        """Launch training as a subprocess (fallback, for testing without Docker)."""
        abs_path = os.path.abspath(script_path)
        self.logger.info(f"[job={self.job_id}] Launching subprocess training: {abs_path}")

        process = await asyncio.create_subprocess_exec(
            sys.executable,
            abs_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        async def _read_stream(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                self.logger.info(f"[job={self.job_id}] {decoded}")
                await self._publish_epoch_from_line(decoded)

        stderr_lines = []

        async def _read_stderr(stream):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                stderr_lines.append(decoded)

        await asyncio.gather(
            _read_stream(process.stdout),
            _read_stderr(process.stderr),
        )
        await process.wait()

        if process.returncode != 0:
            error_text = "\n".join(stderr_lines)
            raise RuntimeError(
                f"Training script exited with code {process.returncode}: " f"{error_text[:2000]}"
            )

    async def _finalize_training(self, script_path: str) -> None:
        latest_checkpoint = f"outputs/{self.job_id}/checkpoints/best.ckpt"

        if os.path.exists(latest_checkpoint):
            await publish(
                self.redis._client,
                STREAM_FURNACE_OUTPUT,
                TRAINING_COMPLETE,
                {
                    "job_id": self.job_id,
                    "checkpoint_path": os.path.abspath(latest_checkpoint),
                    "best_val_metric": self._best_val_metric,
                    "total_epochs": self._epoch_count or 1,
                    "total_crashes_recovered": self._crashes_recovered,
                },
            )
            self.logger.info(
                f"[job={self.job_id}] Training complete | "
                f"best_val_metric={self._best_val_metric:.4f} | "
                f"epochs={self._epoch_count} | "
                f"crashes_recovered={self._crashes_recovered}"
            )
        else:
            raise FileNotFoundError(f"Checkpoint not found at {latest_checkpoint}")

    async def _handle_crash(
        self,
        error: Exception,
        script_path: str,
        attempt_number: int,
    ) -> dict | None:
        self.logger.error(f"[job={self.job_id}] Crash attempt {attempt_number}: {error}")
        record_heartbeat("Furnace", self.job_id)
        FURNACE_CRASHES.labels(job_id=self.job_id, exception_type=type(error).__name__).inc()

        checkpoint_path = f"outputs/{self.job_id}/checkpoints/best.ckpt"
        last_checkpoint = checkpoint_path if os.path.exists(checkpoint_path) else None

        await publish(
            self.redis._client,
            STREAM_FURNACE_CRASH,
            CRASH_EVENT,
            {
                "job_id": self.job_id,
                "exception_type": type(error).__name__,
                "exception_message": str(error),
                "traceback": tb_module.format_exc(),
                "script_path": script_path,
                "last_checkpoint_path": last_checkpoint or "",
                "epoch_at_crash": self._epoch_count,
                "crash_attempt_number": attempt_number,
            },
        )

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
                f"[job={self.job_id}] WAIT timed out after 10 minutes "
                f"with no response from Dissect."
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
                message["epoch_count"] = self._epoch_count
                return message
            elif message.get("event_type") == ESCALATE:
                self.logger.error(
                    f"[job={self.job_id}] Dissect published ESCALATE: " f"{message.get('reason')}"
                )
                return None

        return None

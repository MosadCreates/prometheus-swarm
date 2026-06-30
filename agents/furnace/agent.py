"""Furnace Agent ? The Trainer. Executes training and manages the train loop."""

import asyncio
import json
import os
import sys
import traceback as tb_module

from agents.base import BaseAgent
from agents.furnace.prompts import FURNACE_SYSTEM_PROMPT
from bus.events import (
    CRASH_EVENT,
    ESCALATE,
    RESUME_TRAINING,
    TRAINING_COMPLETE,
    STREAM_DISSECT_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_FURNACE_OUTPUT,
)
from bus.publisher import publish
from training.docker_manager import DockerManager


class FurnaceAgent(BaseAgent):
    def __init__(self, job_id: str):
        super().__init__(job_id=job_id)
        self.docker = DockerManager()

    @property
    def agent_name(self) -> str:
        return "Furnace"

    @property
    def system_prompt(self) -> str:
        return FURNACE_SYSTEM_PROMPT

    async def run(self, script_path: str, use_docker: bool = True) -> None:
        self.logger.info(f"[job={self.job_id}] Furnace starting")
        if not script_path:
            raise ValueError(f"script_path required for Furnace job {self.job_id}")

        current_script = script_path
        crash_attempt = 0

        while True:
            try:
                if use_docker:
                    await self._launch_and_monitor_docker(current_script)
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
                self.logger.info(
                    f"[job={self.job_id}] Resuming with patched script: " f"{current_script}"
                )

    async def _launch_and_monitor_docker(self, script_path: str) -> None:
        """Launch training in a Docker container and wait for completion."""
        abs_script = os.path.abspath(script_path)
        script_name = os.path.basename(abs_script)

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

        await self.docker.launch_container(
            job_id=self.job_id,
            run_cmd=["python", f"/app/scripts/{script_name}"],
            volumes=volumes,
            environment=environment,
        )

        exit_code, logs = await self.docker.wait_for_exit(
            self.job_id,
            timeout=3600,
        )

        await self.docker.kill_container(self.job_id)

        if exit_code != 0:
            raise RuntimeError(f"Training script exited with code {exit_code}: " f"{logs[:2000]}")

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
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_text = stderr.decode("utf-8", errors="replace")
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
                    "best_val_metric": 0.0,
                    "total_epochs": 1,
                    "total_crashes_recovered": 0,
                },
            )
            self.logger.info(f"[job={self.job_id}] Training complete")
        else:
            raise FileNotFoundError(f"Checkpoint not found at {latest_checkpoint}")

    async def _handle_crash(
        self,
        error: Exception,
        script_path: str,
        attempt_number: int,
    ) -> dict | None:
        self.logger.error(f"[job={self.job_id}] Crash attempt {attempt_number}: {error}")

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
                "epoch_at_crash": 0,
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
                return message
            elif message.get("event_type") == ESCALATE:
                self.logger.error(
                    f"[job={self.job_id}] Dissect published ESCALATE: " f"{message.get('reason')}"
                )
                return None

        return None

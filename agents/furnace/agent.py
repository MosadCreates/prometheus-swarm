"""Furnace Agent ? The Trainer. Executes training and manages the train loop."""

import asyncio
import os
import sys

from agents.base import BaseAgent
from agents.furnace.prompts import FURNACE_SYSTEM_PROMPT
from agents.furnace.tools import launch_training_container, monitor_loss
from bus.events import (
    TRAINING_SCRIPT_READY, EPOCH_COMPLETE, TRAINING_COMPLETE,
    CRASH_EVENT, RESUME_TRAINING,
    STREAM_FURNACE_FEED, STREAM_FURNACE_OUTPUT, STREAM_FURNACE_CRASH,
    STREAM_DISSECT_OUTPUT, STREAM_FORGE_OUTPUT,
    GROUP_FURNACE,
)
from bus.publisher import publish
from bus.consumer import ensure_consumer_group, consume_one


class FurnaceAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Furnace"

    @property
    def system_prompt(self) -> str:
        return FURNACE_SYSTEM_PROMPT

    async def run(self) -> None:
        self.logger.info(f"[job={self.job_id}] Furnace starting")

        script_path = self.job_data.get("script_path")
        if not script_path:
            raise ValueError(f"script_path required for Furnace job {self.job_id}")

        pid = await launch_training_container(script_path, self.job_id)

        try:
            await asyncio.sleep(1)
            await self._finalize_training(script_path)
        except Exception as e:
            await self._handle_crash(e, script_path, 0)

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

    async def _handle_crash(self, error: Exception, script_path: str, epoch: int) -> None:
        self.logger.error(f"[job={self.job_id}] Crash: {error}")

        await publish(
            self.redis._client,
            STREAM_FURNACE_CRASH,
            CRASH_EVENT,
            {
                "job_id": self.job_id,
                "exception_type": type(error).__name__,
                "exception_message": str(error),
                "traceback": "",
                "script_path": script_path,
                "last_checkpoint_path": f"outputs/{self.job_id}/checkpoints/best.ckpt",
                "epoch_at_crash": epoch,
                "crash_attempt_number": 1,
            },
        )

"""
Scout Agent ? The Perceiver.
Accepts a raw problem description + dataset, produces a mission_brief.json.
"""

import json
import os
from typing import Any

from agents.base import BaseAgent
from agents.scout.prompts import SCOUT_SYSTEM_PROMPT
from agents.scout.tools import (
    detect_modality, run_eda, infer_task_type,
    select_evaluation_metric, write_mission_brief,
)
from bus.events import MISSION_BRIEF_READY, STREAM_SCOUT_OUTPUT
from bus.publisher import publish


class ScoutAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Scout"

    @property
    def system_prompt(self) -> str:
        return SCOUT_SYSTEM_PROMPT

    async def run(self) -> None:
        self.logger.info(f"[job={self.job_id}] Scout starting")

        # In Phase 1, we bypass LLM and use deterministic tools directly
        # In Phase 2+, Scout will call LLM which calls tools
        problem_description = self.job_data.get("problem_description", "")
        file_path = self.job_data.get("file_path", "")
        target_column = self.job_data.get("target_column")

        if not file_path:
            raise ValueError(f"file_path required for Scout job {self.job_id}")

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        eda = run_eda(file_path, target_column)
        if "error" in eda:
            raise ValueError(f"EDA failed: {eda['error']}")

        brief = write_mission_brief(
            eda_results=eda,
            job_id=self.job_id,
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
            constraints=self.job_data.get("constraints"),
        )

        mission_key = f"job:{self.job_id}:mission_brief"
        await self.redis.set_json(mission_key, brief)

        await self.redis.set_str(f"job:{self.job_id}:file_path", file_path)
        await self.redis.set_str(
            f"job:{self.job_id}:problem_description", problem_description
        )

        await publish(
            self.redis._client,
            STREAM_SCOUT_OUTPUT,
            MISSION_BRIEF_READY,
            {"job_id": self.job_id, "mission_brief_redis_key": mission_key},
        )

        self.logger.info(
            f"[job={self.job_id}] Mission brief ready | "
            f"task={brief['task_type']} modality={brief['modality']}"
        )

    async def run_with_data(
        self, problem_description: str, file_path: str,
        target_column: str | None = None, constraints: dict | None = None,
    ) -> dict[str, Any]:
        self.job_data = {
            "problem_description": problem_description,
            "file_path": file_path,
            "target_column": target_column,
            "constraints": constraints,
        }
        await self.run()
        return await self.redis.get_json(f"job:{self.job_id}:mission_brief")

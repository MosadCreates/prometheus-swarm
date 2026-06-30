"""Forge Agent ? The Architect."""

from agents.base import BaseAgent
from agents.forge.prompts import FORGE_SYSTEM_PROMPT
from agents.forge.decision_tree import select_architecture
from agents.forge.tools import write_training_script, define_optuna_space
from bus.events import TRAINING_SCRIPT_READY, STREAM_FORGE_OUTPUT
from bus.publisher import publish


class ForgeAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Forge"

    @property
    def system_prompt(self) -> str:
        return FORGE_SYSTEM_PROMPT

    async def run(self) -> None:
        self.logger.info(f"[job={self.job_id}] Forge starting")

        brief_key = f"job:{self.job_id}:mission_brief"
        brief = await self.redis.get_json(brief_key)
        if not brief:
            raise ValueError(f"Mission brief not found at {brief_key}")

        architecture = select_architecture(brief)
        search_space = define_optuna_space(architecture)

        script_path = write_training_script(brief, self.job_id)

        search_key = f"job:{self.job_id}:search_space"
        await self.redis.set_json(search_key, search_space)

        await publish(
            self.redis._client,
            STREAM_FORGE_OUTPUT,
            TRAINING_SCRIPT_READY,
            {
                "job_id": self.job_id,
                "script_path": script_path,
                "search_space_redis_key": search_key,
            },
        )

        self.logger.info(f"[job={self.job_id}] Training script ready at {script_path}")

    async def run_with_brief(self, brief: dict) -> str:
        brief_key = f"job:{self.job_id}:mission_brief"
        await self.redis.set_json(brief_key, brief)
        await self.run()
        return f"scripts/training_script_{self.job_id}.py"

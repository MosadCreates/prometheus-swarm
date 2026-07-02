"""Forge Agent ? The Architect."""

import asyncio
import uuid

from agents.base import BaseAgent
from agents.forge.decision_tree import select_architecture, select_imbalance_strategy
from agents.forge.prompts import FORGE_SYSTEM_PROMPT
from agents.forge.tools import write_training_script, define_optuna_space
from bus.events import TRAINING_SCRIPT_READY, STREAM_FORGE_OUTPUT
from bus.publisher import publish
from shared.metrics import (
    FORGE_ARCHITECTURE_SELECTIONS,
    FORGE_SCRIPTS_GENERATED,
    FORGE_SCRIPTS_GENERATION_DURATION,
    AGENT_RUNS,
    record_heartbeat,
    record_agent_error,
)


class ForgeAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Forge"

    @property
    def system_prompt(self) -> str:
        return FORGE_SYSTEM_PROMPT

    async def run(self) -> None:
        self.logger.info(f"[job={self.job_id}] Forge starting")
        AGENT_RUNS.labels(agent="Forge", job_id=self.job_id).inc()
        record_heartbeat("Forge", self.job_id)

        brief_key = f"job:{self.job_id}:mission_brief"
        brief = await self.redis.get_json(brief_key)
        if not brief:
            record_agent_error("Forge", self.job_id, "missing_brief")
            raise ValueError(f"Mission brief not found at {brief_key}")

        modality = brief.get("modality", "tabular")
        task_type = brief.get("task_type", "classification")
        dataset = brief.get("dataset", {})
        num_rows = dataset.get("num_rows", 0)
        class_imbalance_ratio = brief.get("data_quality", {}).get("class_imbalance_ratio", None)

        # Query architecture memory for similar past decisions
        similar = []
        try:
            from memory.collections.architecture_memory import (
                query_similar_architectures,
            )

            similar = query_similar_architectures(modality, task_type, k=3)
        except Exception:
            self.logger.warning(f"[job={self.job_id}] Architecture memory query failed")

        # Select architecture (uses memory to boost successful past choices)
        architecture = select_architecture(brief, use_memory=True, similar_architectures=similar)
        imbalance_strategy = select_imbalance_strategy(class_imbalance_ratio, brief)

        FORGE_ARCHITECTURE_SELECTIONS.labels(architecture=architecture, job_id=self.job_id).inc()

        # On retry, try the next-best architecture if available
        retry_count_str = await self.redis.get_str(f"job:{self.job_id}:retry_count")
        retry_count = int(retry_count_str) if retry_count_str else 0
        if retry_count > 0:
            alternatives = {
                "lightgbm": "xgboost",
                "xgboost": "lightgbm",
                "tabnet": "lightgbm",
                "distilbert": "lightgbm",
                "efficientnet": "lightgbm",
            }
            alt = alternatives.get(architecture, "lightgbm")
            self.logger.info(
                f"[job={self.job_id}] Retry #{retry_count}: "
                f"switching from {architecture} to {alt}"
            )
            architecture = alt
            FORGE_ARCHITECTURE_SELECTIONS.labels(
                architecture=architecture, job_id=self.job_id
            ).inc()

        search_space = define_optuna_space(architecture)

        _start = asyncio.get_event_loop().time()
        script_path = write_training_script(brief, self.job_id)
        _elapsed = asyncio.get_event_loop().time() - _start
        FORGE_SCRIPTS_GENERATED.labels(architecture=architecture, job_id=self.job_id).inc()
        FORGE_SCRIPTS_GENERATION_DURATION.labels(
            architecture=architecture, job_id=self.job_id
        ).observe(_elapsed)
        record_heartbeat("Forge", self.job_id)

        search_key = f"job:{self.job_id}:search_space"
        await self.redis.set_json(search_key, search_space)

        # Store this architecture decision in long-term memory
        decision_id = str(uuid.uuid4())
        try:
            from memory.collections.architecture_memory import store_architecture

            store_architecture(
                decision_id=decision_id,
                job_id=self.job_id,
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
                class_imbalance_ratio=class_imbalance_ratio,
                model_selected=architecture,
                imbalance_strategy=imbalance_strategy,
            )
            await self.redis.set_str(f"job:{self.job_id}:architecture_decision_id", decision_id)
        except Exception:
            self.logger.warning(f"[job={self.job_id}] Failed to store architecture decision")

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

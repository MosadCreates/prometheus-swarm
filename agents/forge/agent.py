"""Forge Agent ? The Architect."""

import asyncio


from agents.base import BaseAgent
from agents.forge.decision_tree import select_architecture, select_imbalance_strategy
from agents.forge.planner import create_plan, format_plan_summary
from agents.forge.prompts import FORGE_SYSTEM_PROMPT
from agents.forge.tools import write_training_script, define_optuna_space
from bus.events import TRAINING_SCRIPT_READY, STREAM_FORGE_OUTPUT
from bus.publisher import publish
from shared.metrics import (
    FORGE_ARCHITECTURE_SELECTIONS,
    FORGE_SCRIPTS_GENERATED,
    FORGE_SCRIPTS_GENERATION_DURATION,
    FORGE_PLANS_GENERATED,
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

        # ── Prefer rich MissionSpecification (Stage 1) ──────────────────
        spec_key = f"job:{self.job_id}:mission_spec"
        spec = await self.redis.get_json(spec_key)
        if spec:
            objective = spec.get("objective", {})
            dataset_analysis = spec.get("dataset_analysis", {})
            data_quality = spec.get("data_quality", {})
            reasoning = brief.get("engineering_reasoning", {})
            if spec.get("engineering_decisions"):
                reasoning.update(spec["engineering_decisions"])
        else:
            objective = {}
            dataset_analysis = brief.get("dataset", {})
            data_quality = brief.get("data_quality", {})
            reasoning = brief.get("engineering_reasoning", {})

        modality = objective.get("modality", brief.get("modality", "tabular"))
        task_type = objective.get("task_type", brief.get("task_type", "classification"))
        dataset = dataset_analysis if dataset_analysis else brief.get("dataset", {})
        num_rows = dataset.get("num_rows", 0)
        class_imbalance_ratio = data_quality.get("class_imbalance_ratio", None)
        arch_decision = reasoning.get("architecture", {})
        scout_alternatives: list[str] = (
            arch_decision.get("alternatives", []) if arch_decision else []
        )

        if arch_decision and arch_decision.get("selected"):
            architecture = arch_decision["selected"]
            self.logger.info(
                f"[job={self.job_id}] Using Scout-recommended architecture: {architecture}"
            )
        else:
            # Backward compatible: use decision tree when no reasoning exists
            similar = []
            try:
                from memory.collections.architecture_memory import (
                    query_similar_architectures,
                )

                similar = query_similar_architectures(modality, task_type, k=3)
            except Exception:
                self.logger.warning(f"[job={self.job_id}] Architecture memory query failed")
            architecture = select_architecture(
                brief, use_memory=True, similar_architectures=similar
            )

        imbalance_strategy = select_imbalance_strategy(class_imbalance_ratio, brief)

        FORGE_ARCHITECTURE_SELECTIONS.labels(architecture=architecture, job_id=self.job_id).inc()

        # On retry, try Scout's alternatives first, then fall back to hardcoded map
        retry_count_str = await self.redis.get_str(f"job:{self.job_id}:retry_count")
        retry_count = int(retry_count_str) if retry_count_str else 0
        if retry_count > 0:
            if scout_alternatives:
                alt_candidates = [a for a in scout_alternatives if a != architecture]
                alt = alt_candidates[0] if alt_candidates else scout_alternatives[0]
            else:
                alt_map = {
                    "lightgbm": "xgboost",
                    "xgboost": "lightgbm",
                    "tabnet": "lightgbm",
                    "distilbert": "lightgbm",
                    "efficientnet": "lightgbm",
                }
                alt = alt_map.get(architecture, "lightgbm")
            self.logger.info(
                f"[job={self.job_id}] Retry #{retry_count}: "
                f"switching from {architecture} to {alt}"
            )
            architecture = alt
            FORGE_ARCHITECTURE_SELECTIONS.labels(
                architecture=architecture, job_id=self.job_id
            ).inc()

        search_space = define_optuna_space(architecture)

        # ── Generate Engineering Plan (Stage 2) ──────────────────────────────
        plan_key = f"job:{self.job_id}:engineering_plan"
        plan = None
        try:
            plan = create_plan(reasoning, brief)
            await self.redis.set_json(plan_key, plan)
            FORGE_PLANS_GENERATED.labels(job_id=self.job_id).inc()
            plan_summary = format_plan_summary(plan)
            self.logger.info(f"[job={self.job_id}] Engineering plan stored at {plan_key}")
        except Exception as exc:
            self.logger.warning(f"[job={self.job_id}] Plan generation failed: {exc}")
            plan = None
            plan_summary = None

        confidence = reasoning.get("overall_confidence") if isinstance(reasoning, dict) else None
        if confidence is not None:
            self.logger.info(
                f"[job={self.job_id}] Scout overall_confidence={confidence} "
                f"— routing generation strategy"
            )

        _start = asyncio.get_event_loop().time()
        script_path = write_training_script(
            brief,
            self.job_id,
            design_summary=plan_summary,
            architecture=architecture,
            engineering_plan=plan,
            redis_client=self.redis,
            confidence=confidence,
        )
        _elapsed = asyncio.get_event_loop().time() - _start
        FORGE_SCRIPTS_GENERATED.labels(architecture=architecture, job_id=self.job_id).inc()
        FORGE_SCRIPTS_GENERATION_DURATION.labels(
            architecture=architecture, job_id=self.job_id
        ).observe(_elapsed)
        record_heartbeat("Forge", self.job_id)

        search_key = f"job:{self.job_id}:search_space"
        await self.redis.set_json(search_key, search_space)

        # Store this architecture decision in long-term memory
        decision_id = f"{self.job_id}:{architecture}"
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

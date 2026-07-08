"""
Scout Agent ? The Perceiver.
Accepts a raw problem description + dataset, produces a mission_brief.json
with structured engineering reasoning (Stage 1).
"""

import os
from typing import Any

import pandas as pd

from agents.base import BaseAgent
from agents.scout.prompts import SCOUT_SYSTEM_PROMPT
from agents.scout.reasoning import (
    reason_problem_type,
    reason_data_quality,
    reason_leakage,
    reason_preprocessing,
    reason_imbalance,
    reason_architecture,
    reason_validation,
    reason_risks,
    reason_feature_engineering,
    reason_outliers,
    adjust_with_experience,
)
from agents.scout.tools import (
    detect_modality,
    infer_task_type,
    run_eda,
    write_mission_brief,
    write_mission_spec,
)
from bus.events import MISSION_BRIEF_READY, STREAM_SCOUT_OUTPUT
from bus.publisher import publish
from shared.metrics import (
    SCOUT_DATASETS_PROCESSED,
    SCOUT_ANALYSIS_DURATION,
    AGENT_RUNS,
    record_heartbeat,
    record_agent_error,
)


class ScoutAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Scout"

    @property
    def system_prompt(self) -> str:
        return SCOUT_SYSTEM_PROMPT

    async def run(self) -> None:
        self.logger.info(f"[job={self.job_id}] Scout starting")
        AGENT_RUNS.labels(agent="Scout", job_id=self.job_id).inc()
        record_heartbeat("Scout", self.job_id)

        # In Phase 1, we bypass LLM and use deterministic tools directly
        # In Phase 2+, Scout will call LLM which calls tools
        import time as _time

        _start = _time.time()
        problem_description = self.job_data.get("problem_description", "")
        file_path = self.job_data.get("file_path", "")
        target_column = self.job_data.get("target_column")

        if not file_path:
            record_agent_error("Scout", self.job_id, "missing_file_path")
            raise ValueError(f"file_path required for Scout job {self.job_id}")

        if not os.path.exists(file_path):
            record_agent_error("Scout", self.job_id, "file_not_found")
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        modality_override = self.job_data.get("modality_override")

        eda = run_eda(file_path, target_column)
        if "error" in eda:
            record_agent_error("Scout", self.job_id, "eda_failed")
            raise ValueError(f"EDA failed: {eda['error']}")

        # ── Engineering Reasoning (Stage 1) ──────────────────────────────
        df_sample = pd.read_csv(file_path, nrows=100)
        modality = detect_modality(file_path, modality_override=modality_override)
        task_type = infer_task_type(target_column, eda.get("column_types", {}), file_path)
        reasoning = {
            "problem_type": reason_problem_type(problem_description, df_sample, target_column),
            "data_quality": reason_data_quality(eda),
            "leakage": reason_leakage(df_sample, target_column),
            "preprocessing": reason_preprocessing(df_sample),
            "feature_engineering": reason_feature_engineering(df_sample, target_column),
            "outliers": reason_outliers(eda),
            "architecture": reason_architecture(
                {
                    "modality": modality,
                    "task_type": task_type,
                    "dataset": {"num_rows": eda.get("num_rows", 0)},
                    "data_quality": {"class_imbalance_ratio": eda.get("class_imbalance_ratio")},
                }
            ),
            "validation": reason_validation(
                task_type,
                eda.get("num_rows", 0),
                eda.get("class_imbalance_ratio"),
            ),
            "risks": reason_risks(eda, problem_description),
        }
        imbalance_dec = reason_imbalance(eda)
        if imbalance_dec:
            reasoning["imbalance"] = imbalance_dec

        # ── Experience-based confidence adjustment + pattern reuse (Stage 3) ──
        try:
            from memory.collections.experience_memory import (
                query_best_pipeline,
                query_by_dataset_profile,
                query_similar_experiences,
            )

            modality = detect_modality(file_path, modality_override=modality_override)
            task_type = infer_task_type(target_column, eda.get("column_types", {}), file_path)
            num_rows = eda.get("num_rows", 0)
            num_columns = eda.get("num_columns", 0)
            imbalance = eda.get("class_imbalance_ratio")

            # Query by rich dataset profile for better pattern matching
            experiences = query_by_dataset_profile(
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
                num_columns=num_columns,
                imbalance_ratio=imbalance,
                k=5,
            )
            if experiences:
                reasoning = adjust_with_experience(reasoning, experiences)
                self.logger.info(
                    f"[job={self.job_id}] Adjusted confidences from {len(experiences)} "
                    f"past experiences"
                )

            # Query best pipeline for similar problems to surface proven patterns
            best_pipelines = query_best_pipeline(
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
                num_columns=num_columns,
                k=3,
            )
            if best_pipelines:
                reasoning["experience_recommendations"] = [
                    {
                        "architecture": p.get("architecture", ""),
                        "achieved_metric": p.get("achieved_metric"),
                        "total_crashes": p.get("total_crashes"),
                        "pipeline_steps": p.get("pipeline_steps", []),
                        "similarity_score": p.get("similarity_score"),
                    }
                    for p in best_pipelines
                ]
                self.logger.info(
                    f"[job={self.job_id}] Found {len(best_pipelines)} successful "
                    f"past pipelines for similar problems"
                )
        except Exception as exc:
            self.logger.warning(f"[job={self.job_id}] Experience query failed (non-fatal): {exc}")

        # Compute overall confidence as average of all decision confidences
        confs = [
            d["confidence"] for d in reasoning.values() if isinstance(d, dict) and "confidence" in d
        ]
        reasoning["overall_confidence"] = round(sum(confs) / len(confs), 2) if confs else 0.85

        _elapsed = _time.time() - _start
        SCOUT_DATASETS_PROCESSED.labels(job_id=self.job_id, status="success").inc()
        SCOUT_ANALYSIS_DURATION.labels(job_id=self.job_id).observe(_elapsed)

        brief = write_mission_brief(
            eda_results=eda,
            job_id=self.job_id,
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
            constraints=self.job_data.get("constraints"),
            modality_override=modality_override,
            engineering_reasoning=reasoning,
        )

        mission_key = f"job:{self.job_id}:mission_brief"
        await self.redis.set_json(mission_key, brief)

        # ── Rich MissionSpecification (Stage 1) ─────────────────────────
        spec = write_mission_spec(
            eda_results=eda,
            job_id=self.job_id,
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
            constraints=self.job_data.get("constraints"),
            modality_override=modality_override,
            engineering_reasoning=reasoning,
        )
        spec_key = f"job:{self.job_id}:mission_spec"
        await self.redis.set_json(spec_key, spec)

        await self.redis.set_str(f"job:{self.job_id}:file_path", file_path)
        await self.redis.set_str(f"job:{self.job_id}:problem_description", problem_description)

        await publish(
            self.redis._client,
            STREAM_SCOUT_OUTPUT,
            MISSION_BRIEF_READY,
            {
                "job_id": self.job_id,
                "mission_brief_redis_key": mission_key,
                "mission_spec_redis_key": spec_key,
            },
        )

        self.logger.info(
            f"[job={self.job_id}] MissionSpecification ready | "
            f"task={brief['task_type']} modality={brief['modality']} "
            f"confidence={reasoning.get('overall_confidence', '?')}"
        )

    async def run_with_data(
        self,
        problem_description: str,
        file_path: str,
        target_column: str | None = None,
        constraints: dict | None = None,
        modality_override: str | None = None,
    ) -> dict[str, Any]:
        self.job_data = {
            "problem_description": problem_description,
            "file_path": file_path,
            "target_column": target_column,
            "constraints": constraints,
            "modality_override": modality_override,
        }
        await self.run()
        return await self.redis.get_json(f"job:{self.job_id}:mission_brief")

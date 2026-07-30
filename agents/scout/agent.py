"""
Scout Agent — The Perceiver.
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
from bus.agent_events import AgentEventTracker, emit_subaction_progress
from bus.events import MISSION_BRIEF_READY, STREAM_SCOUT_OUTPUT
from bus.publisher import publish
from prometheus.cli.mission.state_logger import log_mission_state
from shared.metrics import (
    SCOUT_DATASETS_PROCESSED,
    SCOUT_ANALYSIS_DURATION,
    AGENT_RUNS,
    record_heartbeat,
    record_agent_error,
)
from prometheus.ui.detail_types import (
    ScoutDatasetDetail,
    ScoutDataQualityDetail,
    ScoutTaskDetail,
    ScoutMetricDetail,
    ScoutModalityDetail,
    ScoutRecommendationDetail,
    ScoutConfidenceDetail,
    DetailType,
)


class ScoutAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Scout"

    @property
    def system_prompt(self) -> str:
        return SCOUT_SYSTEM_PROMPT

    async def run(
        self,
        progress_callback: Any = None,
    ) -> None:
        self.logger.info(f"[job={self.job_id}] Scout starting")
        AGENT_RUNS.labels(agent="Scout", job_id=self.job_id).inc()
        record_heartbeat("Scout", self.job_id)

        log_mission_state("SCOUT_START", self.job_id, brief=self.job_data)

        import time as _time

        _start = _time.time()

        tracker = AgentEventTracker(self.redis._client, self.job_id, "Scout")
        await tracker.emit("thinking", "Starting analysis...")

        if progress_callback:
            progress_callback("Starting mission...")

        problem_description = self.job_data.get("problem_description", "")
        file_path = self.job_data.get("file_path", "")
        target_column = self.job_data.get("target_column")

        if not file_path:
            await tracker.error("Missing file path", detail={"error": "file_path required"})
            record_agent_error("Scout", self.job_id, "missing_file_path")
            raise ValueError(f"file_path required for Scout job {self.job_id}")

        if not os.path.exists(file_path):
            await tracker.error(
                "Dataset not found", detail={"error": f"File not found: {file_path}"}
            )
            record_agent_error("Scout", self.job_id, "file_not_found")
            raise FileNotFoundError(f"Dataset not found: {file_path}")

        modality_override = self.job_data.get("modality_override")

        if progress_callback:
            progress_callback("Loading dataset...")

        await tracker.emit("acting", "Profiling dataset...", detail={"task": "EDA"})
        eda = run_eda(file_path, target_column)
        await emit_subaction_progress(self.redis._client, self.job_id, "Scout", "EDA complete", 0.3)
        if "error" in eda:
            await tracker.error(f"EDA failed: {eda['error']}")
            record_agent_error("Scout", self.job_id, "eda_failed")
            raise ValueError(f"EDA failed: {eda['error']}")

        if progress_callback:
            progress_callback("Reading columns...")

        await tracker.emit("thinking", "Analysing dataset characteristics...")

        # ── Engineering Reasoning (Stage 1) ──────────────────────────────
        df_sample = pd.read_csv(file_path, nrows=100)

        if progress_callback:
            progress_callback("Detecting modality...")
        modality = detect_modality(file_path, modality_override=modality_override)

        if progress_callback:
            progress_callback("Detecting task...")
        task_type = infer_task_type(target_column, eda.get("column_types", {}), file_path)

        if progress_callback:
            progress_callback("Detecting target...")

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

        if progress_callback:
            progress_callback("Profiling dataset...")

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Scout", "Engineering reasoning complete", 0.6
        )

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

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Scout", "Experience synthesis complete", 0.8
        )

        # Compute overall confidence as average of all decision confidences
        confs = [
            d["confidence"] for d in reasoning.values() if isinstance(d, dict) and "confidence" in d
        ]
        reasoning["overall_confidence"] = round(sum(confs) / len(confs), 2) if confs else 0.85

        _elapsed = _time.time() - _start
        SCOUT_DATASETS_PROCESSED.labels(job_id=self.job_id, status="success").inc()
        SCOUT_ANALYSIS_DURATION.labels(job_id=self.job_id).observe(_elapsed)

        await tracker.emit(
            "planning",
            "Selecting architecture and strategy...",
            detail={
                "confidence": reasoning.get("overall_confidence"),
                "architecture": reasoning.get("architecture", {}).get("selected"),
            },
        )

        if progress_callback:
            progress_callback("Selecting evaluation metric...")

        await tracker.emit(
            "acting",
            "Writing mission specification...",
            detail={"task_type": task_type, "modality": modality},
        )

        _threshold = self.job_data.get("deployment_threshold")
        _operator = self.job_data.get("deployment_operator", ">")
        brief = write_mission_brief(
            eda_results=eda,
            job_id=self.job_id,
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
            constraints=self.job_data.get("constraints"),
            modality_override=modality_override,
            engineering_reasoning=reasoning,
            deployment_threshold=_threshold,
            deployment_operator=_operator,
        )

        if progress_callback:
            progress_callback("Building mission brief...")

        mission_key = f"job:{self.job_id}:mission_brief"
        await self.redis.set_json(mission_key, brief)

        if progress_callback:
            progress_callback("Writing mission_brief.json...")

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
            deployment_threshold=_threshold,
            deployment_operator=_operator,
        )
        spec_key = f"job:{self.job_id}:mission_spec"
        await self.redis.set_json(spec_key, spec)

        await self.redis.set_str(f"job:{self.job_id}:file_path", file_path)
        await self.redis.set_str(f"job:{self.job_id}:problem_description", problem_description)

        if progress_callback:
            progress_callback("Publishing MISSION_BRIEF_READY...")

        from contracts.events import MissionBriefReadyEvent

        await publish(
            self.redis._client,
            STREAM_SCOUT_OUTPUT,
            MISSION_BRIEF_READY,
            MissionBriefReadyEvent(
                job_id=self.job_id,
                mission_brief_redis_key=mission_key,
                mission_spec_redis_key=spec_key,
            ),
        )

        await tracker.emit("verifying", "Validating mission specification...")

        # Emit structured detail events for the new UI
        await self._emit_structured_details(brief, spec, reasoning, eda)

        dataset_info = brief.get("dataset", {}) or {}
        data_quality = brief.get("data_quality", {}) or {}
        await tracker.done(
            "Mission spec ready",
            detail={
                "task_type": brief.get("task_type"),
                "modality": brief.get("modality"),
                "confidence": reasoning.get("overall_confidence"),
                "num_rows": dataset_info.get("num_rows"),
                "num_columns": dataset_info.get("num_columns"),
                "evaluation_metric": brief.get("evaluation_metric"),
                "class_imbalance": data_quality.get("class_imbalance_ratio"),
            },
        )

        if progress_callback:
            progress_callback("Complete.")

        log_mission_state(
            "SCOUT_COMPLETE",
            self.job_id,
            brief=brief,
            metric_name=brief.get("evaluation_metric"),
            deployment_threshold=brief.get("deployment_threshold"),
            architecture=brief.get("recommended_architecture_family"),
            imbalance_strategy=brief.get("imbalance_strategy"),
            task_type=brief.get("task_type"),
            confidence=reasoning.get("overall_confidence", "?"),
        )

        self.logger.info(
            f"[job={self.job_id}] MissionSpecification ready | "
            f"task={brief['task_type']} modality={brief['modality']} "
            f"confidence={reasoning.get('overall_confidence', '?')}"
        )

    async def _emit_structured_details(
        self,
        brief: dict[str, Any],
        spec: dict[str, Any],
        reasoning: dict[str, Any],
        eda: dict[str, Any],
    ) -> None:
        """Emit structured detail events for the new streaming UI."""
        tracker = AgentEventTracker(self.redis._client, self.job_id, "Scout")

        # Dataset detail
        ds = brief.get("dataset", {})
        dq = brief.get("data_quality", {})
        await tracker.emit(
            "acting",
            "Dataset profiled",
            detail=ScoutDatasetDetail(
                num_rows=ds.get("num_rows", 0),
                num_columns=ds.get("num_columns", 0),
                file_path=ds.get("file_path", ""),
                delimiter=ds.get("delimiter", ","),
                column_types=ds.get("column_types", {}),
                memory_mb=eda.get("memory_usage_bytes", 0) / (1024 * 1024),
            ).model_dump(),
        )

        # Data quality detail
        await tracker.emit(
            "acting",
            "Data quality analyzed",
            detail=ScoutDataQualityDetail(
                missing_values=dq.get("missing_value_rate", {}),
                high_cardinality=dq.get("high_cardinality_columns", []),
                class_imbalance_ratio=dq.get("class_imbalance_ratio"),
                outlier_counts=dq.get("outlier_counts", {}),
                duplicate_rows=dq.get("duplicate_rows", 0),
                warnings=dq.get("data_warnings", []),
            ).model_dump(),
        )

        # Task type detail
        task_dec = reasoning.get("problem_type", {})
        await tracker.emit(
            "acting",
            "Task type inferred",
            detail=ScoutTaskDetail(
                task_type=brief.get("task_type", "classification"),
                confidence=task_dec.get("confidence", 0.85),
                rationale=task_dec.get("rationale", ""),
                alternatives=task_dec.get("alternatives", []),
            ).model_dump(),
        )

        # Metric detail
        await tracker.emit(
            "acting",
            "Evaluation metric selected",
            detail=ScoutMetricDetail(
                metric=brief.get("evaluation_metric", "auc_roc"),
                reason=f"Selected for {brief.get('task_type')} with imbalance {dq.get('class_imbalance_ratio')}",
            ).model_dump(),
        )

        # Modality detail
        await tracker.emit(
            "acting",
            "Modality detected",
            detail=ScoutModalityDetail(
                modality=brief.get("modality", "tabular"),
                confidence=0.9,
            ).model_dump(),
        )

        # Architecture recommendation
        arch_dec = reasoning.get("architecture", {})
        await tracker.emit(
            "acting",
            "Architecture recommended",
            detail=ScoutRecommendationDetail(
                architecture=brief.get("recommended_architecture_family", "lightgbm"),
                confidence=arch_dec.get("confidence", 0.85),
                rationale=arch_dec.get("rationale", ""),
                alternatives=arch_dec.get("alternatives", []),
            ).model_dump(),
        )

        # Overall confidence
        await tracker.emit(
            "verifying",
            "Mission brief complete",
            detail=ScoutConfidenceDetail(
                overall=reasoning.get("overall_confidence", 0.85),
                per_decision={
                    k: v.get("confidence", 0)
                    for k, v in reasoning.items()
                    if isinstance(v, dict) and "confidence" in v
                },
            ).model_dump(),
        )

    async def run_with_data(
        self,
        problem_description: str,
        file_path: str,
        target_column: str | None = None,
        constraints: dict | None = None,
        modality_override: str | None = None,
        progress_callback: Any = None,
    ) -> dict[str, Any]:
        self.job_data = {
            "problem_description": problem_description,
            "file_path": file_path,
            "target_column": target_column,
            "constraints": constraints,
            "modality_override": modality_override,
        }
        await self.run(progress_callback=progress_callback)
        return await self.redis.get_json(f"job:{self.job_id}:mission_brief")

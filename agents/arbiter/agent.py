"""Arbiter Agent — The Critic. Evaluates trained models and decides pass/retry/escalate.

Uses constraint propagation: user-specified thresholds from the mission brief
are used directly instead of data-derived defaults. Always saves evaluation.json,
metrics.csv, decision.json, and evaluation plots (confusion matrix, ROC, PR curve).
Always evaluates on held-out test set (y_test.npy), never training data.
"""

import json
import os
from datetime import datetime, timezone

import numpy as np

from agents.arbiter.controller import build_constraints_from_brief
from agents.arbiter.decision import make_decision
from agents.arbiter.evaluator import load_checkpoint_data
from agents.arbiter.models import (
    DecisionResult,
    EvaluationResult,
    MissionConstraints,
)
from agents.arbiter.prompts import ARBITER_SYSTEM_PROMPT
from agents.arbiter.report import (
    save_decision_report,
    save_evaluation_plots,
    save_evaluation_report,
    save_metrics_csv,
)
from agents.arbiter.tools import compute_classification_metrics, compute_regression_metrics
from agents.base import BaseAgent
from bus.agent_events import emit_agent_event, emit_subaction_progress
from bus.events import (
    EVALUATION_PASS,
    EVALUATION_RETRY,
    ESCALATE,
    STREAM_ARBITER_OUTPUT,
)
from bus.publisher import publish
from memory.schemas import ExperienceRecord
from shared.metrics import ARBITER_DECISIONS, record_heartbeat
from prometheus.ui.detail_types import (
    ArbiterMetricsDetail,
    ArbiterDecisionDetail,
    ArbiterThresholdDetail,
    ArbiterLeaderboardDetail,
    ArbiterReportDetail,
)


class ArbiterAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Arbiter"

    @property
    def system_prompt(self) -> str:
        return ARBITER_SYSTEM_PROMPT

    async def run(self) -> None:
        raise NotImplementedError(
            "ArbiterAgent is event-triggered. Call on_training_complete(event) directly; "
            "it does not have a standalone run() loop."
        )

    async def on_training_complete(self, event: dict) -> None:
        self.job_id = event["job_id"]
        self.logger.info(f"[job={self.job_id}] Arbiter evaluating model")
        record_heartbeat("Arbiter", self.job_id)

        _arbiter_event_id = ""
        _arbiter_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "thinking",
            "Evaluating model...",
            detail={"checkpoint_path": event.get("checkpoint_path", "")},
        )

        checkpoint_path = event.get("checkpoint_path", "")
        task_type = await self._get_task_type()
        crash_count = int(event.get("total_crashes_recovered", 0) or 0)

        if not checkpoint_path or not os.path.exists(checkpoint_path):
            self.logger.error(f"[job={self.job_id}] Checkpoint not found: {checkpoint_path}")
            await self._publish_decision(
                ESCALATE, f"Checkpoint not found: {checkpoint_path}", 0.0, "auc_roc"
            )
            return

        # Step 1: Load constraints from mission brief (user-specified thresholds)
        brief = await self._get_mission_brief()
        constraints = build_constraints_from_brief(brief)

        # Step 2: Load held-out test set (y_test.npy — never training data)
        try:
            from runtime.paths import get_job_paths

            ckpt_dir = str(get_job_paths(self.job_id).checkpoints_dir)
            checkpoint_data = load_checkpoint_data(self.job_id, checkpoint_dir=ckpt_dir)
        except FileNotFoundError as e:
            self.logger.error(f"[job={self.job_id}] Test data not found: {e}")
            await self._publish_decision(ESCALATE, str(e), 0.0, "auc_roc")
            return

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Arbiter", "Loading checkpoint data...", 0.2
        )

        y_true = checkpoint_data["y_true"]
        y_pred = checkpoint_data["y_pred"]
        y_prob = checkpoint_data.get("y_prob")

        # Step 3: Compute metrics on held-out test set
        if task_type == "classification":
            metrics = compute_classification_metrics(y_true, y_pred, y_prob)
        else:
            metrics = compute_regression_metrics(y_true, y_pred)

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Arbiter", "Computing metrics...", 0.6
        )

        evaluation_result = EvaluationResult.from_metrics_dict(
            metrics=metrics,
            task_type=task_type,
            checkpoint_path=checkpoint_data.get("checkpoint_path", checkpoint_path),
            num_samples=checkpoint_data.get("num_samples", 0),
        )

        _arbiter_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "planning",
            f"Reasoning over metrics: {evaluation_result.metric}={evaluation_result.metric_value:.4f}",
            detail={
                "metric": evaluation_result.metric,
                "value": evaluation_result.metric_value,
                "threshold": constraints.threshold,
            },
            parent_event_id=_arbiter_event_id or None,
        )

        _arbiter_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "acting",
            "Deciding pass/retry/escalate...",
            detail={
                "threshold": constraints.threshold,
                "operator": constraints.operator,
                "crash_count": crash_count,
            },
            parent_event_id=_arbiter_event_id or None,
        )

        # Step 4: Make decision using user-specified constraints (not data-derived thresholds)
        decision = make_decision(evaluation_result, constraints)

        # Emit structured detail events
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "acting",
            "Evaluation complete",
            detail=ArbiterMetricsDetail(
                task_type=task_type,
                primary_metric=evaluation_result.metric,
                primary_value=evaluation_result.metric_value,
                all_metrics=evaluation_result.all_metrics or {},
                num_samples=evaluation_result.num_samples,
            ).model_dump(),
        )

        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "verifying",
            "Making decision",
            detail=ArbiterDecisionDetail(
                decision=decision.decision,
                explanation=decision.explanation,
                metric_value=evaluation_result.metric_value,
                threshold=constraints.threshold,
                operator=constraints.operator,
            ).model_dump(),
        )

        # Step 7: Publish decision event
        event_type_map = {
            "PASS": EVALUATION_PASS,
            "RETRY": EVALUATION_RETRY,
            "FAIL": ESCALATE,
        }
        event_type = event_type_map.get(decision.decision, ESCALATE)
        primary_name = evaluation_result.metric
        primary_val = evaluation_result.metric_value

        # Emit leaderboard
        all_metrics = evaluation_result.all_metrics or {}
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "verifying",
            "Leaderboard",
            detail=ArbiterLeaderboardDetail(
                candidates=[
                    {
                        "metric": k,
                        "value": v,
                        "status": "primary" if k == primary_name else "secondary",
                    }
                    for k, v in all_metrics.items()
                ],
            ).model_dump(),
        )

        await emit_subaction_progress(
            self.redis._client, self.job_id, "Arbiter", "Decision made", 1.0, "done"
        )

        # Map decision strings: PASS/RETRY/FAIL → pass/retry/escalate
        decision_str = decision.decision.lower()
        if decision_str == "fail":
            decision_str = "escalate"

        ARBITER_DECISIONS.labels(job_id=self.job_id, decision=decision_str).inc()
        self.logger.info(
            f"[job={self.job_id}] Decision: {decision.decision} | "
            f"{evaluation_result.metric}={evaluation_result.metric_value:.4f} | "
            f"threshold={constraints.threshold}"
        )

        # Step 5: Save evaluation artifacts — always
        from runtime.paths import get_job_paths

        jp = get_job_paths(self.job_id)
        output_dir = str(jp.job_dir)
        os.makedirs(output_dir, exist_ok=True)

        save_evaluation_report(
            self.job_id, evaluation_result, decision, constraints, output_dir=output_dir
        )
        save_metrics_csv(self.job_id, metrics, output_dir=output_dir)
        save_decision_report(self.job_id, decision, output_dir=output_dir)
        save_evaluation_plots(
            self.job_id,
            y_true=y_true,
            y_pred=y_pred,
            y_prob=y_prob,
            task_type=task_type,
        )

        # Step 6: Record experience outcome
        try:
            await self._record_experience(
                task_type,
                metrics,
                decision,
                evaluation_result,
                crash_count,
                event,
                constraints,
            )
        except Exception as exc:
            self.logger.warning(f"[job={self.job_id}] Failed to record experience: {exc}")

        all_metrics = evaluation_result.all_metrics or {}
        _arbiter_event_id = await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            "verifying",
            f"{decision.decision}: {evaluation_result.metric}={evaluation_result.metric_value:.4f}",
            detail={
                "decision": decision.decision,
                "metric": primary_name,
                "value": primary_val,
                "threshold": constraints.threshold,
                "num_samples": evaluation_result.num_samples,
                **{k: v for k, v in all_metrics.items() if k != primary_name},
            },
            parent_event_id=_arbiter_event_id or None,
        )

        state_label = {"PASS": "done", "RETRY": "done", "FAIL": "error"}.get(
            decision.decision, "done"
        )
        summary = {
            "PASS": "Evaluation passed",
            "RETRY": "Evaluation retry needed",
            "FAIL": "Evaluation failed",
        }.get(decision.decision, "Evaluation complete")
        await emit_agent_event(
            self.redis._client,
            self.job_id,
            "Arbiter",
            state_label,
            summary,
            detail={
                "decision": decision.decision,
                "metric": primary_name,
                "value": primary_val,
                "threshold": constraints.threshold,
                "num_samples": evaluation_result.num_samples,
                **{k: v for k, v in all_metrics.items() if k != primary_name},
            },
            parent_event_id=_arbiter_event_id or None,
        )

        await self._publish_decision(event_type, decision.explanation, primary_val, primary_name)

    async def _record_experience(
        self,
        task_type: str,
        metrics: dict[str, float],
        decision: DecisionResult,
        evaluation_result: EvaluationResult,
        crash_count: int,
        event: dict,
        constraints: MissionConstraints,
    ) -> None:
        from memory.collections.experience_memory import store_experience

        primary_val = evaluation_result.metric_value
        actual_minutes = (
            event.get("training_duration_seconds", 0) / 60.0
            if event.get("training_duration_seconds")
            else None
        )
        plan_data = await self._get_engineering_plan()

        patch_attempts = crash_count
        patch_categories = event.get("crash_categories", [])
        if not patch_categories and crash_count > 0:
            patch_categories = ["unknown"]
        patch_ok = crash_count == 0 or event.get("total_crashes_recovered", 0) == crash_count

        record = ExperienceRecord(
            job_id=self.job_id,
            modality=plan_data.get("modality", ""),
            task_type=task_type,
            num_rows=plan_data.get("num_rows", 0),
            num_columns=plan_data.get("num_columns", 0),
            architecture=plan_data.get("architecture", ""),
            class_imbalance_ratio=plan_data.get("class_imbalance_ratio"),
            expected_metric_range=plan_data.get("expected_metric_range"),
            achieved_metric=primary_val,
            expected_training_minutes=plan_data.get("expected_training_minutes"),
            actual_training_minutes=actual_minutes,
            total_crashes=crash_count,
            patch_success=patch_ok,
            outcome=decision.decision,
            dataset_fingerprint=plan_data.get("dataset_fingerprint", {}),
            engineering_decisions=plan_data.get("engineering_decisions", {}),
            pipeline_steps=plan_data.get("pipeline_step_names", []),
            feature_engineering=plan_data.get("feature_engineering_notes", []),
            patch_summary={
                "total_attempts": patch_attempts,
                "categories": patch_categories,
                "last_outcome": (
                    "success" if patch_ok else ("failed" if crash_count > 0 else "none")
                ),
            },
            mission_spec_key=plan_data.get("mission_spec_key", ""),
            engineering_plan_key=plan_data.get("engineering_plan_key", ""),
        )
        store_experience(record)
        self.logger.info(
            f"[job={self.job_id}] Experience recorded: outcome={decision.decision} "
            f"decisions={bool(record.engineering_decisions)} "
            f"fingerprint={bool(record.dataset_fingerprint)}"
        )

    async def _get_mission_brief(self) -> dict | None:
        try:
            raw = await self.redis.get_json(f"job:{self.job_id}:mission_brief")
            return raw if raw else None
        except Exception:
            return None

    async def _get_task_type(self) -> str:
        brief = await self._get_mission_brief()
        if brief:
            return brief.get("task_type", "classification")
        return "classification"

    async def _get_engineering_plan(self) -> dict:
        """Read engineering plan + mission brief + spec for rich experience recording."""
        plan: dict = {}
        try:
            plan = await self.redis.get_json(f"job:{self.job_id}:engineering_plan") or {}
        except Exception:
            pass
        try:
            brief = await self._get_mission_brief() or {}
            spec_raw = None
            try:
                spec_raw = await self.redis.get_json(f"job:{self.job_id}:mission_spec")
            except Exception:
                pass
            spec = spec_raw or {}
            arch_sel = plan.get("architecture_selected", {})
            plan["modality"] = brief.get("modality", "")
            plan["num_rows"] = brief.get("dataset", {}).get("num_rows", 0)
            plan["num_columns"] = brief.get("dataset", {}).get("num_columns", 0)
            plan["architecture"] = arch_sel.get("name", "")
            plan["expected_metric_range"] = arch_sel.get("expected_metric_range")
            plan["expected_training_minutes"] = arch_sel.get("expected_training_minutes")
            plan["class_imbalance_ratio"] = brief.get("data_quality", {}).get(
                "class_imbalance_ratio"
            )
            plan["imbalance_strategy"] = brief.get("imbalance_strategy", "none")
            plan["mission_spec_key"] = f"job:{self.job_id}:mission_spec"
            plan["engineering_plan_key"] = f"job:{self.job_id}:engineering_plan"

            dq = brief.get("data_quality", {})
            plan["dataset_fingerprint"] = {
                "class_imbalance_ratio": dq.get("class_imbalance_ratio"),
                "missing_value_rate": dq.get("missing_value_rate", {}),
                "high_cardinality_columns": dq.get("high_cardinality_columns", []),
                "data_warnings": dq.get("data_warnings", []),
                "column_types": brief.get("dataset", {}).get("column_types", {}),
                "missing_rate_summary": dq.get("missing_value_rate", {}),
            }

            eng_reasoning = spec.get("engineering_reasoning", {}) if spec else {}
            decisions = {}
            for key in ("preprocessing", "imbalance", "validation", "leakage", "architecture"):
                dec = eng_reasoning.get(key, {})
                if isinstance(dec, dict) and dec.get("selected"):
                    decisions[key] = dec["selected"]
            plan["engineering_decisions"] = decisions

            pipeline = plan.get("preprocessing_pipeline", [])
            plan["pipeline_step_names"] = [
                s.get("name", "") for s in pipeline if isinstance(s, dict)
            ]
            notes = plan.get("feature_engineering_notes", [])
            plan["feature_engineering_notes"] = notes if isinstance(notes, list) else []
        except Exception:
            pass
        return plan

    async def _publish_decision(
        self,
        event_type: str,
        reason: str,
        primary_val: float,
        primary_name: str,
    ) -> None:
        from runtime.paths import get_job_paths
        from contracts.events import (
            EvaluationPassEvent,
            EvaluationRetryEvent,
            EvaluationFailedEvent,
            EscalateEvent,
        )

        jp = get_job_paths(self.job_id)

        if event_type == ESCALATE:
            payload = EscalateEvent(
                job_id=self.job_id,
                source_agent="Arbiter",
                reason=reason,
                diagnostic_report_path=str(jp.diagnostic_report_path),
            )
        elif event_type == EVALUATION_PASS:
            payload = EvaluationPassEvent(
                job_id=self.job_id,
                eval_report_path=str(jp.eval_report_path),
                primary_metric=primary_name,
                primary_metric_value=primary_val,
            )
        elif event_type == EVALUATION_RETRY:
            payload = EvaluationRetryEvent(
                job_id=self.job_id,
                eval_report_path=str(jp.eval_report_path),
                primary_metric=primary_name,
                primary_metric_value=primary_val,
                reason=reason,
            )
        else:
            payload = EvaluationFailedEvent(
                job_id=self.job_id,
                eval_report_path=str(jp.eval_report_path),
                reason=reason,
            )

        await publish(self.redis._client, STREAM_ARBITER_OUTPUT, event_type, payload)

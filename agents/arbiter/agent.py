"""Arbiter Agent — The Critic. Evaluates trained models and decides pass/retry/escalate."""

import json
import os
from datetime import datetime, timezone

import numpy as np

from agents.base import BaseAgent
from agents.arbiter.prompts import ARBITER_SYSTEM_PROMPT
from agents.arbiter.tools import (
    compute_classification_metrics,
    compute_regression_metrics,
    generate_failure_analysis,
    make_decision,
)
from bus.events import (
    EVALUATION_PASS,
    EVALUATION_RETRY,
    ESCALATE,
    STREAM_ARBITER_OUTPUT,
)
from bus.publisher import publish
from memory.schemas import ExperienceRecord
from shared.metrics import ARBITER_DECISIONS, record_heartbeat


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

        checkpoint_path = event.get("checkpoint_path", "")
        task_type = await self._get_task_type()
        raw_crash = event.get("total_crashes_recovered", 0)
        crash_count = int(raw_crash) if raw_crash else 0

        if not checkpoint_path or not os.path.exists(checkpoint_path):
            self.logger.error(f"[job={self.job_id}] Checkpoint not found: {checkpoint_path}")
            await self._publish_decision(
                ESCALATE,
                f"Checkpoint not found: {checkpoint_path}",
                {},
            )
            return

        metrics = await self._compute_metrics(task_type)

        decision, reason = make_decision(task_type, metrics, crash_count)
        ARBITER_DECISIONS.labels(job_id=self.job_id, decision=decision).inc()
        analysis = generate_failure_analysis(metrics, decision, reason)

        self.logger.info(f"[job={self.job_id}] Decision: {decision} | reason={reason}")

        eval_report_path = f"outputs/{self.job_id}/eval_report_{self.job_id}.json"
        os.makedirs(os.path.dirname(eval_report_path), exist_ok=True)

        report = {
            "job_id": self.job_id,
            "decision": decision,
            "reason": reason,
            "metrics": metrics,
            "crash_count": crash_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "analysis": analysis,
        }

        with open(eval_report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        # ── Record experience outcome (Stage 3) ──────────────────────────
        try:
            from memory.collections.experience_memory import store_experience

            primary_name = metrics.get("primary_metric", "auc_roc")
            primary_val = (
                metrics.get(primary_name) or metrics.get("auc_roc") or metrics.get("rmse") or 0.0
            )
            actual_minutes = (
                event.get("training_duration_seconds", 0) / 60.0
                if event.get("training_duration_seconds")
                else None
            )

            plan_data = await self._get_engineering_plan()

            # Build patch summary from crash data
            patch_attempts = crash_count  # Each crash triggers a Dissect attempt
            patch_categories = []
            if event.get("crash_categories"):
                patch_categories = event.get("crash_categories", [])
            elif crash_count > 0:
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
                outcome=decision,
                # ── Stage 3 enrichments ──
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
                f"[job={self.job_id}] Experience recorded: outcome={decision} "
                f"decisions={bool(record.engineering_decisions)} "
                f"fingerprint={bool(record.dataset_fingerprint)}"
            )
        except Exception as exc:
            self.logger.warning(f"[job={self.job_id}] Failed to record experience: {exc}")

        event_type_map = {
            "pass": EVALUATION_PASS,
            "retry": EVALUATION_RETRY,
            "escalate": ESCALATE,
        }

        await self._publish_decision(
            event_type_map.get(decision, ESCALATE),
            reason,
            metrics,
        )

    async def _get_task_type(self) -> str:
        try:
            brief = await self.redis.get_json(f"job:{self.job_id}:mission_brief")
            if brief:
                return brief.get("task_type", "classification")
        except Exception:
            pass
        return "classification"

    async def _get_engineering_plan(self) -> dict:
        """Read engineering plan + mission brief + spec for rich experience recording."""
        plan: dict = {}
        try:
            plan = await self.redis.get_json(f"job:{self.job_id}:engineering_plan") or {}
        except Exception:
            pass
        try:
            brief = await self.redis.get_json(f"job:{self.job_id}:mission_brief") or {}
            spec = await self.redis.get_json(f"job:{self.job_id}:mission_spec") or {}
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

            # Dataset fingerprint from brief data quality
            dq = brief.get("data_quality", {})
            fingerprint = {
                "class_imbalance_ratio": dq.get("class_imbalance_ratio"),
                "missing_value_rate": dq.get("missing_value_rate", {}),
                "high_cardinality_columns": dq.get("high_cardinality_columns", []),
                "data_warnings": dq.get("data_warnings", []),
                "column_types": brief.get("dataset", {}).get("column_types", {}),
                "missing_rate_summary": dq.get("missing_value_rate", {}),
            }
            plan["dataset_fingerprint"] = fingerprint

            # Engineering decisions from spec's reasoning
            eng_reasoning = spec.get("engineering_reasoning", {}) if spec else {}
            decisions = {}
            for key in ("preprocessing", "imbalance", "validation", "leakage", "architecture"):
                dec = eng_reasoning.get(key, {})
                if isinstance(dec, dict) and dec.get("selected"):
                    decisions[key] = dec["selected"]
            plan["engineering_decisions"] = decisions

            # Pipeline steps from plan
            pipeline = plan.get("preprocessing_pipeline", [])
            plan["pipeline_step_names"] = [
                s.get("name", "") for s in pipeline if isinstance(s, dict)
            ]

            # Feature engineering notes
            notes = plan.get("feature_engineering_notes", [])
            plan["feature_engineering_notes"] = notes if isinstance(notes, list) else []
        except Exception:
            pass
        return plan

    async def _compute_metrics(self, task_type: str) -> dict[str, float]:
        ckpt_dir = f"outputs/{self.job_id}/checkpoints"
        y_true = np.load(os.path.join(ckpt_dir, "y_test.npy")).tolist()
        y_pred = np.load(os.path.join(ckpt_dir, "y_pred.npy")).tolist()
        if task_type == "classification":
            prob_path = os.path.join(ckpt_dir, "y_prob.npy")
            y_prob = np.load(prob_path).tolist() if os.path.exists(prob_path) else None
            return compute_classification_metrics(y_true, y_pred, y_prob)
        else:
            return compute_regression_metrics(y_true, y_pred)

    async def _publish_decision(
        self,
        event_type: str,
        reason: str,
        metrics: dict[str, float],
    ) -> None:
        primary = metrics.get("auc_roc") or metrics.get("rmse") or 0.0
        primary_name = "auc_roc" if "auc_roc" in metrics else "rmse"

        payload = {
            "job_id": self.job_id,
            "eval_report_path": f"outputs/{self.job_id}/eval_report_{self.job_id}.json",
            "primary_metric": primary_name,
            "primary_metric_value": primary,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if event_type == ESCALATE:
            payload["source_agent"] = "Arbiter"
            payload["diagnostic_report_path"] = (
                f"outputs/{self.job_id}/diagnostic_{self.job_id}.json"
            )

        await publish(self.redis._client, STREAM_ARBITER_OUTPUT, event_type, payload)

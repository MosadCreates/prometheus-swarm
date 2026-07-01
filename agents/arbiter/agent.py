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

        checkpoint_path = event.get("checkpoint_path", "")
        task_type = await self._get_task_type()
        crash_count = event.get("total_crashes_recovered", 0)

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

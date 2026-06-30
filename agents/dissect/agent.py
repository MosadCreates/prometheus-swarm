"""Dissect Agent ? The Debugger. Core scientific contribution: autonomous self-patching of ML training failures."""

import asyncio
import os
from datetime import datetime, timezone
from typing import Any
import uuid

from agents.base import BaseAgent
from agents.dissect.prompts import DISSECT_SYSTEM_PROMPT
from agents.dissect.taxonomy import classify_error, get_repair_strategy
from agents.dissect.tools import parse_stack_trace, apply_patch, rollback_patch, compute_diff, run_sandbox_test
from agents.dissect.patch_log import write_patch_log
from bus.events import RESUME_TRAINING, ESCALATE, CRASH_EVENT, STREAM_DISSECT_OUTPUT
from bus.publisher import publish


class DissectAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Dissect"

    @property
    def system_prompt(self) -> str:
        return DISSECT_SYSTEM_PROMPT

    async def handle_crash(self, crash_event: dict) -> None:
        self.job_id = crash_event["job_id"]
        self.logger.info(f"[job={self.job_id}] Dissect handling crash")

        script_path = crash_event["script_path"]
        exception_type = crash_event["exception_type"]
        exception_message = crash_event["exception_message"]
        traceback_str = crash_event.get("traceback", "")
        attempt_number = crash_event.get("crash_attempt_number", 1)

        category, confidence, match_method = classify_error(exception_type, exception_message)
        strategy = get_repair_strategy(category)

        self.logger.info(
            f"[job={self.job_id}] Error classified | category={category} "
            f"confidence={confidence} method={match_method}"
        )

        if not os.path.exists(script_path):
            await self._escalate(crash_event, f"Script not found: {script_path}")
            return

        with open(script_path) as f:
            original_code = f.read()

        patch_id = str(uuid.uuid4())
        llm_response = await self.call_llm(
            user_message=self._build_prompt(crash_event, category, strategy),
        )

        patched_code = llm_response["text"]

        # Clean markdown code fences if present
        patched_code = self._clean_code_fences(patched_code)

        if patched_code.strip().startswith("ESCALATE:"):
            reason = patched_code.replace("ESCALATE:", "").strip()
            await self._escalate(crash_event, reason)
            return

        success, msg = apply_patch(script_path, patched_code)
        if not success:
            await self._escalate(crash_event, f"Patch apply failed: {msg}")
            return

        diff = compute_diff(original_code, patched_code)
        lines_changed = len([l for l in diff.split("\n") if l.startswith("+") or l.startswith("-")])

        sandbox_passed, sandbox_output = await run_sandbox_test(script_path, self.job_id)

        entry = {
            "patch_id": patch_id,
            "job_id": self.job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exception_type": exception_type,
            "exception_message": exception_message,
            "error_taxonomy_category": category,
            "taxonomy_match_method": match_method,
            "repair_strategy_used": strategy,
            "retrieved_similar_patches": [],
            "diff_applied": diff,
            "lines_changed": lines_changed,
            "sandbox_test_result": "pass" if sandbox_passed else "fail",
            "patch_outcome": "success" if sandbox_passed else "rollback",
            "confidence_score": confidence,
            "attempt_number": attempt_number,
            "resume_from_checkpoint": f"outputs/{self.job_id}/checkpoints/best.ckpt",
        }

        await write_patch_log(self.redis, entry)

        if sandbox_passed:
            self.logger.info(f"[job={self.job_id}] Patch SUCCESS | patch_id={patch_id}")
            await publish(
                self.redis._client,
                STREAM_DISSECT_OUTPUT,
                RESUME_TRAINING,
                {
                    "job_id": self.job_id,
                    "patched_script_path": script_path,
                    "resume_from_checkpoint": f"outputs/{self.job_id}/checkpoints/best.ckpt",
                    "patch_id": patch_id,
                },
            )
        else:
            self.logger.warning(f"[job={self.job_id}] Patch FAILED attempt {attempt_number}")
            rollback_patch(script_path)

            if attempt_number >= 3:
                entry["patch_outcome"] = "escalated"
                await write_patch_log(self.redis, entry)
                await self._escalate(crash_event, "3 patch attempts failed")
            else:
                crash_event["crash_attempt_number"] = attempt_number + 1
                await asyncio.sleep(1)
                await self.handle_crash(crash_event)

    async def _escalate(self, crash_event: dict, reason: str) -> None:
        self.logger.error(f"[job={self.job_id}] ESCALATING: {reason}")
        await publish(
            self.redis._client,
            STREAM_DISSECT_OUTPUT,
            ESCALATE,
            {
                "job_id": self.job_id,
                "source_agent": "Dissect",
                "reason": reason,
                "diagnostic_report_path": f"outputs/{self.job_id}/diagnostic_{self.job_id}.json",
            },
        )

    def _build_prompt(self, crash_event: dict, category: str, strategy: str) -> str:
        return (
            f"The following training script crashed:\n\n"
            f"Script path: {crash_event['script_path']}\n"
            f"Exception: {crash_event['exception_type']}: {crash_event['exception_message']}\n"
            f"Error category: {category}\n"
            f"Suggested repair strategy: {strategy}\n\n"
            f"Read the script at {crash_event['script_path']}, "
            f"identify the bug, and output the complete fixed script."
        )

    @staticmethod
    def _clean_code_fences(text: str) -> str:
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            if line.strip().startswith("```"):
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

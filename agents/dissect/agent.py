"""Dissect Agent ? The Debugger. Core scientific contribution: autonomous self-patching of ML training failures."""

import asyncio
import os
from datetime import datetime, timezone
import uuid

from agents.base import BaseAgent
from agents.dissect.prompts import DISSECT_SYSTEM_PROMPT
from agents.dissect.taxonomy import classify_error, get_repair_strategy
from agents.dissect.tools import apply_patch, rollback_patch, compute_diff, run_sandbox_test
from agents.dissect.patch_log import write_patch_log
from bus.events import RESUME_TRAINING, ESCALATE, STREAM_DISSECT_OUTPUT
from bus.publisher import publish
from memory.collections.patch_memory import store_patch, query_similar_patches


class DissectAgent(BaseAgent):
    @property
    def agent_name(self) -> str:
        return "Dissect"

    @property
    def system_prompt(self) -> str:
        return DISSECT_SYSTEM_PROMPT

    async def run(self) -> None:
        raise NotImplementedError(
            "DissectAgent is event-triggered. Call handle_crash(crash_event) directly; "
            "it does not have a standalone run() loop."
        )

    async def handle_crash(self, crash_event: dict) -> None:
        self.job_id = crash_event["job_id"]
        self.logger.info(f"[job={self.job_id}] Dissect handling crash")

        script_path = crash_event["script_path"]
        exception_type = crash_event["exception_type"]
        exception_message = crash_event["exception_message"]
        attempt_number = int(crash_event.get("crash_attempt_number", 1))

        category, confidence, match_method = classify_error(exception_type, exception_message)
        strategy = get_repair_strategy(category)

        self.logger.info(
            f"[job={self.job_id}] Error classified | category={category} "
            f"confidence={confidence} method={match_method}"
        )

        # Query past similar patches from ChromaDB long-term memory (K=3)
        retrieved_similar = query_similar_patches(
            error_text=f"{exception_type}: {exception_message}",
            category=category,
            k=3,
        )
        if retrieved_similar:
            self.logger.info(
                f"[job={self.job_id}] Retrieved {len(retrieved_similar)} "
                f"similar past patches from ChromaDB"
            )
        else:
            self.logger.info(f"[job={self.job_id}] No similar past patches found in ChromaDB")

        if not os.path.exists(script_path):
            await self._escalate(crash_event, f"Script not found: {script_path}")
            return

        with open(script_path) as f:
            original_code = f.read()

        patch_id = str(uuid.uuid4())
        llm_response = await self.call_llm(
            user_message=self._build_prompt(crash_event, category, strategy, retrieved_similar),
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
        lines_changed = sum(
            1 for line in diff.split("\n") if line.startswith("+") or line.startswith("-")
        )

        sandbox_passed, sandbox_output = await run_sandbox_test(script_path, self.job_id)

        patch_outcome = "success" if sandbox_passed else "rollback"

        entry = {
            "patch_id": patch_id,
            "job_id": self.job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exception_type": exception_type,
            "exception_message": exception_message,
            "error_taxonomy_category": category,
            "taxonomy_match_method": match_method,
            "repair_strategy_used": strategy,
            "retrieved_similar_patches": retrieved_similar,
            "diff_applied": diff,
            "lines_changed": lines_changed,
            "sandbox_test_result": "pass" if sandbox_passed else "fail",
            "patch_outcome": patch_outcome,
            "confidence_score": confidence,
            "attempt_number": attempt_number,
            "resume_from_checkpoint": f"outputs/{self.job_id}/checkpoints/best.ckpt",
        }

        await write_patch_log(self.redis, entry)

        # Store in ChromaDB long-term memory (always — success or failure)
        try:
            store_patch(
                patch_id=patch_id,
                job_id=self.job_id,
                exception_type=exception_type,
                exception_message=exception_message,
                category=category,
                repair_strategy=strategy,
                diff_applied=diff,
                outcome=patch_outcome,
            )
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Failed to store patch in ChromaDB: {e}")

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
                # Store escalated outcome
                entry["patch_outcome"] = "escalated"
                await write_patch_log(self.redis, entry)
                try:
                    store_patch(
                        patch_id=patch_id,
                        job_id=self.job_id,
                        exception_type=exception_type,
                        exception_message=exception_message,
                        category=category,
                        repair_strategy=strategy,
                        diff_applied=diff,
                        outcome="escalated",
                    )
                except Exception as e:
                    self.logger.warning(f"[job={self.job_id}] Failed to store escalated patch: {e}")
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

    def _build_prompt(
        self,
        crash_event: dict,
        category: str,
        strategy: str,
        similar_patches: list[dict] | None = None,
    ) -> str:
        script_content = ""
        try:
            with open(crash_event["script_path"]) as f:
                script_content = f.read()
        except Exception:
            script_content = "[unable to read script]"

        similar_section = ""
        if similar_patches:
            lines = []
            lines.append("Similar past patches retrieved from memory:")
            for i, p in enumerate(similar_patches, 1):
                lines.append(
                    f"  {i}. category={p.get('category')}, "
                    f"strategy={p.get('repair_strategy')}, "
                    f"outcome={p.get('outcome')}, "
                    f"similarity={p.get('similarity_score', 0):.2f}"
                )
            similar_section = "\n".join(lines) + "\n\n"

        return (
            f"The following training script crashed:\n\n"
            f"Script path: {crash_event['script_path']}\n\n"
            f"--- BEGIN SCRIPT ---\n"
            f"{script_content}\n"
            f"--- END SCRIPT ---\n\n"
            f"Exception: {crash_event['exception_type']}: {crash_event['exception_message']}\n"
            f"Error category: {category}\n"
            f"Suggested repair strategy: {strategy}\n\n"
            f"{similar_section}"
            f"Fix the bug and output the COMPLETE fixed script. "
            f"Do NOT output a diff or patch — output the entire script."
        )

    @staticmethod
    def _clean_code_fences(text: str) -> str:
        lines = text.split("\n")
        in_block = False
        captured = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                captured.append(line)
        if captured:
            return "\n".join(captured)
        return text.strip()

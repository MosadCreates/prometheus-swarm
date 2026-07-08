"""Dissect Agent — The Debugger. Core scientific contribution: autonomous self-patching of ML training failures."""

import asyncio
import os
import time
from datetime import datetime, timezone
import uuid

from evaluation import config as eval_config
from agents.base import BaseAgent
from agents.dissect.prompts import DISSECT_SYSTEM_PROMPT
from agents.dissect.taxonomy import classify_error_async, get_repair_strategy
from agents.dissect.tools import (
    apply_patch,
    rollback_patch,
    compute_diff,
    run_sandbox_test,
)
from agents.dissect.patch_log import write_patch_log
from agents.dissect.budget import RepairBudget
from agents.dissect.routing import (
    run_cascade,
    on_llm_success,
    CASCADE_LEVEL_NAMES,
)
from agents.dissect.repair_cache import cache_lookup
from agents.dissect.knowledge_store import record_llm_interaction
from agents.forge.quality_feedback import record_repair
from bus.events import RESUME_TRAINING, ESCALATE, STREAM_DISSECT_OUTPUT
from bus.publisher import publish
from memory.collections.patch_memory import store_patch
from shared.metrics import (
    DISSECT_ERROR_CLASSIFICATIONS,
    DISSECT_PATCHES_GENERATED,
    DISSECT_OUTCOMES,
    DISSECT_CASCADE_LEVEL,
    DISSECT_LLM_BUDGET_EXHAUSTED,
    record_heartbeat,
    AGENT_LLM_CALLS,
    AGENT_LLM_TOKENS,
    AGENT_LLM_COST,
)


class DissectAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._classification_cache: dict[tuple[str, str], tuple[str, float, str]] = {}
        self._budget: RepairBudget | None = None
        self._dataset_path: str = ""

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
        record_heartbeat("Dissect", self.job_id)

        script_path = crash_event["script_path"]
        exception_type = crash_event["exception_type"]
        exception_message = crash_event["exception_message"]
        attempt_number = int(crash_event.get("crash_attempt_number", 1))

        if self._budget is None:
            self._budget = RepairBudget(job_id=self.job_id)
        self._budget.record_attempt()

        self._dataset_path = crash_event.get("dataset_path", crash_event.get("script_path", ""))

        cache_key = (exception_type, exception_message)
        if cache_key in self._classification_cache:
            category, confidence, match_method = self._classification_cache[cache_key]
            self.logger.info(
                f"[job={self.job_id}] Reusing cached classification | category={category} "
                f"method={match_method}"
            )
        else:
            script_snippet = None
            try:
                with open(script_path, encoding="utf-8") as f:
                    script_snippet = f.read()[:2000]
            except Exception:
                pass

            category, confidence, match_method = await classify_error_async(
                exception_type, exception_message, script_snippet=script_snippet
            )
            self._classification_cache[cache_key] = (category, confidence, match_method)

        strategy = get_repair_strategy(category)
        DISSECT_ERROR_CLASSIFICATIONS.labels(category=category, job_id=self.job_id).inc()

        self.logger.info(
            f"[job={self.job_id}] Error classified | category={category} "
            f"confidence={confidence} method={match_method}"
        )

        if not os.path.exists(script_path):
            await self._escalate(crash_event, f"Script not found: {script_path}")
            return

        with open(script_path, encoding="utf-8") as f:
            original_code = f.read()

        # === Cascade Routing: Level 0 -> Level 3 ===
        cascade_result = await run_cascade(
            category=category,
            script_content=original_code,
            exception_type=exception_type,
            exception_message=exception_message,
            dataset_path=self._dataset_path,
            redis_client=(
                self.redis._client
                if hasattr(self, "redis") and hasattr(self.redis, "_client")
                else None
            ),
            budget=self._budget,
        )

        if cascade_result.resolved and cascade_result.level < 4:
            # Levels 0-3: deterministic repair found
            DISSECT_CASCADE_LEVEL.labels(level=str(cascade_result.level), job_id=self.job_id).inc()
            patch_id = str(uuid.uuid4())
            diff = cascade_result.diff_applied or ""

            success, msg = apply_patch(script_path, cascade_result.patched_script)
            if not success:
                await self._escalate(crash_event, f"Patch apply failed: {msg}")
                return

            sandbox_passed, sandbox_output = await run_sandbox_test(script_path, self.job_id)
            lines_changed = sum(
                1 for line in diff.split("\n") if line.startswith("+") or line.startswith("-")
            )

            outcome = "success" if sandbox_passed else "rollback"
            entry = self._build_log_entry(
                patch_id=patch_id,
                crash_event=crash_event,
                category=category,
                match_method=match_method,
                strategy=strategy,
                cascade_level=cascade_result.level,
                diff=diff,
                lines_changed=lines_changed,
                sandbox_passed=sandbox_passed,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            await write_patch_log(self.redis, entry)
            self._store_in_memory(patch_id, entry, outcome)
            record_repair(
                self.job_id,
                category,
                "unknown",
                sandbox_passed,
                redis_client=(
                    self.redis._client
                    if hasattr(self, "redis") and hasattr(self.redis, "_client")
                    else None
                ),
                script_content=original_code,
            )

            if sandbox_passed:
                DISSECT_PATCHES_GENERATED.labels(category=category, job_id=self.job_id).inc()
                DISSECT_OUTCOMES.labels(outcome="resume", job_id=self.job_id).inc()
                self.logger.info(
                    f"[job={self.job_id}] Cascade SUCCESS | level={cascade_result.level} "
                    f"({CASCADE_LEVEL_NAMES.get(cascade_result.level, '?')}) "
                    f"patch_id={patch_id}"
                )
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
                return
            else:
                self.logger.warning(
                    f"[job={self.job_id}] Cascade patch FAILED sandbox | "
                    f"level={cascade_result.level} — falling back"
                )
                rollback_patch(script_path)

        # === Check budget before Level 4 LLM ===
        if not self._budget.can_call_llm():
            DISSECT_LLM_BUDGET_EXHAUSTED.labels(job_id=self.job_id).inc()
            self.logger.warning(
                f"[job={self.job_id}] LLM budget exhausted "
                f"(calls={self._budget.llm_calls_used}/{self._budget.max_llm_calls}, "
                f"cost=${self._budget.total_cost:.4f}) — escalating"
            )
            entry = self._build_log_entry(
                patch_id=str(uuid.uuid4()),
                crash_event=crash_event,
                category=category,
                match_method=match_method,
                strategy=strategy,
                cascade_level=4,
                diff="",
                lines_changed=0,
                sandbox_passed=False,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            entry["patch_outcome"] = "escalated"
            await write_patch_log(self.redis, entry)
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, "LLM budget exhausted")
            return

        # === Level 4: LLM Reasoning ===
        self.logger.info(f"[job={self.job_id}] Generating patch via LLM (attempt {attempt_number})")
        t0 = time.time()
        patch_id = str(uuid.uuid4())

        llm_response = await self.call_llm(
            user_message=self._build_prompt(crash_event, category, strategy, cascade_result),
        )

        llm_latency = (time.time() - t0) * 1000
        input_tokens = llm_response.get("input_tokens", 0)
        output_tokens = llm_response.get("output_tokens", 0)
        cost = self._estimate_cost(input_tokens, output_tokens)
        self._budget.record_llm_call(cost)

        AGENT_LLM_CALLS.labels(agent="Dissect", job_id=self.job_id).inc()
        AGENT_LLM_TOKENS.labels(agent="Dissect", job_id=self.job_id, direction="input").inc(
            input_tokens
        )
        AGENT_LLM_TOKENS.labels(agent="Dissect", job_id=self.job_id, direction="output").inc(
            output_tokens
        )
        AGENT_LLM_COST.labels(agent="Dissect", job_id=self.job_id).inc(cost)

        patched_code = llm_response["text"]
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

        entry = self._build_log_entry(
            patch_id=patch_id,
            crash_event=crash_event,
            category=category,
            match_method=match_method,
            strategy=strategy,
            cascade_level=4,
            diff=diff,
            lines_changed=lines_changed,
            sandbox_passed=sandbox_passed,
            confidence=confidence,
            attempt_number=attempt_number,
        )
        await write_patch_log(self.redis, entry)
        self._store_in_memory(patch_id, entry, patch_outcome)
        record_repair(self.job_id, category, "unknown", sandbox_passed)

        # === Record LLM interaction for knowledge compilation ===
        prompt_text = self._build_prompt(crash_event, category, strategy, cascade_result)
        await record_llm_interaction(
            redis_client=(
                self.redis._client
                if hasattr(self, "redis") and hasattr(self.redis, "_client")
                else None
            ),
            job_id=self.job_id,
            category=category,
            exception_type=exception_type,
            exception_message=exception_message,
            prompt=prompt_text,
            response=patched_code,
            patch_diff=diff,
            sandbox_result="pass" if sandbox_passed else "fail",
            patch_outcome=patch_outcome,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            repair_latency_ms=llm_latency,
            accepted=sandbox_passed,
        )

        DISSECT_PATCHES_GENERATED.labels(category=category, job_id=self.job_id).inc()

        if sandbox_passed:
            DISSECT_OUTCOMES.labels(outcome="resume", job_id=self.job_id).inc()
            self.logger.info(f"[job={self.job_id}] LLM patch SUCCESS | patch_id={patch_id}")

            # === Promote LLM success to template + cache ===
            if hasattr(self, "redis") and hasattr(self.redis, "_client"):
                await on_llm_success(
                    redis_client=self.redis._client,
                    job_id=self.job_id,
                    category=category,
                    exception_type=exception_type,
                    exception_message=exception_message,
                    dataset_path=self._dataset_path,
                    original_script=original_code,
                    patched_script=patched_code,
                    patch_diff=diff,
                    patch_id=patch_id,
                )

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
            self.logger.warning(f"[job={self.job_id}] LLM patch FAILED attempt {attempt_number}")
            rollback_patch(script_path)

            if attempt_number >= 3:
                entry["patch_outcome"] = "escalated"
                await write_patch_log(self.redis, entry)
                self._store_in_memory(patch_id, entry, "escalated")
                DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
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

    def _build_log_entry(
        self,
        *,
        patch_id: str,
        crash_event: dict,
        category: str,
        match_method: str,
        strategy: str,
        cascade_level: int = -1,
        diff: str,
        lines_changed: int,
        sandbox_passed: bool,
        confidence: float,
        attempt_number: int,
    ) -> dict:
        return {
            "patch_id": patch_id,
            "job_id": self.job_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exception_type": crash_event["exception_type"],
            "exception_message": crash_event["exception_message"],
            "error_taxonomy_category": category,
            "taxonomy_match_method": match_method,
            "repair_strategy_used": strategy,
            "cascade_level": cascade_level,
            "cascade_level_name": CASCADE_LEVEL_NAMES.get(cascade_level, "UNKNOWN"),
            "diff_applied": diff,
            "lines_changed": lines_changed,
            "sandbox_test_result": "pass" if sandbox_passed else "fail",
            "patch_outcome": "success" if sandbox_passed else "rollback",
            "confidence_score": confidence,
            "attempt_number": attempt_number,
            "resume_from_checkpoint": f"outputs/{self.job_id}/checkpoints/best.ckpt",
        }

    def _store_in_memory(self, patch_id: str, entry: dict, outcome: str) -> None:
        if eval_config.DISABLE_PATCH_MEMORY:
            return
        try:
            store_patch(
                patch_id=patch_id,
                job_id=self.job_id,
                exception_type=entry["exception_type"],
                exception_message=entry["exception_message"],
                category=entry["error_taxonomy_category"],
                repair_strategy=entry["repair_strategy_used"],
                diff_applied=entry["diff_applied"],
                outcome=outcome,
            )
        except Exception as e:
            self.logger.warning(f"[job={self.job_id}] Failed to store patch in ChromaDB: {e}")

    def _build_prompt(
        self,
        crash_event: dict,
        category: str,
        strategy: str,
        cascade_result=None,
    ) -> str:
        script_content = ""
        try:
            with open(crash_event["script_path"], encoding="utf-8") as f:
                script_content = f.read()
        except Exception:
            script_content = "[unable to read script]"

        return (
            f"The following training script crashed:\n\n"
            f"Script path: {crash_event['script_path']}\n\n"
            f"--- BEGIN SCRIPT ---\n"
            f"{script_content}\n"
            f"--- END SCRIPT ---\n\n"
            f"Exception: {crash_event['exception_type']}: {crash_event['exception_message']}\n"
            f"Error category: {category}\n"
            f"Suggested repair strategy: {strategy}\n\n"
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

    @staticmethod
    def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
        input_rate = 3.0 / 1_000_000
        output_rate = 15.0 / 1_000_000
        return (input_tokens * input_rate) + (output_tokens * output_rate)

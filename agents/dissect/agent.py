"""Dissect Agent — The Debugger. Core scientific contribution: autonomous self-patching of ML training failures."""

import asyncio
import os
import time
from datetime import datetime, timezone
import uuid

from evaluation import config as eval_config
from agents.base import BaseAgent
from agents.dissect.prompts import DISSECT_SYSTEM_PROMPT
from agents.dissect.taxonomy import (
    classify_error_async,
    get_repair_strategy,
    is_terminal,
    get_preferred_strategy,
)
from agents.dissect.tools import (
    apply_patch,
    rollback_patch,
    compute_diff,
    run_sandbox_test,
)
from agents.dissect.validation import validate_patch_pre, validate_patch_post
from agents.dissect.patch_log import write_patch_log
from agents.dissect.budget import RepairBudget
from agents.dissect.governor import BudgetGovernor
from agents.dissect.fingerprint import FingerprintStore, compute_fingerprint, compute_script_hash
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

ESCALATION_REASONS = {
    "terminal_error": "Terminal error category — no repair possible",
    "duplicate_fingerprint": "Same fingerprint already attempted — would loop",
    "no_progress_loop": "Script hash, error, and stage unchanged — no progress",
    "budget_exhausted": "Per-fingerprint LLM budget exhausted",
    "llm_failed": "LLM patch failed sandbox verification",
    "patch_had_no_effect": "Patch did not change the script",
    "script_not_found": "Script file not found at expected path",
    "patch_apply_failed": "Failed to apply patch to script file",
    "llm_disabled": "LLM calls disabled by configuration",
    "all_attempts_exhausted": "All repair attempts exhausted",
}


class DissectAgent(BaseAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._classification_cache: dict[tuple[str, str], tuple[str, float, str]] = {}
        self._budget: RepairBudget | None = None
        self._governor: BudgetGovernor | None = None
        self._fp_store: FingerprintStore | None = None
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

    def _ensure_governor(self, job_id: str, redis_client=None) -> None:
        if self._governor is None:
            self._governor = BudgetGovernor(job_id=job_id)
        if self._fp_store is None and redis_client is not None:
            self._fp_store = FingerprintStore(redis_client, job_id)

    def _get_redis_client(self):
        if hasattr(self, "redis") and hasattr(self.redis, "_client"):
            return self.redis._client
        return None

    async def handle_crash(self, crash_event: dict) -> None:
        self.job_id = crash_event["job_id"]
        self.logger.info(f"[job={self.job_id}] Dissect handling crash")
        record_heartbeat("Dissect", self.job_id)

        script_path = crash_event["script_path"]
        exception_type = crash_event["exception_type"]
        exception_message = crash_event["exception_message"]
        attempt_number = int(crash_event.get("crash_attempt_number", 1))
        redis_client = self._get_redis_client()

        if self._budget is None:
            self._budget = RepairBudget(job_id=self.job_id)
        self._budget.record_attempt()
        self._ensure_governor(self.job_id, redis_client)

        self._dataset_path = crash_event.get("dataset_path", crash_event.get("script_path", ""))

        # ── Classification ──────────────────────────────────────────────
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
            f"confidence={confidence} method={match_method} "
            f"preferred={get_preferred_strategy(category)}"
        )

        if not os.path.exists(script_path):
            await self._escalate(crash_event, "script_not_found")
            return

        with open(script_path, encoding="utf-8") as f:
            original_code = f.read()

        # ── Compute fingerprint ─────────────────────────────────────────
        pipeline_stage = crash_event.get("pipeline_stage", "training")
        fingerprint = compute_fingerprint(
            category, exception_message, original_code, pipeline_stage
        )
        script_hash = compute_script_hash(original_code)
        self.logger.info(
            f"[job={self.job_id}] Fingerprint={fingerprint[:16]}... category={category} stage={pipeline_stage}"
        )

        # ── Terminal error check ────────────────────────────────────────
        if is_terminal(category):
            self.logger.warning(
                f"[job={self.job_id}] Terminal category={category} — escalating, no repair"
            )
            entry = self._build_log_entry(
                patch_id=str(uuid.uuid4()),
                crash_event=crash_event,
                category=category,
                match_method=match_method,
                strategy=strategy,
                cascade_level=-1,
                diff="",
                lines_changed=0,
                sandbox_passed=False,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            entry["patch_outcome"] = "escalated"
            entry["escalation_reason"] = "terminal_error"
            await write_patch_log(self.redis, entry)
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, "terminal_error")
            return

        # ── Duplicate fingerprint check ────────────────────────────────
        if self._fp_store is not None:
            if not await self._fp_store.is_new(fingerprint):
                self.logger.warning(
                    f"[job={self.job_id}] Duplicate fingerprint={fingerprint[:16]}... "
                    f"category={category} — escalating, would loop"
                )
                entry = self._build_log_entry(
                    patch_id=str(uuid.uuid4()),
                    crash_event=crash_event,
                    category=category,
                    match_method=match_method,
                    strategy=strategy,
                    cascade_level=-1,
                    diff="",
                    lines_changed=0,
                    sandbox_passed=False,
                    confidence=confidence,
                    attempt_number=attempt_number,
                )
                entry["patch_outcome"] = "escalated"
                entry["escalation_reason"] = "duplicate_fingerprint"
                await write_patch_log(self.redis, entry)
                DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
                await self._escalate(crash_event, "duplicate_fingerprint")
                return

            # ── Progress check ─────────────────────────────────────────
            if not await self._fp_store.has_progress(script_hash, category, pipeline_stage):
                self.logger.warning(
                    f"[job={self.job_id}] No progress: script_hash={script_hash} "
                    f"category={category} stage={pipeline_stage} unchanged — escalating"
                )
                entry = self._build_log_entry(
                    patch_id=str(uuid.uuid4()),
                    crash_event=crash_event,
                    category=category,
                    match_method=match_method,
                    strategy=strategy,
                    cascade_level=-1,
                    diff="",
                    lines_changed=0,
                    sandbox_passed=False,
                    confidence=confidence,
                    attempt_number=attempt_number,
                )
                entry["patch_outcome"] = "escalated"
                entry["escalation_reason"] = "no_progress_loop"
                await write_patch_log(self.redis, entry)
                DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
                await self._escalate(crash_event, "no_progress_loop")
                return

            await self._fp_store.register(fingerprint, category, pipeline_stage, script_hash)

        # ── Budget check (per-fingerprint) ──────────────────────────────
        if self._governor is not None and not self._governor.can_call_llm(fingerprint):
            reason = self._governor.exhausted_reason(fingerprint)
            self.logger.warning(
                f"[job={self.job_id}] LLM budget exhausted for fingerprint={fingerprint[:16]}... "
                f"reason={reason} — escalating"
            )
            DISSECT_LLM_BUDGET_EXHAUSTED.labels(job_id=self.job_id).inc()
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
            entry["escalation_reason"] = reason
            await write_patch_log(self.redis, entry)
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, reason)
            return

        # ── Cascade Routing: direct from taxonomy ──────────────────────
        cascade_result = await run_cascade(
            category=category,
            script_content=original_code,
            exception_type=exception_type,
            exception_message=exception_message,
            dataset_path=self._dataset_path,
            redis_client=redis_client,
            budget=self._budget,
            job_id=self.job_id,
            governor=self._governor,
            fingerprint=fingerprint,
            fp_store=self._fp_store,
        )

        # ── Terminal from cascade ──────────────────────────────────────
        if cascade_result.is_terminal:
            entry = self._build_log_entry(
                patch_id=str(uuid.uuid4()),
                crash_event=crash_event,
                category=category,
                match_method=match_method,
                strategy=strategy,
                cascade_level=-1,
                diff="",
                lines_changed=0,
                sandbox_passed=False,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            entry["patch_outcome"] = "escalated"
            entry["escalation_reason"] = "terminal_error"
            await write_patch_log(self.redis, entry)
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, "terminal_error")
            return

        # ── Deterministic cascade success (levels 0-3) ────────────────
        if cascade_result.resolved and cascade_result.level < 4:
            DISSECT_CASCADE_LEVEL.labels(level=str(cascade_result.level), job_id=self.job_id).inc()
            patch_id = str(uuid.uuid4())
            diff = cascade_result.diff_applied or ""

            success, msg = apply_patch(script_path, cascade_result.patched_script)
            if not success:
                await self._escalate(crash_event, "patch_apply_failed")
                return

            # Pre-sandbox validation
            pre = validate_patch_pre(original_code, cascade_result.patched_script, diff)
            if not pre["valid"]:
                failed = [c for c in pre["checks"] if not c["passed"]]
                self.logger.warning(
                    f"[job={self.job_id}] Pre-sandbox validation failed: "
                    f"{[c['name'] for c in failed]}"
                )
                rollback_patch(script_path)
                await self._escalate(crash_event, f"pre_validation: {failed[0]['name']}")
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
            await record_repair(
                self.job_id,
                category,
                "unknown",
                sandbox_passed,
                redis_client=redis_client,
                script_content=original_code,
            )

            if sandbox_passed:
                post = validate_patch_post(self.job_id, sandbox_output)
                if not post["valid"]:
                    failed = [c for c in post["checks"] if not c["passed"]]
                    self.logger.warning(
                        f"[job={self.job_id}] Post-sandbox validation warnings: "
                        f"{[c['name'] for c in failed]} — accepting patch anyway"
                    )

                DISSECT_PATCHES_GENERATED.labels(category=category, job_id=self.job_id).inc()
                DISSECT_OUTCOMES.labels(outcome="resume", job_id=self.job_id).inc()
                if self._fp_store is not None:
                    await self._fp_store.record_state(script_hash, category, pipeline_stage)
                self.logger.info(
                    f"[job={self.job_id}] Cascade SUCCESS | level={cascade_result.level} "
                    f"({CASCADE_LEVEL_NAMES.get(cascade_result.level, '?')}) "
                    f"patch_id={patch_id}"
                )
                await publish(
                    redis_client,
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
                    f"level={cascade_result.level} — escalating"
                )
                rollback_patch(script_path)
                await self._escalate(crash_event, "llm_failed")
                return

        # ── Level 4: LLM Reasoning ─────────────────────────────────────
        self.logger.info(f"[job={self.job_id}] Generating patch via LLM (attempt {attempt_number})")

        # Final budget check before LLM call
        if self._governor is not None and not self._governor.can_call_llm(fingerprint):
            reason = self._governor.exhausted_reason(fingerprint)
            self.logger.warning(f"[job={self.job_id}] Budget exhausted before LLM: {reason}")
            DISSECT_LLM_BUDGET_EXHAUSTED.labels(job_id=self.job_id).inc()
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
            entry["escalation_reason"] = reason
            await write_patch_log(self.redis, entry)
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, reason)
            return

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
        if self._governor is not None:
            self._governor.record_llm_call(fingerprint, cost, input_tokens + output_tokens)

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
            await self._escalate_after_llm(
                crash_event,
                reason,
                entry_template=None,
                category=category,
                match_method=match_method,
                strategy=strategy,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            return

        # ── Apply LLM patch ────────────────────────────────────────────
        success, msg = apply_patch(script_path, patched_code)
        if not success:
            await self._escalate_after_llm(
                crash_event,
                "patch_apply_failed",
                entry_template=None,
                category=category,
                match_method=match_method,
                strategy=strategy,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            return

        diff = compute_diff(original_code, patched_code)

        # ── Progress check: did the patch actually change anything? ────
        new_script_hash = compute_script_hash(patched_code)
        if new_script_hash == script_hash:
            self.logger.warning(f"[job={self.job_id}] LLM patch had NO effect — script unchanged")
            rollback_patch(script_path)
            await self._escalate_after_llm(
                crash_event,
                "patch_had_no_effect",
                entry_template=None,
                category=category,
                match_method=match_method,
                strategy=strategy,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            return

        lines_changed = sum(
            1 for line in diff.split("\n") if line.startswith("+") or line.startswith("-")
        )

        # Pre-sandbox validation
        pre = validate_patch_pre(original_code, patched_code, diff)
        if not pre["valid"]:
            failed = [c for c in pre["checks"] if not c["passed"]]
            self.logger.warning(
                f"[job={self.job_id}] Pre-sandbox validation failed for LLM patch: "
                f"{[c['name'] for c in failed]}"
            )
            rollback_patch(script_path)
            await self._escalate_after_llm(
                crash_event,
                f"pre_validation: {failed[0]['name']}",
                entry_template=None,
                category=category,
                match_method=match_method,
                strategy=strategy,
                confidence=confidence,
                attempt_number=attempt_number,
            )
            return

        sandbox_passed, sandbox_output = await run_sandbox_test(script_path, self.job_id)
        patch_outcome = "success" if sandbox_passed else "rollback"

        if sandbox_passed:
            post = validate_patch_post(self.job_id, sandbox_output)
            if not post["valid"]:
                failed = [c for c in post["checks"] if not c["passed"]]
                self.logger.warning(
                    f"[job={self.job_id}] Post-sandbox validation warnings for LLM patch: "
                    f"{[c['name'] for c in failed]} — accepting patch anyway"
                )

        # ── Build and store log entry ──────────────────────────────────
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
        await record_repair(self.job_id, category, "unknown", sandbox_passed)

        # ── Record LLM interaction for knowledge compilation ──────────
        prompt_text = self._build_prompt(crash_event, category, strategy, cascade_result)
        await record_llm_interaction(
            redis_client=redis_client,
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

            if self._fp_store is not None:
                await self._fp_store.record_state(new_script_hash, category, pipeline_stage)

            # Promote to cache + template + rule
            if redis_client is not None:
                await on_llm_success(
                    redis_client=redis_client,
                    job_id=self.job_id,
                    category=category,
                    exception_type=exception_type,
                    exception_message=exception_message,
                    dataset_path=self._dataset_path,
                    original_script=original_code,
                    patched_script=patched_code,
                    patch_diff=diff,
                    patch_id=patch_id,
                    cascade_path=(
                        cascade_result.cascade_path
                        if hasattr(cascade_result, "cascade_path")
                        else None
                    ),
                )

            await publish(
                redis_client,
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

            entry["patch_outcome"] = "escalated"
            entry["escalation_reason"] = "llm_failed"
            await write_patch_log(self.redis, entry)
            self._store_in_memory(patch_id, entry, "escalated")
            DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
            await self._escalate(crash_event, "llm_failed")

    async def _escalate_after_llm(self, crash_event, reason, entry_template, **kw):
        """Escalate with a log entry recording why."""
        entry = self._build_log_entry(
            patch_id=str(uuid.uuid4()),
            crash_event=crash_event,
            category=kw.get("category", "unknown"),
            match_method=kw.get("match_method", "regex"),
            strategy=kw.get("strategy", "unknown"),
            cascade_level=4,
            diff="",
            lines_changed=0,
            sandbox_passed=False,
            confidence=kw.get("confidence", 0.5),
            attempt_number=kw.get("attempt_number", 1),
        )
        entry["patch_outcome"] = "escalated"
        entry["escalation_reason"] = reason
        await write_patch_log(self.redis, entry)
        DISSECT_OUTCOMES.labels(outcome="escalate", job_id=self.job_id).inc()
        await self._escalate(crash_event, reason)

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
            "llm_used_for_repair": cascade_level == 4,
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

        # ── Dataset context ──────────────────────────────────────────────
        dataset_columns = ""
        dataset_sample = ""
        delimiter_info = ""
        if self._dataset_path and os.path.exists(self._dataset_path):
            try:
                import pandas as pd
                from agents.scout.tools import _detect_delimiter

                delim = _detect_delimiter(self._dataset_path)
                delimiter_info = f"Detected delimiter: '{delim}'"
                df = pd.read_csv(self._dataset_path, sep=delim, nrows=5)
                dataset_columns = f"Dataset columns: {list(df.columns)}"
                dataset_sample = f"Dataset sample (first 3 rows):\n{df.head(3).to_string()}"
            except Exception as e:
                dataset_columns = f"[could not read dataset: {e}]"

        # ── Cascade path ─────────────────────────────────────────────────
        cascade_path_str = ""
        if (
            cascade_result
            and hasattr(cascade_result, "cascade_path")
            and cascade_result.cascade_path
        ):
            parts = []
            for step in cascade_result.cascade_path:
                lvl = step.get("level", "?")
                outcome = step.get("outcome", "?")
                msg = step.get("message", "")
                parts.append(f"  L{lvl}: {outcome} — {msg}")
            cascade_path_str = "Cascade path:\n" + "\n".join(parts)

        # ── Similar patches from memory ──────────────────────────────────
        similar_patches_str = ""
        try:
            from memory.collections.patch_memory import query_similar_patches

            patches = query_similar_patches(
                error_text=f"{crash_event['exception_type']}: {crash_event['exception_message']}",
                category=category,
                k=3,
            )
            if patches:
                lines = []
                for p in patches:
                    lines.append(
                        f"  patch_id={p['patch_id'][:8]} "
                        f"score={p['similarity_score']} "
                        f"outcome={p['outcome']} "
                        f"strategy={p.get('repair_strategy', '?')}"
                    )
                similar_patches_str = "Similar past patches:\n" + "\n".join(lines)
        except Exception:
            similar_patches_str = "[could not query patch memory]"

        parts = [
            "The following training script crashed:",
            f"Script path: {crash_event['script_path']}",
            "",
            f"Exception: {crash_event['exception_type']}: {crash_event['exception_message']}",
            f"Error category: {category}",
            f"Suggested repair strategy: {strategy}",
            "",
            "--- BEGIN SCRIPT ---",
            script_content,
            "--- END SCRIPT ---",
            "",
        ]

        if delimiter_info:
            parts.append(delimiter_info)
        if dataset_columns:
            parts.append(dataset_columns)
        if dataset_sample:
            parts.append(dataset_sample)
        if cascade_path_str:
            parts.append(cascade_path_str)
        if similar_patches_str:
            parts.append(similar_patches_str)

        parts.append(
            "Fix the bug and output the COMPLETE fixed script. "
            "Do NOT output a diff or patch — output the entire script."
        )
        return "\n\n".join(parts)

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

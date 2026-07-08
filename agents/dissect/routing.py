"""Intelligent Repair Routing — 5-level deterministic cascade (Phase 4).

The repair cascade flow:

  Level 0: Deterministic Repair Rules (rules.py)
    - Simple search/replace transforms
    - Zero LLM calls, zero DB queries
    - Categories: name_error, import_error, permission_error, zero_division, syntax_error, nan_propagation, etc.

  Level 1: Compiled Repair Templates (repair_templates.py)
    - Generalized repair patterns from past LLM successes
    - Pattern matching on exception message
    - Parameterized insertion/transform

  Level 2: Repair Cache (repair_cache.py)
    - Fingerprint-based exact match
    - Constant-time Redis GET
    - Returns verified diff from past identical failure

  Level 3: Patch Memory Retrieval (patch_memory.py)
    - ChromaDB semantic similarity search (K=3)
    - Retrieve similar patches from past jobs
    - Replay with sandbox verification

  Level 4: LLM Reasoning
    - Full LLM call with script context + error
    - If success → promote to template + cache
    - If failure after 3 attempts → escalate

  Level 5: Escalation
    - Publish ESCALATE
    - Diagnostic report written
    - Job marked FAILED

Routing decisions are deterministic — no LLM is used to decide whether to call another LLM.
"""

import logging
from typing import Any

from agents.dissect.rules import apply_rule
from agents.dissect.repair_templates import find_matching_templates
from agents.dissect.repair_cache import cache_lookup, cache_store
from agents.dissect.taxonomy import (
    get_cascade_level,
    is_deterministic,
    has_rule,
    has_template,
)
from agents.dissect.budget import RepairBudget
from shared.metrics import (
    DISSECT_PATCHES_GENERATED,
    DISSECT_OUTCOMES,
    DISSECT_CASCADE_HITS,
    DISSECT_CASCADE_MISSES,
    DISSECT_CASCADE_ERRORS,
)

logger = logging.getLogger(__name__)


CASCADE_LEVEL_NAMES = {
    0: "DETERMINISTIC_RULE",
    1: "COMPILED_TEMPLATE",
    2: "REPAIR_CACHE",
    3: "PATCH_MEMORY",
    4: "LLM_REASONING",
    5: "ESCALATION",
}


class RoutingResult:
    """Result of a single cascade level attempt."""

    def __init__(
        self,
        level: int,
        patched_script: str | None = None,
        diff_applied: str | None = None,
        success: bool = False,
        should_continue: bool = True,
        message: str = "",
        cascade_path: list[dict[str, Any]] | None = None,
    ):
        self.level = level
        self.level_name = CASCADE_LEVEL_NAMES.get(level, f"LEVEL_{level}")
        self.patched_script = patched_script
        self.diff_applied = diff_applied
        self.success = success
        self.should_continue = should_continue
        self.message = message
        self.cascade_path = cascade_path if cascade_path is not None else []

    @property
    def resolved(self) -> bool:
        return self.success and not self.should_continue


def compute_initial_level(category: str) -> int:
    """Determine the starting cascade level based on category metadata."""
    return get_cascade_level(category)


async def run_cascade_level_0(
    category: str,
    script_content: str,
    exception_message: str,
) -> RoutingResult:
    """Level 0: Deterministic Repair Rules."""
    patched = apply_rule(category, script_content, exception_message)
    if patched is not None and patched != script_content:
        from agents.dissect.tools import compute_diff

        diff = compute_diff(script_content, patched)
        logger.info(f"Level 0 rule matched | category={category}")
        return RoutingResult(
            level=0,
            patched_script=patched,
            diff_applied=diff,
            success=True,
            should_continue=False,
            message=f"Rule-based patch applied for {category}",
        )
    return RoutingResult(level=0, should_continue=True, message="No rule matched")


async def run_cascade_level_1(
    category: str,
    script_content: str,
    exception_type: str,
    exception_message: str,
) -> RoutingResult:
    """Level 1: Compiled Repair Templates."""
    templates = find_matching_templates(exception_type, exception_message, category=category)
    for template in templates:
        try:
            patched = template.apply(script_content, exception_message)
            if patched and patched != script_content:
                from agents.dissect.tools import compute_diff

                diff = compute_diff(script_content, patched)
                logger.info(
                    f"Level 1 template matched | template={template.template_id} "
                    f"category={category}"
                )
                return RoutingResult(
                    level=1,
                    patched_script=patched,
                    diff_applied=diff,
                    success=True,
                    should_continue=False,
                    message=f"Template {template.template_id} applied",
                )
        except Exception as e:
            logger.warning(f"Level 1 template {template.template_id} failed: {e}")
    return RoutingResult(level=1, should_continue=True, message="No template matched")


async def run_cascade_level_2(
    redis_client: Any,
    script_content: str,
    dataset_path: str,
    exception_type: str,
    exception_message: str,
) -> RoutingResult:
    """Level 2: Repair Cache (fingerprint lookup)."""
    cached = await cache_lookup(redis_client, dataset_path, exception_type, exception_message)
    if cached and cached.get("diff_applied"):
        from agents.dissect.tools import apply_unified_diff
        import tempfile
        import os

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8")
        tmp.write(script_content)
        tmp_path = tmp.name
        tmp.close()

        try:
            success, msg = apply_unified_diff(tmp_path, cached["diff_applied"])
            if success:
                with open(tmp_path, encoding="utf-8") as f:
                    patched = f.read()
                logger.info(
                    f"Level 2 cache HIT | category={cached.get('category')} "
                    f"fp={cached.get('fingerprint', '')[:12]}"
                )
                return RoutingResult(
                    level=2,
                    patched_script=patched,
                    diff_applied=cached["diff_applied"],
                    success=True,
                    should_continue=False,
                    message="Cached repair applied",
                )
        except Exception as e:
            logger.warning(f"Level 2 cache apply failed: {e}")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    return RoutingResult(level=2, should_continue=True, message="Cache miss")


async def run_cascade_level_3(
    script_content: str,
    exception_type: str,
    exception_message: str,
    category: str,
) -> RoutingResult:
    """Level 3: Patch Memory Retrieval (ChromaDB)."""
    from evaluation import config as eval_config

    if eval_config.DISABLE_PATCH_MEMORY:
        return RoutingResult(level=3, should_continue=True, message="Patch memory disabled")

    from memory.collections.patch_memory import query_similar_patches

    similar_patches = query_similar_patches(
        error_text=f"{exception_type}: {exception_message}",
        category=category,
        k=3,
    )

    for sp in similar_patches:
        if sp.get("outcome") == "success" and sp.get("similarity_score", 0) >= 0.90:
            diff_text = sp.get("diff_applied", "")
            if not diff_text:
                continue

            from agents.dissect.tools import apply_unified_diff, apply_patch
            import tempfile
            import os

            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            )
            tmp.write(script_content)
            tmp_path = tmp.name
            tmp.close()

            try:
                if diff_text.strip().startswith("---"):
                    success, msg = apply_unified_diff(tmp_path, diff_text)
                else:
                    success, msg = apply_patch(tmp_path, diff_text)

                if success:
                    with open(tmp_path, encoding="utf-8") as f:
                        patched = f.read()
                    logger.info(
                        f"Level 3 memory HIT | score={sp['similarity_score']:.2f} "
                        f"category={category}"
                    )
                    return RoutingResult(
                        level=3,
                        patched_script=patched,
                        diff_applied=diff_text,
                        success=True,
                        should_continue=False,
                        message=f"Memory patch replayed (score={sp['similarity_score']:.2f})",
                    )
            except Exception as e:
                logger.warning(f"Level 3 memory apply failed: {e}")
            finally:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    return RoutingResult(level=3, should_continue=True, message="No matching memory patch")


async def _run_level_safe(
    level: int,
    category: str,
    job_id: str,
    fn,
    *args,
    **kwargs,
) -> RoutingResult:
    """Run a cascade level with telemetry tracking and graceful error handling."""
    level_name = CASCADE_LEVEL_NAMES.get(level, f"LEVEL_{level}")
    try:
        result = await fn(*args, **kwargs)
        if result.resolved:
            logger.info(f"Level {level} ({level_name}) RESOLVED | {result.message}")
            DISSECT_CASCADE_HITS.labels(level=str(level), category=category, job_id=job_id).inc()
            return result
        else:
            logger.debug(f"Level {level} ({level_name}) MISS | {result.message}")
            DISSECT_CASCADE_MISSES.labels(
                level=str(level), reason=result.message[:64], job_id=job_id
            ).inc()
            return result
    except Exception as e:
        logger.warning(
            f"Level {level} ({level_name}) ERROR | {e} | "
            f"category={category} job={job_id}"
        )
        DISSECT_CASCADE_ERRORS.labels(level=str(level), job_id=job_id).inc()
        return RoutingResult(level=level, should_continue=True, message=f"Error: {e}")


async def run_cascade(
    category: str,
    script_content: str,
    exception_type: str,
    exception_message: str,
    dataset_path: str,
    redis_client: Any,
    budget: RepairBudget,
    job_id: str = "unknown",
) -> RoutingResult:
    """Run the 5-level repair cascade. Exits early on first success.

    Each level is wrapped in _run_level_safe so an unexpected error
    at any level does not block fallthrough to the next. Telemetry
    counters track hits, misses, and errors per level.
    """
    start_level = max(
        compute_initial_level(category),
        budget.get_cascade_level_bias(),
    )

    cascade_path: list[dict[str, Any]] = []

    logger.info(
        f"Starting repair cascade | category={category} job={job_id} "
        f"start_level={CASCADE_LEVEL_NAMES.get(start_level, str(start_level))} "
        f"budget_remaining={budget.budget_remaining_ratio():.2f}"
    )

    # Level 0: Deterministic Rules
    if start_level <= 0 and has_rule(category):
        result = await _run_level_safe(
            0, category, job_id, run_cascade_level_0,
            category, script_content, exception_message,
        )
        cascade_path.append({"level": 0, "outcome": "hit" if result.resolved else "miss", "message": result.message})
        if result.resolved:
            result.cascade_path = cascade_path
            return result
    elif start_level > 0:
        cascade_path.append({"level": 0, "outcome": "skipped", "reason": f"start_level={start_level}"})
    else:
        cascade_path.append({"level": 0, "outcome": "skipped", "reason": "no_rule"})

    # Level 1: Compiled Templates
    if start_level <= 1 and has_template(category):
        result = await _run_level_safe(
            1, category, job_id, run_cascade_level_1,
            category, script_content, exception_type, exception_message,
        )
        cascade_path.append({"level": 1, "outcome": "hit" if result.resolved else "miss", "message": result.message})
        if result.resolved:
            result.cascade_path = cascade_path
            return result
    elif start_level > 1:
        cascade_path.append({"level": 1, "outcome": "skipped", "reason": f"start_level={start_level}"})
    else:
        cascade_path.append({"level": 1, "outcome": "skipped", "reason": "no_template"})

    # Level 2: Repair Cache
    if start_level <= 2 and dataset_path:
        result = await _run_level_safe(
            2, category, job_id, run_cascade_level_2,
            redis_client, script_content, dataset_path, exception_type, exception_message,
        )
        cascade_path.append({"level": 2, "outcome": "hit" if result.resolved else "miss", "message": result.message})
        if result.resolved:
            result.cascade_path = cascade_path
            return result
    elif not dataset_path:
        cascade_path.append({"level": 2, "outcome": "skipped", "reason": "no_dataset_path"})
    else:
        cascade_path.append({"level": 2, "outcome": "skipped", "reason": f"start_level={start_level}"})

    # Level 3: Patch Memory
    if start_level <= 3:
        result = await _run_level_safe(
            3, category, job_id, run_cascade_level_3,
            script_content, exception_type, exception_message, category,
        )
        cascade_path.append({"level": 3, "outcome": "hit" if result.resolved else "miss", "message": result.message})
        if result.resolved:
            result.cascade_path = cascade_path
            return result
    else:
        cascade_path.append({"level": 3, "outcome": "skipped", "reason": f"start_level={start_level}"})

    # Level 4: LLM Reasoning (delegated to agent)
    cascade_path.append({"level": 4, "outcome": "required", "message": "deterministic levels exhausted"})
    logger.info(
        f"Cascade telemetry | job={job_id} category={category} "
        f"path={' -> '.join(f'L{e["outcome"][0].upper()}{e["level"]}' for e in cascade_path)}"
    )

    return RoutingResult(
        level=4,
        should_continue=True,
        message="All deterministic levels exhausted, LLM required",
        cascade_path=cascade_path,
    )


async def on_llm_success(
    redis_client: Any,
    job_id: str,
    category: str,
    exception_type: str,
    exception_message: str,
    dataset_path: str,
    original_script: str,
    patched_script: str,
    patch_diff: str,
    patch_id: str,
    cascade_path: list[dict[str, Any]] | None = None,
) -> None:
    """Post-LLM success: promote to template and store in cache.

    Records telemetry: cascade path, promotion outcomes, cache storage.
    """
    # Log full cascade path for telemetry
    if cascade_path:
        path_str = " -> ".join(
            f"L{e['level']}/{e['outcome'][:4]}" for e in cascade_path
        )
        logger.info(
            f"[job={job_id}] LLM resolved after cascade path: {path_str} "
            f"category={category}"
        )

    # Level 1: Promote to compiled template
    from agents.dissect.repair_templates import generalize_diff_to_template

    template = generalize_diff_to_template(
        category=category,
        original_script=original_script,
        patched_script=patched_script,
        exception_message=exception_message,
        source_patch_id=patch_id,
    )
    if template:
        logger.info(f"LLM repair promoted to template: {template.template_id}")

    # Level 2: Store in repair cache
    await cache_store(
        redis_client=redis_client,
        dataset_path=dataset_path,
        exception_type=exception_type,
        exception_message=exception_message,
        category=category,
        diff_applied=patch_diff,
        outcome="success",
    )

    # ── Gap 2: Push prevention rule to Forge ─────────────────────────────
    _push_forge_prevention_rule(
        redis_client,
        job_id,
        category,
        original_script,
        patch_diff,
        patch_id,
    )


def _extract_prevention_snippet(patch_diff: str, original_script: str) -> str:
    """Extract a Python code snippet from a patch diff for use as a prevention rule.

    Tries to find the added lines in the diff (lines starting with '+')
    and returns them as a clean code snippet. Falls back to returning the
    entire diff as a comment.
    """
    if not patch_diff:
        return ""

    added_lines = []
    for line in patch_diff.split("\n"):
        stripped = line.strip()
        if stripped.startswith("+") and not stripped.startswith("+++"):
            content = stripped[1:].strip()
            if content and not content.startswith("#") and not content.startswith("import "):
                added_lines.append(content)

    if added_lines:
        return "\n".join(added_lines)

    return f"# Prevention from diff:\n# {patch_diff[:500]}"


def _push_forge_prevention_rule(
    redis_client: Any,
    job_id: str,
    category: str,
    original_script: str,
    patch_diff: str,
    patch_id: str,
) -> None:
    """Push a prevention rule to Forge's Redis store.

    Called after a successful LLM repair. Records the repair as a
    prevention rule so Forge can pre-apply it to future scripts.
    """
    try:
        import asyncio

        from agents.forge.prevention import PreventionRule, push_prevention_rule

        architecture = "lightgbm"
        for arch_hint in ("lightgbm", "xgboost", "tabnet", "distilbert", "efficientnet"):
            if arch_hint in original_script[:2000].lower():
                architecture = arch_hint
                break

        snippet = _extract_prevention_snippet(patch_diff, original_script)
        if not snippet:
            logger.debug(f"No prevention snippet extracted for patch {patch_id[:8]}")
            return

        rule = PreventionRule(
            architecture=architecture,
            error_category=category,
            modification_type="insert_after_imports",
            code_snippet=snippet,
            summary=f"Auto-prevent {category} in {architecture} " f"(from {patch_id[:8]})",
            source_patch_id=patch_id,
            confidence=0.70,
            occurrences=1,
        )
        asyncio.create_task(push_prevention_rule(redis_client, rule))
        logger.info(
            f"[job={job_id}] Prevention rule pushed | arch={architecture} " f"category={category}"
        )
    except Exception as e:
        logger.warning(f"Failed to push prevention rule: {e}")

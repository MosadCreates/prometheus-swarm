"""Intelligent Repair Routing — direct routing with terminal bypass and progress detection.

Repair cascade flow:

  Terminal error → Escalate immediately (no repair attempted)

  Preferred strategy matches:
    rule     → Level 0 (deterministic rules)
    template → Level 1 (compiled templates)
    cache    → Level 2 (repair cache fingerprint match)
    memory   → Level 3 (patch memory semantic search)
    llm      → Level 4 (LLM reasoning)
    cascade  → Walk levels 0→4 in order (legacy fallback)

Each level is tried in order of the preferred strategy. If the first choice
fails, the system falls back through remaining levels. Progress detection
terminates the loop if state hasn't changed since the last attempt.
"""

import logging
from typing import Any

from agents.dissect.rules import apply_rule
from agents.dissect.repair_templates import find_matching_templates
from agents.dissect.repair_cache import cache_lookup, cache_store, cache_increment
from agents.dissect.taxonomy import (
    get_cascade_level,
    is_deterministic,
    has_rule,
    has_template,
    is_terminal,
    get_preferred_strategy,
)
from agents.dissect.budget import RepairBudget
from agents.dissect.governor import BudgetGovernor
from shared.metrics import (
    DISSECT_PATCHES_GENERATED,
    DISSECT_OUTCOMES,
    DISSECT_CASCADE_HITS,
    DISSECT_CASCADE_MISSES,
    DISSECT_CASCADE_ERRORS,
)

logger = logging.getLogger(__name__)

PREFERRED_STRATEGY_ORDER = {
    "rule": [0, 1, 2, 3, 4],
    "template": [1, 0, 2, 3, 4],
    "cache": [2, 0, 1, 3, 4],
    "memory": [3, 0, 1, 2, 4],
    "llm": [4, 0, 1, 2, 3],
    "cascade": [0, 1, 2, 3, 4],
    "terminal": [-1],
}

CASCADE_LEVEL_NAMES = {
    -1: "TERMINAL",
    0: "DETERMINISTIC_RULE",
    1: "COMPILED_TEMPLATE",
    2: "REPAIR_CACHE",
    3: "PATCH_MEMORY",
    4: "LLM_REASONING",
    5: "ESCALATION",
}


class RoutingResult:
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

    @property
    def is_terminal(self) -> bool:
        return self.level == -1


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
    redis_client: Any = None,
    job_id: str = "",
) -> RoutingResult:
    """Level 1: Compiled Repair Templates.

    On successful template match, increments usage_count and persists.
    When usage_count reaches 3, pushes a Forge prevention rule so the
    error is prevented at code-generation time.
    """
    templates = find_matching_templates(exception_type, exception_message, category=category)
    for template in templates:
        try:
            patched = template.apply(script_content, exception_message)
            if patched and patched != script_content:
                from agents.dissect.tools import compute_diff, compute_diff as _diff_fn

                diff = compute_diff(script_content, patched)

                # ── Track usage ─────────────────────────────────────────
                template.usage_count += 1
                from agents.dissect.repair_templates import save_templates

                save_templates()

                # ── Stage 3: Push prevention rule at 3+ uses ────────────
                if template.usage_count >= 3 and redis_client is not None:
                    _push_forge_prevention_rule(
                        redis_client,
                        job_id,
                        category,
                        script_content,
                        diff,
                        template.source_patch_id,
                    )

                logger.info(
                    f"Level 1 template matched | template={template.template_id} "
                    f"category={category} usage={template.usage_count}"
                )
                return RoutingResult(
                    level=1,
                    patched_script=patched,
                    diff_applied=diff,
                    success=True,
                    should_continue=False,
                    message=f"Template {template.template_id} applied (usage #{template.usage_count})",
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
    category: str = "",
    job_id: str = "",
) -> RoutingResult:
    """Level 2: Repair Cache (fingerprint lookup).

    On cache hit, increments replay_count. When replay_count reaches 2,
    promotes the cached repair to a compiled template. At 3, pushes a
    Forge prevention rule.
    """
    cached = await cache_lookup(redis_client, dataset_path, exception_type, exception_message)
    if cached and cached.get("diff_applied"):
        from agents.dissect.tools import apply_unified_diff, compute_diff
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

                # ── Track replay count ──────────────────────────────────
                replay_count = await cache_increment(
                    redis_client, dataset_path, exception_type, exception_message
                )

                logger.info(
                    f"Level 2 cache HIT | category={category or cached.get('category')} "
                    f"fp={cached.get('fingerprint', '')[:12]} "
                    f"replay_count={replay_count}"
                )

                # ── Stage 2: Promote to template on 2nd replay ──────────
                if replay_count >= 2:
                    from agents.dissect.repair_templates import generalize_diff_to_template

                    diff = compute_diff(script_content, patched)
                    template = generalize_diff_to_template(
                        category=category or cached.get("category", "unknown"),
                        original_script=script_content,
                        patched_script=patched,
                        exception_message=exception_message,
                        source_patch_id=cached.get("fingerprint", "cache"),
                    )
                    if template:
                        logger.info(
                            f"[job={job_id}] Cache replay #{replay_count} → "
                            f"promoted to template: {template.template_id}"
                        )

                # ── Stage 3: Push prevention rule on 3rd replay ────────
                if replay_count >= 3:
                    _push_forge_prevention_rule(
                        redis_client,
                        job_id,
                        category or cached.get("category", "unknown"),
                        script_content,
                        cached["diff_applied"],
                        cached.get("fingerprint", "cache"),
                    )

                return RoutingResult(
                    level=2,
                    patched_script=patched,
                    diff_applied=cached["diff_applied"],
                    success=True,
                    should_continue=False,
                    message=f"Cached repair applied (replay #{replay_count})",
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
            f"Level {level} ({level_name}) ERROR | {e} | " f"category={category} job={job_id}"
        )
        DISSECT_CASCADE_ERRORS.labels(level=str(level), job_id=job_id).inc()
        return RoutingResult(level=level, should_continue=True, message=f"Error: {e}")


async def _run_level_dispatch(
    level: int,
    category: str,
    script_content: str,
    exception_type: str,
    exception_message: str,
    dataset_path: str,
    redis_client: Any,
    job_id: str,
) -> RoutingResult:
    """Dispatch a single cascade level by number."""
    if level == 0:
        return await run_cascade_level_0(category, script_content, exception_message)
    elif level == 1:
        return await run_cascade_level_1(
            category, script_content, exception_type, exception_message, redis_client, job_id
        )
    elif level == 2:
        if not dataset_path:
            return RoutingResult(level=2, should_continue=True, message="No dataset path")
        return await run_cascade_level_2(
            redis_client,
            script_content,
            dataset_path,
            exception_type,
            exception_message,
            category,
            job_id,
        )
    elif level == 3:
        return await run_cascade_level_3(
            script_content, exception_type, exception_message, category
        )
    elif level == 4:
        return RoutingResult(level=4, should_continue=True, message="LLM required")
    return RoutingResult(level=level, should_continue=True, message="Unknown level")


async def run_cascade(
    category: str,
    script_content: str,
    exception_type: str,
    exception_message: str,
    dataset_path: str,
    redis_client: Any,
    budget: RepairBudget,
    job_id: str = "unknown",
    governor: BudgetGovernor | None = None,
    fingerprint: str | None = None,
    fp_store=None,
) -> RoutingResult:
    """Run the repair cascade using direct routing from taxonomy.

    Terminal errors are caught before any level is attempted.
    Preferred strategy from taxonomy determines the order levels are tried.
    """
    # ── Terminal bypass ──────────────────────────────────────────────────
    if is_terminal(category):
        logger.info(f"Terminal error category={category} — escalating immediately")
        return RoutingResult(
            level=-1,
            should_continue=False,
            success=False,
            message=f"Terminal error: {category} cannot be repaired",
            cascade_path=[{"level": -1, "outcome": "terminal", "category": category}],
        )

    # ── Determine level order from preferred strategy ──────────────────
    preferred = get_preferred_strategy(category)
    level_order = PREFERRED_STRATEGY_ORDER.get(preferred, [0, 1, 2, 3, 4])

    cascade_path: list[dict[str, Any]] = []
    start_level = max(
        get_cascade_level(category),
        budget.get_cascade_level_bias(),
    )

    logger.info(
        f"Starting repair cascade | category={category} job={job_id} "
        f"preferred={preferred} start_level={start_level} "
        f"order={level_order} budget_remaining={budget.budget_remaining_ratio():.2f}"
    )

    # ── Try levels in preferred order ────────────────────────────────
    for target_level in level_order:
        # Skip levels below the start floor
        if target_level >= 0 and target_level < start_level:
            cascade_path.append(
                {
                    "level": target_level,
                    "outcome": "skipped",
                    "reason": f"start_level_floor={start_level}",
                }
            )
            continue

        if target_level == 4:
            # LLM is delegated to agent — exit cascade with level=4 signal
            cascade_path.append(
                {"level": 4, "outcome": "required", "message": "deterministic levels exhausted"}
            )
            path_str = " -> ".join(f'L{e["outcome"][0].upper()}{e["level"]}' for e in cascade_path)
            logger.info(f"Cascade telemetry | job={job_id} category={category} path={path_str}")
            return RoutingResult(
                level=4,
                should_continue=True,
                message="Deterministic levels exhausted, LLM required",
                cascade_path=cascade_path,
            )

        result = await _run_level_safe(
            target_level,
            category,
            job_id,
            _run_level_dispatch,
            target_level,
            category,
            script_content,
            exception_type,
            exception_message,
            dataset_path,
            redis_client,
            job_id,
        )
        cascade_path.append(
            {
                "level": target_level,
                "outcome": "hit" if result.resolved else "miss",
                "message": result.message,
            }
        )
        if result.resolved:
            result.cascade_path = cascade_path
            return result

    # All levels exhausted
    cascade_path.append({"level": 4, "outcome": "required", "message": "all levels exhausted"})
    path_str = " -> ".join(f'L{e["outcome"][0].upper()}{e["level"]}' for e in cascade_path)
    logger.info(f"Cascade telemetry | job={job_id} category={category} path={path_str}")
    return RoutingResult(
        level=4,
        should_continue=True,
        message="All repair levels exhausted, LLM required",
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
    """Post-LLM success: store repair in cache for future replay.

    Template promotion and rule promotion happen at cascade hit time
    (level 2 cache replay), not here. This function only persists the
    initial repair so that future identical failures can skip the LLM.
    """
    if cascade_path:
        path_str = " -> ".join(f"L{e['level']}/{e['outcome'][:4]}" for e in cascade_path)
        logger.info(
            f"[job={job_id}] LLM resolved after cascade path: {path_str} " f"category={category}"
        )

    await cache_store(
        redis_client=redis_client,
        dataset_path=dataset_path,
        exception_type=exception_type,
        exception_message=exception_message,
        category=category,
        diff_applied=patch_diff,
        outcome="success",
    )


def _extract_prevention_snippet(patch_diff: str, original_script: str) -> str:
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
            summary=f"Auto-prevent {category} in {architecture} (from {patch_id[:8]})",
            source_patch_id=patch_id,
            confidence=0.70,
            occurrences=1,
        )
        asyncio.create_task(push_prevention_rule(redis_client, rule))
        logger.info(
            f"[job={job_id}] Prevention rule pushed | arch={architecture} category={category}"
        )
    except Exception as e:
        logger.warning(f"Failed to push prevention rule: {e}")

"""Forge Prevention Rules — Dissect repairs flow back to prevent future errors.

When Dissect's LLM successfully patches a training script, the patch is recorded
as a prevention rule. When Forge generates a future script for the same architecture,
it pre-applies the prevention rule so the error never occurs.

Flow:
    Dissect LLM success
        → on_llm_success()
            → promote to template (Level 1)
            → store in cache (Level 2)
            → push prevention rule to Redis (NEW)
        → Forge reads prevention rules before script generation
        → Forge applies rules to rendered script
        → Error prevented before training starts

Redis key: forge:prevention_rules:{architecture}
Type: List of JSON-encoded PreventionRule dicts
"""

import json
import logging
import os
import re
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

REDIS_PREFIX = "forge:prevention_rules"

PREVENTION_TYPES = {
    "insert_after_imports": "Insert code after the last import statement",
    "insert_before_checkpoint": "Insert code before checkpoint saving",
    "insert_after_data_loading": "Insert code after data loading and target extraction",
    "wrap_fit_call": "Wrap the model.fit() call with additional logic",
}


class PreventionRule:
    """A rule that Forge applies to prevent a known error pattern.

    Each rule originates from a successful Dissect LLM repair. The rule captures
    what architecture it applies to, what error it prevents, and what code to
    inject into generated scripts.
    """

    def __init__(
        self,
        architecture: str,
        error_category: str,
        modification_type: str,
        code_snippet: str,
        summary: str = "",
        source_patch_id: str = "",
        rule_id: str | None = None,
        confidence: float = 0.8,
        occurrences: int = 1,
        active: bool = True,
    ):
        self.rule_id = rule_id or str(uuid.uuid4())
        self.architecture = architecture
        self.error_category = error_category
        self.modification_type = modification_type
        self.code_snippet = code_snippet
        self.summary = summary or f"Prevent {error_category} for {architecture}"
        self.source_patch_id = source_patch_id
        self.confidence = min(max(confidence, 0.0), 1.0)
        self.occurrences = max(occurrences, 1)
        self.active = active
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "architecture": self.architecture,
            "error_category": self.error_category,
            "modification_type": self.modification_type,
            "code_snippet": self.code_snippet,
            "summary": self.summary,
            "source_patch_id": self.source_patch_id,
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "active": self.active,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PreventionRule":
        rule = cls(
            architecture=data["architecture"],
            error_category=data["error_category"],
            modification_type=data["modification_type"],
            code_snippet=data["code_snippet"],
            summary=data.get("summary", ""),
            source_patch_id=data.get("source_patch_id", ""),
            rule_id=data.get("rule_id"),
            confidence=data.get("confidence", 0.8),
            occurrences=data.get("occurrences", 1),
            active=data.get("active", True),
        )
        rule.created_at = data.get("created_at", rule.created_at)
        return rule


def _redis_key(architecture: str) -> str:
    return f"{REDIS_PREFIX}:{architecture}"


async def push_prevention_rule(
    redis_client: Any,
    rule: PreventionRule,
    ttl_seconds: int = 86400 * 90,
) -> bool:
    """Store a prevention rule in Redis for Forge to consume.

    Args:
        redis_client: Redis client with rpush/set_str methods.
        rule: The PreventionRule to store.
        ttl_seconds: TTL for the Redis list (default 90 days).

    Returns:
        True if stored successfully.
    """
    key = _redis_key(rule.architecture)
    try:
        await redis_client.rpush(key, json.dumps(rule.to_dict()))
        await redis_client.expire(key, ttl_seconds)
        logger.info(
            f"Prevention rule stored | arch={rule.architecture} "
            f"category={rule.error_category} rule_id={rule.rule_id[:8]}"
        )
        return True
    except Exception as e:
        logger.warning(f"Failed to store prevention rule: {e}")
        return False


async def load_prevention_rules(
    redis_client: Any,
    architecture: str,
    min_confidence: float = 0.0,
) -> list[PreventionRule]:
    """Load all active prevention rules for a given architecture.

    Args:
        redis_client: Redis client.
        architecture: Architecture to filter by.
        min_confidence: Minimum confidence threshold.

    Returns:
        List of active PreventionRules for this architecture.
    """
    key = _redis_key(architecture)
    try:
        raw_list = await redis_client.lrange(key, 0, -1)
    except Exception as e:
        logger.warning(f"Failed to load prevention rules: {e}")
        return []

    rules: list[PreventionRule] = []
    for raw in raw_list:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            rule = PreventionRule.from_dict(data)
            if rule.active and rule.confidence >= min_confidence:
                rules.append(rule)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Skipping malformed prevention rule: {e}")

    logger.info(f"Loaded {len(rules)} prevention rules for architecture={architecture}")
    return rules


async def increment_occurrence(
    redis_client: Any,
    architecture: str,
    rule_id: str,
) -> bool:
    """Increment the occurrence count for a prevention rule.

    Called when a prevention rule successfully prevents an error
    (i.e., the script trains without crashing on the expected error).
    """
    key = _redis_key(architecture)
    try:
        raw_list = await redis_client.lrange(key, 0, -1)
        for i, raw in enumerate(raw_list):
            data = json.loads(raw) if isinstance(raw, str) else raw
            if data.get("rule_id") == rule_id:
                data["occurrences"] = data.get("occurrences", 1) + 1
                await redis_client.lset(key, i, json.dumps(data))
                return True
    except Exception as e:
        logger.warning(f"Failed to increment occurrence count: {e}")
    return False


def apply_prevention_rule(script: str, rule: PreventionRule) -> str:
    """Apply a single prevention rule to a rendered training script.

    Returns the modified script, or the original if the rule couldn't be applied.

    Supported modification types:
        insert_after_imports: Insert code after the last import statement.
        insert_before_checkpoint: Insert code before the checkpoint saving block.
        insert_after_data_loading: Insert code after target.pop() / data loading.
        wrap_fit_call: Wrap model.fit() with a try/except or logging block.
    """
    if not rule.active or not rule.code_snippet:
        return script

    mt = rule.modification_type

    if mt == "insert_after_imports":
        return _insert_after_imports(script, rule.code_snippet)

    if mt == "insert_before_checkpoint":
        return _insert_before_checkpoint(script, rule.code_snippet)

    if mt == "insert_after_data_loading":
        return _insert_after_data_loading(script, rule.code_snippet)

    if mt == "wrap_fit_call":
        return _wrap_fit_call(script, rule.code_snippet)

    logger.warning(f"Unknown prevention type '{mt}' — skipping rule {rule.rule_id[:8]}")
    return script


def apply_all_prevention_rules(script: str, rules: list[PreventionRule]) -> str:
    """Apply multiple prevention rules in sequence.

    Rules are applied in order. If a rule fails to apply cleanly
    (no change detected), it's skipped gracefully.
    """
    for rule in rules:
        before = len(script)
        script = apply_prevention_rule(script, rule)
        if len(script) != before:
            logger.info(
                f"Prevention rule applied | arch={rule.architecture} "
                f"category={rule.error_category} rule_id={rule.rule_id[:8]}"
            )
        else:
            logger.debug(
                f"Prevention rule skipped (no change) | "
                f"rule_id={rule.rule_id[:8]} type={rule.modification_type}"
            )
    return script


def _insert_after_imports(script: str, code: str) -> str:
    """Find the last import line and insert code after it."""
    lines = script.split("\n")
    last_import_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            last_import_idx = i

    if last_import_idx < 0:
        return script

    indent = ""

    code_lines = code.rstrip().split("\n")

    result = lines[: last_import_idx + 1] + [""] + code_lines + lines[last_import_idx + 1 :]
    return "\n".join(result)


def _insert_before_checkpoint(script: str, code: str) -> str:
    """Insert code before the checkpoint saving section.

    Looks for patterns like checkpoint_path = ... or output_dir = ...
    and inserts code before the first such match.
    """
    anchors = [
        "checkpoint_path =",
        "checkpoint_path=",
        'checkpoint_path = os.path.join(OUTPUT_DIR, "best.ckpt")',
    ]
    lines = script.split("\n")
    target_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        for anchor in anchors:
            if anchor in stripped:
                target_idx = i
                break
        if target_idx >= 0:
            break

    if target_idx < 0:
        return script

    code_lines = code.rstrip().split("\n")
    result = lines[:target_idx] + code_lines + [""] + lines[target_idx:]
    return "\n".join(result)


def _insert_after_data_loading(script: str, code: str) -> str:
    """Insert code after the data loading and target extraction section.

    Targets the line after target = df.pop(...) or target = df[...].
    """
    patterns = [
        r"^\s*(target|y)\s*=\s*df\.pop\(.*\)",
        r"^\s*(target|y)\s*=\s*df\[.*\]",
        r"^\s*target\s*=\s*df\.pop\(.*",
    ]
    lines = script.split("\n")
    target_idx = -1
    for i, line in enumerate(lines):
        stripped = line.strip()
        for pat in patterns:
            if re.match(pat, stripped):
                target_idx = i
                break
        if target_idx >= 0:
            break

    if target_idx < 0:
        return script

    code_lines = code.rstrip().split("\n")
    result = lines[: target_idx + 1] + code_lines + lines[target_idx + 1 :]
    return "\n".join(result)


def _wrap_fit_call(script: str, code: str) -> str:
    """Wrap model.fit() calls with additional code.

    The code_snippet should be Python code that wraps the fit call.
    The word 'MODEL_FIT' in the snippet is replaced with the actual fit line.
    """
    lines = script.split("\n")
    fit_indices = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\s*(model|_model)\s*\.fit\s*\(", stripped):
            fit_indices.append(i)

    if not fit_indices:
        return script

    for idx in reversed(fit_indices):
        fit_line = lines[idx]
        indent = " " * (len(lines[idx]) - len(lines[idx].lstrip()))
        wrapped = code.replace("MODEL_FIT", fit_line.strip())
        wrapped_lines = [f"{indent}{wl}" for wl in wrapped.split("\n")]
        lines = lines[:idx] + wrapped_lines + lines[idx + 1 :]

    return "\n".join(lines)

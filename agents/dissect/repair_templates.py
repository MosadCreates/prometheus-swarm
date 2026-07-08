"""Repair Template Promotion — compiled, generalized repair patterns (Phase 3).

When the LLM successfully repairs a novel error, the repair pattern is:
  1. Generalized (column names, file paths replaced with placeholders)
  2. Compiled into a RepairTemplate
  3. Stored in the template registry
  4. Future identical structural failures are fixed with zero LLM calls

Each template has:
  - category: which error category it addresses
  - pattern_matcher: regex on exception message to detect applicability
  - apply: parameterized function that applies the fix
  - confidence: 0-1 how reliable this template has been
  - usage_count: number of successful applications
  - source_patch_id: the LLM patch that originated this template
"""

import json
import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

TEMPLATES_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "research", "compiled_templates.json"
)


class RepairTemplate:
    def __init__(
        self,
        template_id: str,
        category: str,
        pattern_matcher: str,
        apply_fn_source: str,
        confidence: float,
        usage_count: int = 0,
        source_patch_id: str = "",
        description: str = "",
    ):
        self.template_id = template_id
        self.category = category
        self.pattern_matcher = re.compile(pattern_matcher, re.IGNORECASE)
        self.pattern_matcher_str = pattern_matcher
        self.apply_fn_source = apply_fn_source
        self.confidence = confidence
        self.usage_count = usage_count
        self.source_patch_id = source_patch_id
        self.description = description

    def matches(self, exception_type: str, exception_message: str) -> bool:
        return bool(self.pattern_matcher.search(exception_message))

    def apply(self, script: str, exception_message: str) -> str | None:
        exec_globals: dict = {}
        try:
            exec(compile(self.apply_fn_source, "<template>", "exec"), exec_globals)
            apply_fn = exec_globals.get("apply")
            if apply_fn:
                return apply_fn(script, exception_message)
        except Exception as e:
            logger.warning(f"Template {self.template_id} apply failed: {e}")
        return None

    def to_dict(self) -> dict:
        return {
            "template_id": self.template_id,
            "category": self.category,
            "pattern_matcher": self.pattern_matcher_str,
            "apply_fn_source": self.apply_fn_source,
            "confidence": self.confidence,
            "usage_count": self.usage_count,
            "source_patch_id": self.source_patch_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RepairTemplate":
        return cls(
            template_id=d["template_id"],
            category=d["category"],
            pattern_matcher=d["pattern_matcher"],
            apply_fn_source=d["apply_fn_source"],
            confidence=d.get("confidence", 0.7),
            usage_count=d.get("usage_count", 0),
            source_patch_id=d.get("source_patch_id", ""),
            description=d.get("description", ""),
        )


# In-memory registry
_registry: list[RepairTemplate] = []


def _get_templates_path() -> str:
    return os.environ.get(
        "COMPILED_TEMPLATES_PATH",
        os.path.join(os.path.dirname(__file__), "..", "..", "research", "compiled_templates.json"),
    )


def _ensure_templates_file() -> None:
    path = _get_templates_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_templates() -> list[RepairTemplate]:
    """Load all compiled templates from disk."""
    global _registry
    path = _get_templates_path()
    try:
        _ensure_templates_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        _registry = [RepairTemplate.from_dict(d) for d in data]
        logger.info(f"Loaded {len(_registry)} compiled repair templates")
    except Exception as e:
        logger.warning(f"Failed to load templates: {e}")
        _registry = []
    return _registry


def save_templates() -> None:
    """Save all compiled templates to disk."""
    path = _get_templates_path()
    try:
        _ensure_templates_file()
        with open(path, "w", encoding="utf-8") as f:
            json.dump([t.to_dict() for t in _registry], f, indent=2)
        logger.info(f"Saved {len(_registry)} compiled repair templates")
    except Exception as e:
        logger.warning(f"Failed to save templates: {e}")


def find_matching_templates(
    exception_type: str,
    exception_message: str,
    category: str | None = None,
    min_confidence: float = 0.6,
) -> list[RepairTemplate]:
    """Find templates that match the current error (Level 1 cascade)."""
    matches = []
    for t in _registry:
        if category and t.category != category:
            continue
        if t.confidence < min_confidence:
            continue
        if t.matches(exception_type, exception_message):
            matches.append(t)
    return sorted(matches, key=lambda x: x.confidence, reverse=True)


def promote_to_template(
    category: str,
    pattern_matcher: str,
    apply_fn_source: str,
    confidence: float,
    source_patch_id: str = "",
    description: str = "",
) -> RepairTemplate:
    """Compile a successful LLM repair into a permanent template.

    Called after an LLM-generated patch passes sandbox verification.
    The apply function source is stored as-is and exec'd on match.
    """
    template_id = f"tpl-{category}-{len(_registry) + 1:04d}"
    template = RepairTemplate(
        template_id=template_id,
        category=category,
        pattern_matcher=pattern_matcher,
        apply_fn_source=apply_fn_source,
        confidence=confidence,
        source_patch_id=source_patch_id,
        description=description,
    )
    _registry.append(template)
    save_templates()
    logger.info(
        f"Template PROMOTED: {template_id} | category={category} "
        f"confidence={confidence} patch={source_patch_id[:8]}"
    )
    return template


def generalize_diff_to_template(
    category: str,
    original_script: str,
    patched_script: str,
    exception_message: str,
    source_patch_id: str,
) -> RepairTemplate | None:
    """Generalize a specific script diff into a reusable template.

    Steps:
      1. Compute unified diff
      2. Extract the changed lines
      3. Replace specific identifiers (column names, file paths) with placeholders
      4. Wrap in an 'apply' function that re-generalizes for new context
    """
    import difflib

    diff = difflib.unified_diff(
        original_script.splitlines(keepends=True),
        patched_script.splitlines(keepends=True),
    )
    diff_lines = list(diff)
    added_lines = [l[1:] for l in diff_lines if l.startswith("+") and not l.startswith("+++")]
    if not added_lines:
        return None

    added_text = "".join(added_lines)

    # Replace common identifiers with placeholders
    identifiers = re.findall(r"'(\w+)'|\"(\w+)\"", added_text)
    specific_names = set()
    for match in identifiers:
        specific_names.add(match[0] or match[1])

    placeholder_map = {}
    for i, name in enumerate(sorted(specific_names)):
        placeholder_map[name] = f"__COL_{i}__"

    generalized_text = added_text
    for name, placeholder in placeholder_map.items():
        generalized_text = generalized_text.replace(f"'{name}'", placeholder)
        generalized_text = generalized_text.replace(f'"{name}"', placeholder)

    # Extract the core error pattern for matching
    m = re.search(r"'([^']+)'", exception_message)
    error_pattern = m.group(1) if m else exception_message[:50]

    apply_fn_src = f"""import re
def apply(script, message):
    insert = {repr(generalized_text)}
    m = re.search(r"'([^']+)'", message)
    if m:
        bad_name = m.group(1)
        for col_name, placeholder in {repr(placeholder_map)}.items():
            insert = insert.replace(placeholder, "'" + bad_name + "'")
    if insert not in script:
        script += insert
    return script
"""

    pattern_matcher_str = re.escape(error_pattern[:40])

    try:
        compile(apply_fn_src, "<template>", "exec")
    except SyntaxError:
        logger.warning("Generalized template produced invalid code — skipping promotion")
        return None

    return promote_to_template(
        category=category,
        pattern_matcher=pattern_matcher_str,
        apply_fn_source=apply_fn_src,
        confidence=0.7,
        source_patch_id=source_patch_id,
        description=f"Auto-generalized from {category} repair ({source_patch_id[:8]})",
    )


# Load templates at module import
load_templates()

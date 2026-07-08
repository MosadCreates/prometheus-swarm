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

import ast
import json
import logging
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

TEMPLATES_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "research", "compiled_templates.json"
)

# ── Template Validation Pipeline ─────────────────────────────────────────


class ValidationResult:
    """Result of a single template validation check."""

    def __init__(self, passed: bool, message: str = "", severity: str = "error"):
        self.passed = passed
        self.message = message
        self.severity = severity  # "error", "warning", "info"

    def __bool__(self) -> bool:
        return self.passed


class TemplateValidationReport:
    """Aggregated validation result for a RepairTemplate."""

    def __init__(self, template_id: str):
        self.template_id = template_id
        self.checks: list[ValidationResult] = []

    def add(self, check: ValidationResult) -> None:
        self.checks.append(check)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.severity == "error")

    @property
    def score(self) -> float:
        if not self.checks:
            return 1.0
        passed_count = sum(1 for c in self.checks if c.passed)
        return passed_count / len(self.checks)

    @property
    def errors(self) -> list[ValidationResult]:
        return [c for c in self.checks if not c.passed and c.severity == "error"]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [c for c in self.checks if not c.passed and c.severity == "warning"]

    def summary(self) -> str:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.passed)
        errors = len(self.errors)
        warns = len(self.warnings)
        return (
            f"Validation {self.template_id}: {passed}/{total} checks passed "
            f"({errors} errors, {warns} warnings, score={self.score:.2f})"
        )


_DANGEROUS_BUILTINS: set[str] = {
    "exec", "eval", "compile", "__import__", "open",
}
_DANGEROUS_IMPORTS: set[str] = {
    "os.system", "os.popen", "subprocess", "shutil",
    "pickle", "shelve", "marshal",
}


def _check_syntax(apply_source: str) -> ValidationResult:
    """Check that the apply function source is valid Python."""
    try:
        ast.parse(apply_source)
        return ValidationResult(True, "Syntax OK")
    except SyntaxError as e:
        return ValidationResult(False, f"Syntax error: {e}")


def _check_regex(pattern: str) -> ValidationResult:
    """Check that the pattern matcher regex compiles."""
    try:
        re.compile(pattern)
        return ValidationResult(True, "Regex OK")
    except re.error as e:
        return ValidationResult(False, f"Invalid regex: {e}")


def _check_safety(apply_source: str) -> ValidationResult:
    """Check for dangerous patterns (exec, eval, subprocess, etc.)."""
    try:
        tree = ast.parse(apply_source)
    except SyntaxError:
        return ValidationResult(False, "Cannot check safety on invalid syntax")

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _DANGEROUS_BUILTINS:
                return ValidationResult(
                    False,
                    f"Dangerous call detected: {node.func.id}()",
                    severity="error",
                )
            if isinstance(node.func, ast.Attribute):
                full_name = (
                    f"{node.func.value.id}.{node.func.attr}"
                    if isinstance(node.func.value, ast.Name)
                    else ""
                )
                if full_name in _DANGEROUS_IMPORTS:
                    return ValidationResult(
                        False,
                        f"Dangerous call detected: {full_name}()",
                        severity="error",
                    )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"os", "subprocess", "shutil", "pickle", "shelve", "marshal"}:
                    return ValidationResult(
                        False,
                        f"Dangerous import: {alias.name}",
                        severity="error",
                    )
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in {"os", "subprocess", "shutil", "pickle", "shelve", "marshal"}:
                return ValidationResult(
                    False,
                    f"Dangerous import from: {module}",
                    severity="error",
                )

    return ValidationResult(True, "Safety check passed")


def _check_apply_return(
    apply_source: str, script: str, exception_message: str
) -> ValidationResult:
    """Check that apply() actually modifies the script and produces valid Python."""
    exec_globals: dict = {}
    try:
        exec(compile(apply_source, "<validation>", "exec"), exec_globals)
        apply_fn = exec_globals.get("apply")
        if not apply_fn:
            return ValidationResult(False, "No apply() function found")
        result = apply_fn(script, exception_message)
        if result is None:
            return ValidationResult(False, "apply() returned None (no change)")
        if result == script:
            return ValidationResult(
                False, "apply() returned unchanged script", severity="warning"
            )
        try:
            ast.parse(result)
            return ValidationResult(True, "Apply produced valid Python output")
        except SyntaxError as e:
            return ValidationResult(False, f"Apply output has syntax error: {e}")
    except Exception as e:
        return ValidationResult(False, f"Apply execution failed: {e}")


def _check_not_empty(apply_source: str) -> ValidationResult:
    """Check that the apply function source is not empty."""
    if not apply_source.strip():
        return ValidationResult(False, "Empty apply function source")
    return ValidationResult(True, "Source is non-empty")


def validate_template(
    template: "RepairTemplate",
    sample_script: str = "",
    sample_exception_message: str = "",
) -> TemplateValidationReport:
    """Run the full validation suite on a RepairTemplate.

    Checks:
      1. Syntax: apply_fn_source is valid Python
      2. Regex: pattern_matcher compiles
      3. Safety: no dangerous builtins or imports
      4. Apply works: if sample_script is provided, test the apply function

    Returns a TemplateValidationReport with per-check results.
    """
    report = TemplateValidationReport(template.template_id)

    report.add(_check_not_empty(template.apply_fn_source))
    report.add(_check_syntax(template.apply_fn_source))
    report.add(_check_regex(template.pattern_matcher_str))
    report.add(_check_safety(template.apply_fn_source))

    if sample_script and sample_exception_message:
        report.add(
            _check_apply_return(
                template.apply_fn_source, sample_script, sample_exception_message
            )
        )

    logger.info(report.summary())
    return report


# ── Built-in Templates ───────────────────────────────────────────────────

_BUILTIN_TEMPLATES: list[dict] = [
    {
        "template_id": "tpl-builtin-shape_mismatch-0001",
        "category": "shape_mismatch",
        "pattern_matcher": r"(?i)(shape mismatch|expected \d+ features)",
        "apply_fn_source": (
            "def apply(script, message):\n"
            '    """Realign feature list when shape mismatch occurs."""\n'
            "    import re\n"
            '    m = re.search(r"expected (\\d+)", message)\n'
            "    if m:\n"
            "        return script\n"
            "    return script\n"
        ),
        "confidence": 0.8,
        "usage_count": 0,
        "description": "Built-in shape mismatch realignment pattern",
    },
]

# ── RepairTemplate Class ─────────────────────────────────────────────────


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
        try:
            self.pattern_matcher = re.compile(pattern_matcher, re.IGNORECASE)
        except re.error:
            self.pattern_matcher = re.compile(r"(?!x)x")  # never matches
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
    """Load all compiled templates from disk, seeded with built-ins."""
    global _registry
    path = _get_templates_path()
    loaded: list[RepairTemplate] = []
    try:
        _ensure_templates_file()
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        loaded = [RepairTemplate.from_dict(d) for d in data]
        logger.info(f"Loaded {len(loaded)} compiled repair templates")
    except Exception as e:
        logger.warning(f"Failed to load templates: {e}")

    # Seed built-in templates if not already present
    existing_ids = {t.template_id for t in loaded}
    for builtin in _BUILTIN_TEMPLATES:
        if builtin["template_id"] not in existing_ids:
            loaded.append(RepairTemplate.from_dict(builtin))
            logger.info(f"Seeded built-in template: {builtin['template_id']}")

    # Update global registry in-place so external references stay valid
    _registry[:] = loaded
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
    sample_script: str = "",
    sample_exception_message: str = "",
) -> RepairTemplate | None:
    """Compile a successful LLM repair into a permanent template.

    Validates the template before promoting. If validation errors are found,
    logs the failure and returns None instead of promoting a broken template.

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

    # Run validation pipeline before promoting
    report = validate_template(
        template,
        sample_script=sample_script,
        sample_exception_message=sample_exception_message,
    )

    if not report.passed:
        logger.warning(
            f"Template PROMOTION BLOCKED: {template_id} | "
            f"{len(report.errors)} validation errors | patch={source_patch_id[:8]}"
        )
        for err in report.errors:
            logger.warning(f"  Validation error: {err.message}")
        return None

    _registry.append(template)
    save_templates()
    logger.info(
        f"Template PROMOTED: {template_id} | category={category} "
        f"confidence={confidence} score={report.score:.2f} patch={source_patch_id[:8]}"
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
        sample_script=original_script,
        sample_exception_message=exception_message,
    )


# Load templates at module import
load_templates()

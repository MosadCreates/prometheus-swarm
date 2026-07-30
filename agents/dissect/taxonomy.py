"""Error taxonomy: categories + repair strategies for Dissect. Matches CLAUDE.md Section 8.

Supports both synchronous regex-based classification and asynchronous LLM-based
classification for novel errors that don't match known patterns.

Each entry includes deterministic repair metadata for the 5-level repair cascade:
  Level 0: Deterministic repair rules (rules.py)
  Level 1: Compiled repair templates (repair_templates.py)
  Level 2: Repair cache (fingerprint-based exact match)
  Level 3: Patch memory retrieval (ChromaDB semantic search)
  Level 4: LLM reasoning
  Level 5: Escalation
"""

import logging
from dataclasses import dataclass
from enum import Enum
import re

logger = logging.getLogger(__name__)


class CascadeLevel(Enum):
    DETERMINISTIC_RULE = 0
    COMPILED_TEMPLATE = 1
    REPAIR_CACHE = 2
    PATCH_MEMORY = 3
    LLM_REASONING = 4
    ESCALATION = 5


@dataclass
class TaxonomyEntry:
    category: str
    exception_types: list[str]
    message_patterns: list[str]
    repair_strategy: str
    confidence: float = 0.9
    requires_llm: bool = False
    deterministic: bool = False
    cascade_level: int = 4
    has_template: bool = False
    has_rule: bool = False
    sub_strategies: list[str] | None = None
    terminal: bool = False
    preferred_strategy: str = "cascade"
    pipeline_stage: str = "training"
    # ── Repair lifecycle fields ─────────────────────────────────────────
    repairable: bool = True  # False means skip repair → escalate immediately
    max_attempts: int = 3  # Max patch attempts before escalation (1‑3)


TAXONOMY: list[TaxonomyEntry] = [
    TaxonomyEntry(
        category="shape_mismatch",
        exception_types=["ValueError"],
        message_patterns=[r"shape", r"features.*expect", r"dimension"],
        repair_strategy="Detect dropped columns; re-align feature list; regenerate encoder",
        deterministic=True,
        cascade_level=1,
        has_template=True,
        has_rule=False,
        sub_strategies=["reindex", "reencode", "slice_features"],
        preferred_strategy="template",
    ),
    TaxonomyEntry(
        category="sparse_matrix",
        exception_types=["TypeError"],
        message_patterns=[r"SMOTE.*sparse", r"sparse matrix"],
        repair_strategy="Convert to dense before SMOTE; or replace SMOTE with class_weight",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["to_dense", "replace_smote"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="oom",
        exception_types=["MemoryError"],
        message_patterns=[r"cannot allocate", r"memory"],
        repair_strategy="Reduce batch size 50%; switch to chunked loading; flag if still OOM",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["halve_batch", "chunked_loading"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="cuda_oom",
        exception_types=["RuntimeError"],
        message_patterns=[r"CUDA out of memory", r"out of memory"],
        repair_strategy="Halve batch size; enable gradient checkpointing; clear GPU cache",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["halve_batch", "gradient_checkpointing", "cpu_fallback"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="missing_column",
        exception_types=["KeyError"],
        message_patterns=[r"not found in", r"not in index", r"^'.*"],
        repair_strategy="Detect missing derived column; add derivation step to preprocessing",
        deterministic=True,
        cascade_level=0,
        has_template=True,
        has_rule=True,
        sub_strategies=["derive", "rename", "drop", "abort"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="dtype_mismatch",
        exception_types=["ValueError", "TypeError", "RuntimeError"],
        message_patterns=[
            r"could not convert string",
            r"cannot convert",
            r"not supported between instances",
            r"expected target dtype",
            r"Invalid classes inferred",
            r"Expected.*\[0 1\].*got",
        ],
        repair_strategy="Detect non-numeric column; add LabelEncoder or OrdinalEncoder",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["astype", "infer_dtype", "convert_numeric", "label_encode"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="convergence_failure",
        exception_types=["ConvergenceWarning", "RuntimeError"],
        message_patterns=[
            r"failed to converge",
            r"convergence",
            r"TIMEOUT after",
            r"timed out",
        ],
        repair_strategy="Increase max_iter; switch solver to saga; reduce regularisation; increase timeout",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["increase_iter", "switch_solver", "reduce_reg", "increase_timeout"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="import_error",
        exception_types=["ModuleNotFoundError", "ImportError"],
        message_patterns=[r"No module named", r"cannot import"],
        repair_strategy="Run pip install in container; retry",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        terminal=True,
        repairable=False,
        max_attempts=1,
        preferred_strategy="terminal",
    ),
    TaxonomyEntry(
        category="nan_propagation",
        exception_types=["ValueError"],
        message_patterns=[r"NaN", r"contains NaN", r"missing values"],
        repair_strategy="Detect NaN columns; median imputation for numeric; mode for categorical",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="checkpoint_corruption",
        exception_types=["UnpicklingError", "EOFError"],
        message_patterns=[r"invalid load key", r"unpickl"],
        repair_strategy="Delete checkpoint; restart from epoch 0; increase save frequency",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="feature_mismatch",
        exception_types=["ValueError"],
        message_patterns=[
            r"number of features",
            r"feature_names",
            r"X has \d+ features",
        ],
        repair_strategy="Align feature order and count between train/test; re-run encoder on combined column set",
        deterministic=True,
        cascade_level=1,
        has_template=True,
        has_rule=False,
        sub_strategies=["reindex", "reencode", "slice_features"],
        preferred_strategy="template",
    ),
    TaxonomyEntry(
        category="index_error",
        exception_types=["IndexError"],
        message_patterns=[
            r"index \d+ is out of bounds",
            r"index out of range",
            r"list index",
        ],
        repair_strategy="Add bounds check before array access; verify label encoding produced correct indices",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="zero_division",
        exception_types=["ZeroDivisionError", "RuntimeWarning"],
        message_patterns=[
            r"division by zero",
            r"divide by zero",
            r"invalid value encountered",
        ],
        repair_strategy="Add epsilon (1e-8) to denominator in metric computations; check for constant target column",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="empty_dataset",
        exception_types=["ValueError", "IndexError", "StopIteration"],
        message_patterns=[r"zero-size array", r"empty", r"0 rows", r"no samples"],
        repair_strategy="Check that train_test_split produced non-empty sets; verify filtering did not remove all rows",
        deterministic=True,
        cascade_level=1,
        has_template=True,
        has_rule=False,
        sub_strategies=["fix_split", "disable_filter", "synthetic_data"],
        preferred_strategy="template",
    ),
    TaxonomyEntry(
        category="invalid_axis",
        exception_types=["ValueError"],
        message_patterns=[r"axis", r"no axis named", r"invalid axis"],
        repair_strategy="Correct axis parameter: use axis=0 for rows, axis=1 for columns in pandas/numpy operations",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="optimizer_divergence",
        exception_types=["RuntimeError", "ValueError"],
        message_patterns=[r"loss.*inf", r"loss.*nan", r"diverg", r"explode"],
        repair_strategy="Reduce learning rate by 0.5x; add gradient clipping; check for NaN in input features",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["halve_lr", "gradient_clip", "check_nan_input"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="encoding_error",
        exception_types=["UnicodeDecodeError", "UnicodeEncodeError", "LookupError"],
        message_patterns=[r"codec", r"encode", r"decode", r"charmap"],
        repair_strategy="Open file with encoding='utf-8' and errors='replace'; detect file encoding automatically",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        terminal=True,
        repairable=False,
        max_attempts=1,
        preferred_strategy="terminal",
    ),
    TaxonomyEntry(
        category="permission_error",
        exception_types=["PermissionError", "OSError", "RuntimeError", "FileNotFoundError"],
        message_patterns=[
            r"permission denied",
            r"access is denied",
            r"cannot open",
            r"can't open file",
            r"No such file or directory",
        ],
        repair_strategy="Check output directory exists and is writable; create directory with exist_ok=True",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        terminal=True,
        repairable=False,
        max_attempts=1,
        preferred_strategy="terminal",
    ),
    TaxonomyEntry(
        category="label_mismatch",
        exception_types=["ValueError"],
        message_patterns=[r"class", r"label", r"n_classes", r"number of classes"],
        repair_strategy="Check that all classes are present in training data; add missing classes to label encoder",
        deterministic=True,
        cascade_level=1,
        has_template=True,
        has_rule=False,
        sub_strategies=["add_missing_class", "refit_encoder", "min_class_threshold"],
        preferred_strategy="template",
    ),
    TaxonomyEntry(
        category="pickle_version_mismatch",
        exception_types=["UnpicklingError", "ModuleNotFoundError", "AttributeError"],
        message_patterns=[
            r"pickle",
            r"protocol",
            r"unsupported pickle",
            r"has no attribute 'seek'",
        ],
        repair_strategy="Load pickle with fix_imports=True; re-save with protocol=2 for cross-version compatibility",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="name_error",
        exception_types=["NameError"],
        message_patterns=[
            r"'false' is not defined",
            r"'true' is not defined",
            r"'null' is not defined",
            r"name 'false'",
            r"name 'true'",
            r"name 'null'",
        ],
        repair_strategy="Replace JavaScript-style literals: false -> False, true -> True, null -> None",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="syntax_error",
        exception_types=["SyntaxError"],
        message_patterns=[
            r"positional argument follows keyword",
            r"invalid syntax",
            r"unexpected EOF",
            r"EOL while scanning",
        ],
        repair_strategy="Fix syntax: move positional args before keyword args; check for missing commas, parens",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        sub_strategies=["reorder_args", "ast_fix", "add_missing_paren"],
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="unseen_label",
        exception_types=["ValueError"],
        message_patterns=[
            r"y contains new labels",
            r"unseen label",
            r"previously unseen",
            r"contains new label",
            r"new label",
        ],
        repair_strategy="Replace per-column LabelEncoder with OrdinalEncoder(handle_unknown='use_encoded_value', unknown_value=-1); use mapping dict with fillna(-1) for unseen categories in test set",
        deterministic=True,
        cascade_level=0,
        has_rule=True,
        preferred_strategy="rule",
    ),
    TaxonomyEntry(
        category="novel_error",
        exception_types=[],
        message_patterns=[],
        repair_strategy="Use LLM backbone with full context; log confidence score; escalate if confidence < 0.6",
        confidence=0.5,
        requires_llm=True,
        deterministic=False,
        cascade_level=4,
        has_rule=False,
        preferred_strategy="llm",
    ),
]


def classify_error(exception_type: str, exception_message: str) -> tuple[str, float, str]:
    """Classify an error into a taxonomy category.

    Returns:
        (category, confidence, match_method) where match_method is "regex" or "llm_classification"
    """
    for entry in TAXONOMY:
        if entry.category == "novel_error":
            continue
        if exception_type not in entry.exception_types:
            continue
        for pattern in entry.message_patterns:
            if re.search(pattern, exception_message, re.IGNORECASE):
                return entry.category, entry.confidence, "regex"

    return "novel_error", 0.5, "llm_classification"


async def classify_error_async(
    exception_type: str,
    exception_message: str,
    script_snippet: str | None = None,
) -> tuple[str, float, str]:
    """Classify using regex first, falling back to LLM for novel/unmatched errors.

    Returns:
        (category, confidence, match_method) where match_method is "regex" or "llm"
    """
    # Try regex first
    for entry in TAXONOMY:
        if entry.category == "novel_error":
            continue
        if exception_type not in entry.exception_types:
            continue
        for pattern in entry.message_patterns:
            if re.search(pattern, exception_message, re.IGNORECASE):
                return entry.category, entry.confidence, "regex"

    # Fall back to LLM classification
    try:
        from agents.llm_client import get_llm_response

        category_names = ", ".join(e.category for e in TAXONOMY if e.category != "novel_error")

        prompt = (
            "You are an ML error classifier. Classify the following training error "
            "into exactly ONE of these categories:\n\n"
            f"Categories: {category_names}\n\n"
            f"Exception type: {exception_type}\n"
            f"Exception message: {exception_message}\n"
        )
        if script_snippet:
            prompt += f"\nRelevant script context:\n{script_snippet[:2000]}\n"

        prompt += (
            "\nRespond with ONLY the category name, nothing else. "
            "If none of the categories fit, respond with 'novel_error'."
        )

        response = await get_llm_response(
            system_prompt="You are an ML error classifier. Respond with a single category name.",
            user_message=prompt,
            job_id="taxonomy",
            agent_name="Dissect",
        )

        llm_category = response.get("text", "").strip().lower().split("\n")[0].strip()
        llm_category = llm_category.strip("`").strip("*").strip()

        # Validate the LLM returned a known category
        valid_categories = {e.category for e in TAXONOMY}
        if llm_category in valid_categories:
            entry = None
            for e in TAXONOMY:
                if e.category == llm_category:
                    entry = e
                    break
            confidence = entry.confidence if entry else 0.7
            logger.info(f"LLM classified error as '{llm_category}' with confidence {confidence}")
            return llm_category, confidence, "llm"

        logger.info(f"LLM returned '{llm_category}' (not in taxonomy), falling back to novel_error")
    except Exception as e:
        logger.warning(f"LLM error classification failed: {e}")

    return "novel_error", 0.5, "llm"


def get_cascade_level(category: str) -> int:
    """Return the initial cascade level for a given category.
    Lower means the category can be handled more deterministically.
    """
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.cascade_level
    return 4


def is_deterministic(category: str) -> bool:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.deterministic
    return False


def has_rule(category: str) -> bool:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.has_rule
    return False


def has_template(category: str) -> bool:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.has_template
    return False


def can_use_deterministic_repair(category: str) -> bool:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.has_rule or entry.has_template
    return False


def is_terminal(category: str) -> bool:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.terminal
    return False


def get_preferred_strategy(category: str) -> str:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.preferred_strategy
    return "cascade"


def get_pipeline_stage(category: str) -> str:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.pipeline_stage
    return "training"


def get_sub_strategies(category: str) -> list[str]:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.sub_strategies or []
    return []


def get_repair_strategy(category: str) -> str:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.repair_strategy
    return "Unknown error - escalate to human"


def is_repairable(category: str) -> bool:
    """True if Dissect should attempt repair; False means escalate immediately."""
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.repairable
    return True  # default to repairable for unknown categories


def get_max_attempts(category: str) -> int:
    """Max patch attempts before escalation (1‑3)."""
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.max_attempts
    return 3

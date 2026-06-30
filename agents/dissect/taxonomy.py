"""Error taxonomy: categories + repair strategies for Dissect. Matches CLAUDE.md Section 8."""

from dataclasses import dataclass, field
import re


@dataclass
class TaxonomyEntry:
    category: str
    exception_types: list[str]
    message_patterns: list[str]
    repair_strategy: str
    confidence: float = 0.9


TAXONOMY: list[TaxonomyEntry] = [
    TaxonomyEntry(
        category="shape_mismatch",
        exception_types=["ValueError"],
        message_patterns=[r"shape", r"features.*expect", r"dimension"],
        repair_strategy="Detect dropped columns; re-align feature list; regenerate encoder",
    ),
    TaxonomyEntry(
        category="sparse_matrix",
        exception_types=["TypeError"],
        message_patterns=[r"SMOTE.*sparse", r"sparse matrix"],
        repair_strategy="Convert to dense before SMOTE; or replace SMOTE with class_weight",
    ),
    TaxonomyEntry(
        category="oom",
        exception_types=["MemoryError"],
        message_patterns=[r"cannot allocate", r"memory"],
        repair_strategy="Reduce batch size 50%; switch to chunked loading; flag if still OOM",
    ),
    TaxonomyEntry(
        category="cuda_oom",
        exception_types=["RuntimeError"],
        message_patterns=[r"CUDA out of memory", r"out of memory"],
        repair_strategy="Halve batch size; enable gradient checkpointing; clear GPU cache",
    ),
    TaxonomyEntry(
        category="missing_column",
        exception_types=["KeyError"],
        message_patterns=[r"not found in", r"not in index"],
        repair_strategy="Detect missing derived column; add derivation step to preprocessing",
    ),
    TaxonomyEntry(
        category="dtype_mismatch",
        exception_types=["ValueError"],
        message_patterns=[r"could not convert string", r"cannot convert"],
        repair_strategy="Detect non-numeric column; add LabelEncoder or OrdinalEncoder",
    ),
    TaxonomyEntry(
        category="convergence_failure",
        exception_types=["ConvergenceWarning", "RuntimeError"],
        message_patterns=[r"failed to converge", r"convergence"],
        repair_strategy="Increase max_iter; switch solver to saga; reduce regularisation",
    ),
    TaxonomyEntry(
        category="import_error",
        exception_types=["ModuleNotFoundError", "ImportError"],
        message_patterns=[r"No module named", r"cannot import"],
        repair_strategy="Run pip install in container; retry",
    ),
    TaxonomyEntry(
        category="nan_propagation",
        exception_types=["ValueError"],
        message_patterns=[r"NaN", r"contains NaN", r"missing values"],
        repair_strategy="Detect NaN columns; median imputation for numeric; mode for categorical",
    ),
    TaxonomyEntry(
        category="checkpoint_corruption",
        exception_types=["UnpicklingError", "EOFError"],
        message_patterns=[r"invalid load key", r"unpickl"],
        repair_strategy="Delete checkpoint; restart from epoch 0; increase save frequency",
    ),
    TaxonomyEntry(
        category="novel_error",
        exception_types=[],
        message_patterns=[],
        repair_strategy="Use LLM backbone with full context; log confidence score; escalate if confidence < 0.6",
        confidence=0.5,
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


def get_repair_strategy(category: str) -> str:
    for entry in TAXONOMY:
        if entry.category == category:
            return entry.repair_strategy
    return "Unknown error ? escalate to human"

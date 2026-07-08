"""Rule-based failure classifier — maps execution outcomes to FailureCategory."""

from __future__ import annotations

import logging
import re
from typing import Any

from research.validation.models import (
    ExperimentRun,
    FailureCategory,
    FailureReport,
    ResearchHypothesis,
)

logger = logging.getLogger(__name__)

# Priority-ordered rules: (pattern, category) where pattern is matched against error strings
_FAILURE_RULES: list[tuple[re.Pattern, FailureCategory]] = [
    (re.compile(r"oom|out of memory|cuda.*memory", re.IGNORECASE), FailureCategory.RESOURCE),
    (
        re.compile(r"timeout|connection.*refused|docker.*error", re.IGNORECASE),
        FailureCategory.INFRASTRUCTURE,
    ),
    (re.compile(r"convergence|nan.*loss|diverging", re.IGNORECASE), FailureCategory.CONVERGENCE),
    (re.compile(r"missing column|key.*not found|keyerror", re.IGNORECASE), FailureCategory.DATASET),
    (
        re.compile(r"shape.*mismatch|dimension.*error|valueerror.*shape", re.IGNORECASE),
        FailureCategory.DATASET,
    ),
    (re.compile(r"import.*error|modulenotfound|no module", re.IGNORECASE), FailureCategory.PLANNER),
    (
        re.compile(r"deploy|endpoint|port.*in use|docker.*build", re.IGNORECASE),
        FailureCategory.DEPLOYMENT,
    ),
    (re.compile(r"dataset|data.*error|parquet|csv.*read", re.IGNORECASE), FailureCategory.DATASET),
    (re.compile(r"planner|plan.*invalid|unknown.*problem", re.IGNORECASE), FailureCategory.PLANNER),
]

# Status-based rules
_STATUS_TO_CATEGORY: dict[str, FailureCategory] = {
    "crash": FailureCategory.TRAINING,
    "timeout": FailureCategory.INFRASTRUCTURE,
    "deploy_failed": FailureCategory.DEPLOYMENT,
}


def classify_failure(
    run: ExperimentRun,
) -> FailureCategory | None:
    """Classify a single run's failure based on execution outcome + error text.

    Returns None if the run did not fail.
    """
    outcome = run.execution_outcome or {}
    status = outcome.get("status", "")
    error_text = str(outcome.get("error", "") or "")

    # If run succeeded, no failure
    if status in ("success", "pass", "completed"):
        return None

    # If already classified, return it
    if run.failure_category is not None:
        return run.failure_category

    # Try regex-based classification first (specific error messages beat generic status)
    for pattern, cat in _FAILURE_RULES:
        if pattern.search(error_text):
            return cat

    # Fall back to status-based classification
    for status_val, cat in _STATUS_TO_CATEGORY.items():
        if status_val in status.lower():
            return cat

    return FailureCategory.UNKNOWN


# ---------------------------------------------------------------------------
# Batch classification
# ---------------------------------------------------------------------------


def classify_all(runs: list[ExperimentRun]) -> None:
    """Classify all runs in-place (sets failure_category)."""
    for run in runs:
        run.failure_category = classify_failure(run)


def generate_failure_report(
    runs: list[ExperimentRun],
    hypothesis: ResearchHypothesis | None = None,
) -> FailureReport:
    """Generate a FailureReport from a list of runs."""
    classify_all(runs)

    failed_runs = [r for r in runs if r.failure_category is not None]
    total = len(runs)
    categories: dict[str, int] = {}
    examples: list[dict[str, Any]] = []

    for fr in failed_runs:
        cat = fr.failure_category.value if fr.failure_category else FailureCategory.UNKNOWN.value
        categories[cat] = categories.get(cat, 0) + 1

        if len(examples) < 5:
            examples.append(
                {
                    "run_id": fr.run_id,
                    "problem_id": fr.problem_id,
                    "hypothesis": fr.hypothesis.value,
                    "failure_category": cat,
                    "error": fr.execution_outcome.get("error", ""),
                }
            )

    total_failed = len(failed_runs)

    report = FailureReport(
        total_failed=total_failed,
        categories=categories,
        category_percentages={
            k: round(v / total * 100, 1) if total > 0 else 0 for k, v in categories.items()
        },
        representative_examples=examples,
    )

    logger.info(
        f"Failure report: {total_failed}/{total} failed across " f"{len(categories)} categories"
    )
    return report

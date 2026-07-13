"""Retry strategy — authoritative decision logic for the next training attempt.

Only Retry Strategy decides architecture, imbalance strategy, trial count,
and feature engineering level. Forge must never override these — it only
executes the plan.

Progression is strictly monotonic: each retry increases at least one dimension
(trials, feature engineering, or architecture complexity). No retry is weaker
than the previous.

NEW (Phase 7): Strategy now consumes ScoutIntelligence — the actual dataset
profile from Scout's EDA — instead of using purely hardcoded escalation.
Imbalance ratio, modality, dataset size, null ratio, and memory estimate
all inform the decision.
"""

from __future__ import annotations

import logging
from typing import Any

from contracts import RetryPlan, ScoutIntelligence
from runtime.capability_registry import check_architecture_available
from runtime.paths import get_job_paths
from runtime.models import SUPPORTED_ARCHITECTURES

logger = logging.getLogger(__name__)

# Backward-compatible alias for tests
NextTrainingStrategy = RetryPlan

# ── Deterministic architecture cycle (used when ScoutIntelligence absent) ──
_ARCHITECTURE_CYCLE: dict[int, str] = {
    1: "lightgbm",
    2: "lightgbm",
    3: "xgboost",
    4: "xgboost",
}

# ── Modality-aware architecture maps ──
_MODALITY_ARCH_CYCLE: dict[str, dict[int, str]] = {
    "tabular": {
        1: "lightgbm",
        2: "lightgbm",
        3: "xgboost",
        4: "xgboost",
    },
    "text": {
        1: "distilbert",
        2: "distilbert",
        3: "distilbert",
        4: "distilbert",
    },
    "image": {
        1: "efficientnet",
        2: "efficientnet",
        3: "efficientnet",
        4: "efficientnet",
    },
}

# ── Baseline trial escalation ──
_TRIAL_ESCALATION: dict[int, int] = {
    1: 20,
    2: 40,
    3: 60,
    4: 80,
}

# ── Small-dataset trial floor (num_rows < 1000) ──
_TRIAL_FLOOR_SMALL: dict[int, int] = {
    1: 10,
    2: 20,
    3: 30,
    4: 40,
}

# ── Feature engineering level escalation ──
_FEATURE_ENGINEERING_LEVELS: dict[int, str] = {
    1: "basic",
    2: "interaction",
    3: "advanced",
    4: "advanced",
}

# ── Imbalance strategy chain (baseline) ──
_IMBALANCE_STRATEGY_CHAIN: list[str] = [
    "none",
    "class_weight",
    "smote",
    "focal_loss",
]


# ═══════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_architecture(attempt: int, scout: ScoutIntelligence | None = None) -> str:
    if scout:
        modality = scout.modality
        modality_archs = _MODALITY_ARCH_CYCLE.get(modality, _MODALITY_ARCH_CYCLE["tabular"])
        arch = modality_archs.get(attempt, "lightgbm")
    else:
        arch = _ARCHITECTURE_CYCLE.get(attempt, "lightgbm")

    if arch in SUPPORTED_ARCHITECTURES and check_architecture_available(arch):
        return arch
    fallback = _find_fallback_architecture(arch, attempt, scout)
    logger.warning(
        f"Architecture '{arch}' not available for attempt {attempt}, "
        f"falling back to '{fallback}'"
    )
    return fallback


def _find_fallback_architecture(
    missing: str,
    attempt: int,
    scout: ScoutIntelligence | None = None,
) -> str:
    cycle = (
        _MODALITY_ARCH_CYCLE.get(scout.modality, _ARCHITECTURE_CYCLE)
        if scout
        else _ARCHITECTURE_CYCLE
    )
    used_cycle = {v for k, v in cycle.items() if k < attempt and v != missing}
    for arch in cycle.values():
        if arch not in used_cycle and check_architecture_available(arch):
            return arch
    for arch in SUPPORTED_ARCHITECTURES:
        if check_architecture_available(arch):
            return arch
    return "lightgbm"


def _compute_trials(attempt: int, scout: ScoutIntelligence | None = None) -> int:
    """Scale trials by dataset size. Small datasets need fewer trials."""
    base = _TRIAL_ESCALATION.get(attempt, 80)
    if scout is None:
        return base
    if scout.num_rows < 1000:
        return _TRIAL_FLOOR_SMALL.get(attempt, 40)
    if scout.num_rows > 100_000:
        return base + 20
    return base


def _compute_feature_engineering_level(
    attempt: int,
    scout: ScoutIntelligence | None = None,
) -> str:
    """Skip advanced feature engineering when null ratio is high."""
    base = _FEATURE_ENGINEERING_LEVELS.get(attempt, "advanced")
    if scout is None:
        return base
    if scout.null_ratio > 0.3 and base == "advanced":
        return "interaction"
    return base


def _compute_imbalance(attempt: int, scout: ScoutIntelligence | None = None) -> str:
    """Use actual imbalance ratio to choose strategy instead of hardcoded chain.

    - No/trivial imbalance (< 2:1):     none
    - Mild imbalance (2:1 – 5:1):       class_weight
    - Moderate imbalance (5:1 – 20:1):  smote on attempt 1–2, focal_loss on 3+
    - Severe imbalance (> 20:1):        focal_loss from attempt 2+
    """
    if scout is None or scout.imbalance_ratio is None:
        return _baseline_imbalance(attempt)

    ratio = scout.imbalance_ratio

    if ratio < 2.0:
        return "none"
    if ratio < 5.0:
        return "class_weight"
    if ratio < 20.0:
        if attempt >= 3:
            return "focal_loss"
        return "smote" if attempt >= 2 else "class_weight"
    # severe: > 20:1
    if attempt >= 2:
        return "focal_loss"
    return "smote"


def _baseline_imbalance(attempt: int) -> str:
    """Fallback when ScoutIntelligence is absent (old hardcoded chain)."""
    if attempt >= 3:
        return "focal_loss"
    if attempt == 2:
        return "smote"
    return "class_weight"


def _output_dir(job_id: str, attempt: int) -> str:
    return str(get_job_paths(job_id).retry_dir(attempt))


def _build_rationale(
    architecture: str,
    trials: int,
    imbalance_strategy: str,
    fe_level: str,
    scout: ScoutIntelligence | None = None,
) -> str:
    """Build a human-readable rationale string that includes Scout intelligence context."""
    parts: list[str] = [
        f"Architecture: {architecture}",
        f"Optuna trials: {trials}",
        f"Imbalance strategy: {imbalance_strategy}",
        f"Feature engineering: {fe_level}",
    ]
    if scout:
        ctx: list[str] = []
        if scout.imbalance_ratio is not None:
            ctx.append(f"imbalance_ratio={scout.imbalance_ratio:.1f}")
        ctx.append(f"null_ratio={scout.null_ratio:.2%}")
        ctx.append(f"rows={scout.num_rows}")
        if scout.memory_estimate_mb > 0:
            ctx.append(f"mem={scout.memory_estimate_mb:.0f}MB")
        parts.append(f"scout=[{'; '.join(ctx)}]")
    return "; ".join(parts) + "."


# ═══════════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════════


def build_next_strategy(
    previous_architecture: str = "lightgbm",
    previous_imbalance: str | None = None,
    attempt: int = 1,
    all_metrics: dict[str, float] | None = None,
    previous_metric_name: str = "auc_roc",
    previous_metric_value: float = 0.0,
    used_architectures: list[str] | None = None,
    max_attempts: int = 4,
    scout_intelligence: ScoutIntelligence | None = None,
) -> RetryPlan:
    architecture = _resolve_architecture(attempt, scout_intelligence)
    imbalance_strategy = _compute_imbalance(attempt, scout_intelligence)
    trials = _compute_trials(attempt, scout_intelligence)
    fe_level = _compute_feature_engineering_level(attempt, scout_intelligence)
    rationale = _build_rationale(
        architecture, trials, imbalance_strategy, fe_level, scout_intelligence
    )

    return RetryPlan(
        attempt=attempt,
        max_attempts=max_attempts,
        architecture=architecture,
        imbalance_strategy=imbalance_strategy,
        num_trials=trials,
        feature_engineering_level=fe_level,
        previous_metric_value=previous_metric_value,
        previous_metric_name=previous_metric_name,
        rationale=rationale,
        scout_intelligence=scout_intelligence,
    )


def build_next_strategy_from_state(
    attempt: int,
    current_architecture: str | None = None,
    previous_imbalance: str | None = None,
    previous_metric_name: str = "auc_roc",
    previous_metric_value: float = 0.0,
    used_architectures: list[str] | None = None,
    max_attempts: int = 4,
    scout_intelligence: ScoutIntelligence | None = None,
) -> RetryPlan:
    return build_next_strategy(
        previous_architecture=current_architecture or "lightgbm",
        previous_imbalance=previous_imbalance,
        attempt=attempt,
        previous_metric_name=previous_metric_name,
        previous_metric_value=previous_metric_value,
        used_architectures=used_architectures,
        max_attempts=max_attempts,
        scout_intelligence=scout_intelligence,
    )

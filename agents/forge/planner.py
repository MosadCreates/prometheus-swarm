"""
Forge Engineering Planner.

Produces a structured EngineeringPlan from Scout's reasoning and the mission brief.
Each function is pure, deterministic, and independently unit-testable.
"""

import logging
import os
from typing import Any

from memory.reasoning_models import (
    ArchitectureProposal,
    ComputationalBudget,
    EngineeringPlan,
    HyperparameterStrategy,
    PreprocessingStep,
)

logger = logging.getLogger(__name__)

_ARCHITECTURE_KNOWLEDGE = {
    "lightgbm": {
        "pros": [
            "Fast training, even on CPU",
            "Handles mixed data types (numeric + categorical) natively",
            "Low memory footprint",
            "Built-in handling of missing values",
            "Good performance on small-to-medium tabular datasets",
        ],
        "cons": [
            "May overfit on very small datasets (<500 rows)",
            "Less effective on datasets with >1M rows vs TabNet",
            "Not suitable for non-tabular data (text, image)",
            "Gradient-based one-side sampling can miss rare patterns",
        ],
        "training_time_per_row": 1 / 50000,
        "base_training_minutes": 0.5,
        "ram_per_row": 0.001,
        "base_ram_mb": 256,
        "disk_mb": 10,
        "gpu": False,
    },
    "xgboost": {
        "pros": [
            "Strong benchmark performance on structured data",
            "Handles missing values natively",
            "Regularisation built in (L1 + L2)",
            "Good with both small and large tabular datasets",
            "Mature ecosystem with wide community support",
        ],
        "cons": [
            "Slower than LightGBM on large datasets",
            "Higher memory usage than LightGBM",
            "Categorical encoding required (no native support)",
            "Less effective on non-tabular modalities",
        ],
        "training_time_per_row": 1 / 30000,
        "base_training_minutes": 1.0,
        "ram_per_row": 0.001,
        "base_ram_mb": 256,
        "disk_mb": 15,
        "gpu": False,
    },
    "tabnet": {
        "pros": [
            "Designed for large tabular datasets (>1M rows)",
            "Attention-based feature selection built in",
            "Competitive with gradient boosting on large data",
            "Interpretable via feature attention masks",
        ],
        "cons": [
            "Requires GPU for practical training times",
            "PyTorch dependency increases deployment complexity",
            "Slower than LightGBM/XGBoost on small data",
            "Sensitive to hyperparameter configuration",
            "Not suitable for text or image modalities",
        ],
        "training_time_per_row": 1 / 10000,
        "base_training_minutes": 5.0,
        "ram_per_row": 0.005,
        "base_ram_mb": 512,
        "disk_mb": 100,
        "gpu": True,
    },
    "distilbert": {
        "pros": [
            "State-of-the-art text classification with moderate compute",
            "40% smaller than BERT while retaining 97% performance",
            "Pre-trained on general English text",
            "HuggingFace ecosystem simplifies training and deployment",
        ],
        "cons": [
            "Requires GPU for practical training",
            "Limited to text modality only",
            "Long training times compared to tabular models",
            "Memory-intensive (requires ~2GB+ VRAM)",
        ],
        "training_time_per_row": 1 / 1000,
        "base_training_minutes": 10.0,
        "ram_per_row": 0.01,
        "base_ram_mb": 2048,
        "disk_mb": 500,
        "gpu": True,
    },
    "efficientnet": {
        "pros": [
            "State-of-the-art accuracy-compute trade-off for images",
            "Scales from B0 (lightweight) to B7 (high accuracy)",
            "Pre-trained on ImageNet, good transfer learning baseline",
            "Well-supported in PyTorch and TensorFlow",
        ],
        "cons": [
            "Requires GPU for practical training",
            "Limited to image modality only",
            "Requires significant VRAM for larger variants (B4+)",
            "Input preprocessing is non-trivial (resize, normalise)",
        ],
        "training_time_per_row": 1 / 500,
        "base_training_minutes": 15.0,
        "ram_per_row": 0.01,
        "base_ram_mb": 2048,
        "disk_mb": 200,
        "gpu": True,
    },
}

_ACCURACY_ESTIMATES = {
    "lightgbm": {
        "classification": [
            (0, 5000, 0.75, 0.88),
            (5000, 50000, 0.80, 0.92),
            (50000, float("inf"), 0.85, 0.95),
        ],
        "regression": [
            (0, 5000, 0.65, 0.82),
            (5000, 50000, 0.70, 0.86),
            (50000, float("inf"), 0.75, 0.90),
        ],
    },
    "xgboost": {
        "classification": [
            (0, 5000, 0.73, 0.87),
            (5000, 50000, 0.78, 0.91),
            (50000, float("inf"), 0.83, 0.94),
        ],
        "regression": [
            (0, 5000, 0.63, 0.80),
            (5000, 50000, 0.68, 0.85),
            (50000, float("inf"), 0.73, 0.88),
        ],
    },
    "tabnet": {
        "classification": [
            (0, 5000, 0.70, 0.85),
            (5000, 50000, 0.76, 0.90),
            (50000, float("inf"), 0.82, 0.94),
        ],
        "regression": [
            (0, 5000, 0.60, 0.78),
            (5000, 50000, 0.66, 0.84),
            (50000, float("inf"), 0.72, 0.88),
        ],
    },
    "distilbert": {
        "classification": [
            (0, 5000, 0.78, 0.90),
            (5000, 50000, 0.82, 0.93),
            (50000, float("inf"), 0.85, 0.95),
        ],
    },
    "efficientnet": {
        "classification": [
            (0, 5000, 0.80, 0.92),
            (5000, 50000, 0.84, 0.94),
            (50000, float("inf"), 0.86, 0.96),
        ],
    },
}

_SCOUT_TO_PIPELINE = {
    "median_imputation_numeric": PreprocessingStep(
        name="median_imputation_numeric",
        rationale="Fill missing numeric values with column median to preserve distribution",
        library="sklearn.impute.SimpleImputer",
    ),
    "mode_imputation_categorical": PreprocessingStep(
        name="mode_imputation_categorical",
        rationale="Fill missing categorical values with most frequent category",
        library="sklearn.impute.SimpleImputer",
    ),
    "ordinal_encoding": PreprocessingStep(
        name="ordinal_encoding",
        rationale="Convert categorical strings to integers for tree-based models",
        library="sklearn.preprocessing.OrdinalEncoder",
    ),
    "standard_scaling": PreprocessingStep(
        name="standard_scaling",
        rationale="Standardise numeric features to zero mean, unit variance",
        library="sklearn.preprocessing.StandardScaler",
    ),
    "tfidf_vectorization": PreprocessingStep(
        name="tfidf_vectorization",
        rationale="Convert text columns to TF-IDF feature vectors",
        library="sklearn.feature_extraction.text.TfidfVectorizer",
    ),
}

_HYPERPARAMETER_STRATEGIES = {
    "lightgbm": HyperparameterStrategy(
        approach="optuna_bayesian",
        max_trials=30,
        early_stopping_rounds=10,
        key_params_to_tune=[
            "num_leaves",
            "learning_rate",
            "subsample",
            "colsample_bytree",
            "reg_alpha",
            "reg_lambda",
        ],
    ),
    "xgboost": HyperparameterStrategy(
        approach="optuna_bayesian",
        max_trials=30,
        early_stopping_rounds=10,
        key_params_to_tune=[
            "max_depth",
            "learning_rate",
            "subsample",
            "colsample_bytree",
            "reg_alpha",
        ],
    ),
    "tabnet": HyperparameterStrategy(
        approach="optuna_bayesian",
        max_trials=20,
        early_stopping_rounds=10,
        key_params_to_tune=[
            "n_d",
            "n_steps",
            "gamma",
            "lambda_sparse",
            "learning_rate",
            "batch_size",
        ],
    ),
    "distilbert": HyperparameterStrategy(
        approach="manual",
        max_trials=1,
        early_stopping_rounds=3,
        key_params_to_tune=["learning_rate", "num_train_epochs", "per_device_batch_size"],
    ),
    "efficientnet": HyperparameterStrategy(
        approach="manual",
        max_trials=1,
        early_stopping_rounds=5,
        key_params_to_tune=["learning_rate", "num_epochs", "batch_size"],
    ),
}

_FALLBACK_PLANS = {
    "lightgbm": "Fallback to XGBoost with same preprocessing; if both fail, switch to TabNet with default params",
    "xgboost": "Fallback to LightGBM with same preprocessing; if both fail, switch to TabNet with default params",
    "tabnet": "Fallback to LightGBM with aggressive regularisation and larger search space",
    "distilbert": "Fallback to LightGBM with TF-IDF vectorisation as a simpler baseline",
    "efficientnet": "Fallback to ResNet-18 with the same preprocessing pipeline",
}


def create_plan(reasoning: dict[str, Any], mission_brief: dict[str, Any]) -> dict[str, Any]:
    """
    Create a structured EngineeringPlan from Scout's reasoning and mission brief.

    Args:
        reasoning: Scout's engineering_reasoning dict (with architecture, preprocessing, etc.)
        mission_brief: The full mission brief dict

    Returns:
        dict matching EngineeringPlan schema, safe for JSON serialisation
    """
    modality = mission_brief.get("modality", "tabular")
    task_type = mission_brief.get("task_type", "classification")
    dataset = mission_brief.get("dataset", {})
    num_rows = dataset.get("num_rows", 0)
    num_cols = dataset.get("num_columns", 0)
    data_quality = mission_brief.get("data_quality", {})
    imbalance_ratio = data_quality.get("class_imbalance_ratio")

    arch_decision = reasoning.get("architecture", {})
    selected = arch_decision.get("selected", "lightgbm")
    scout_alternatives = arch_decision.get("alternatives", [selected])

    primary = _build_architecture_proposal(selected, task_type, num_rows, num_cols, imbalance_ratio)
    alternatives = [
        _build_architecture_proposal(alt, task_type, num_rows, num_cols, imbalance_ratio)
        for alt in scout_alternatives
        if alt != selected
    ]
    if not alternatives:
        alt_names = [a for a in _ARCHITECTURE_KNOWLEDGE if a != selected]
        alternatives = [
            _build_architecture_proposal(a, task_type, num_rows, num_cols, imbalance_ratio)
            for a in alt_names[:2]
        ]

    pipeline = _build_preprocessing_pipeline(reasoning, mission_brief)

    hp_strategy = _HYPERPARAMETER_STRATEGIES.get(selected, _HYPERPARAMETER_STRATEGIES["lightgbm"])

    budget = _estimate_budget(selected, num_rows, num_cols)

    fallback = _FALLBACK_PLANS.get(selected, "Fallback to LightGBM with default configuration")

    # ── Incorporate enriched reasoning (Stage 1) ────────────────────────
    feature_eng = reasoning.get("feature_engineering", {})
    outlier_strat = reasoning.get("outliers", {})

    extra_notes = []
    if isinstance(feature_eng, dict) and feature_eng.get("recommendations"):
        extra_notes.extend(feature_eng["recommendations"][:2])
    if isinstance(outlier_strat, dict) and outlier_strat.get("selected", "none") != "none":
        extra_notes.append(f"Outlier strategy: {outlier_strat['selected']}")

    # ── Query experience memory for similar past problems (Stage 3) ────
    _use_experience = False
    _exp_query_best = None
    _exp_query_conf = None
    try:
        from memory.collections.experience_memory import (
            query_best_pipeline as _exp_query_best,
            query_architecture_confidence as _exp_query_conf,
        )

        # Quick availability check without blocking
        import socket

        _host = os.environ.get("CHROMA_HOST", "localhost")
        _port = int(os.environ.get("CHROMA_PORT", 8000))
        _sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _sock.settimeout(1.0)
        _use_experience = _sock.connect_ex((_host, _port)) == 0
        _sock.close()
    except Exception:
        _use_experience = False

    if _use_experience:
        try:
            past_successes = _exp_query_best(
                modality=modality,
                task_type=task_type,
                num_rows=num_rows,
                num_columns=num_cols,
                k=3,
            )
            if past_successes:
                best_arch = past_successes[0].get("architecture", "")
                best_metric = past_successes[0].get("achieved_metric")
                arch_conf = _exp_query_conf(selected, modality, task_type)
                extra_notes.append(
                    f"Past successful architecture for similar problems: {best_arch} "
                    f"(best metric: {best_metric:.4f})"
                )
                if arch_conf.get("total_jobs", 0) >= 3:
                    pass_ratio = arch_conf.get("pass_ratio", 0)
                    avg_metric = arch_conf.get("avg_metric")
                    extra_notes.append(
                        f"{selected} historical pass ratio: {pass_ratio:.0%} "
                        f"over {arch_conf['total_jobs']} jobs"
                    )
                    if avg_metric is not None:
                        extra_notes.append(f"{selected} historical avg metric: {avg_metric:.4f}")

            # Check alternatives' historical performance
            for alt in alternatives:
                alt_name = alt.get("name", "")
                if alt_name:
                    alt_conf = _exp_query_conf(alt_name, modality, task_type)
                    if (
                        alt_conf.get("total_jobs", 0) >= 2
                        and alt_conf.get("avg_metric") is not None
                    ):
                        extra_notes.append(
                            f"{alt_name} historical avg: {alt_conf['avg_metric']:.4f} "
                            f"(pass rate: {alt_conf.get('pass_ratio', 0):.0%})"
                        )
        except Exception as exc:
            logger.debug(f"Experience memory query failed (non-fatal): {exc}")

    plan = EngineeringPlan(
        architecture_selected=primary,
        alternatives=alternatives,
        preprocessing_pipeline=pipeline,
        hyperparameter_strategy=hp_strategy,
        computational_budget=budget,
        fallback_plan=fallback,
        feature_engineering_notes=extra_notes,
    )
    return plan.model_dump()


def _build_architecture_proposal(
    arch: str, task_type: str, num_rows: int, num_cols: int, imbalance_ratio: float | None
) -> ArchitectureProposal:
    knowledge = _ARCHITECTURE_KNOWLEDGE.get(arch, _ARCHITECTURE_KNOWLEDGE["lightgbm"])
    metric_range = _estimate_metric_range(arch, task_type, num_rows, imbalance_ratio)
    training_minutes = _estimate_training_minutes(arch, num_rows, num_cols)
    ram_mb = _estimate_ram_mb(arch, num_rows)

    reason_for_selection = _build_selection_reason(arch, task_type, num_rows, metric_range)

    return ArchitectureProposal(
        name=arch,
        pros=knowledge["pros"],
        cons=knowledge["cons"],
        expected_training_minutes=training_minutes,
        expected_ram_mb=ram_mb,
        expected_metric_range=metric_range,
        reason_for_selection=reason_for_selection,
    )


def _estimate_training_minutes(arch: str, num_rows: int, num_cols: int) -> int:
    knowledge = _ARCHITECTURE_KNOWLEDGE.get(arch, _ARCHITECTURE_KNOWLEDGE["lightgbm"])
    minutes = knowledge["base_training_minutes"] + knowledge["training_time_per_row"] * num_rows
    col_factor = 1.0 + (num_cols - 10) * 0.02 if num_cols > 10 else 1.0
    return max(1, int(round(minutes * col_factor)))


def _estimate_ram_mb(arch: str, num_rows: int) -> int:
    knowledge = _ARCHITECTURE_KNOWLEDGE.get(arch, _ARCHITECTURE_KNOWLEDGE["lightgbm"])
    ram = knowledge["base_ram_mb"] + knowledge["ram_per_row"] * num_rows
    return max(knowledge["base_ram_mb"], int(round(ram)))


def _estimate_metric_range(
    arch: str, task_type: str, num_rows: int, imbalance_ratio: float | None
) -> list[float] | None:
    arch_estimates = _ACCURACY_ESTIMATES.get(arch, {})
    task_estimates = arch_estimates.get(task_type, arch_estimates.get("classification", []))
    low, high = 0.5, 0.85
    for lo, hi, lo_val, hi_val in task_estimates:
        if lo <= num_rows < hi:
            low, high = lo_val, hi_val
            break
    if imbalance_ratio and imbalance_ratio > 10:
        low = round(low - 0.08, 2)
        high = round(high - 0.05, 2)
    return [low, high]


def _build_selection_reason(
    arch: str, task_type: str, num_rows: int, metric_range: list[float] | None
) -> str:
    knowledge = _ARCHITECTURE_KNOWLEDGE.get(arch, _ARCHITECTURE_KNOWLEDGE["lightgbm"])
    reason_parts = [f"{arch} selected for {task_type} task with {num_rows} rows"]
    if metric_range:
        reason_parts.append(f"expected metric range [{metric_range[0]:.2f}, {metric_range[1]:.2f}]")
    has_gpu = knowledge.get("gpu", False)
    if has_gpu:
        reason_parts.append("GPU recommended")
    reason_parts.append(knowledge["pros"][0].lower())
    return "; ".join(reason_parts)


def _build_preprocessing_pipeline(
    reasoning: dict[str, Any], mission_brief: dict[str, Any]
) -> list[dict[str, Any]]:
    prep_decision = reasoning.get("preprocessing", {})
    selected_str = prep_decision.get("selected", "passthrough")

    if selected_str == "passthrough":
        return [{"name": "passthrough", "rationale": "No preprocessing needed", "library": "none"}]

    # Convert Scout's " -> " joined pipeline to steps
    step_names = [s.strip() for s in selected_str.split("->")]
    steps = []
    for name in step_names:
        if name in _SCOUT_TO_PIPELINE:
            steps.append(_SCOUT_TO_PIPELINE[name])
        elif name:
            steps.append(PreprocessingStep(name=name, rationale=f"Apply {name}", library="sklearn"))

    return [s.model_dump() for s in steps]


def _estimate_budget(arch: str, num_rows: int, num_cols: int) -> ComputationalBudget:
    knowledge = _ARCHITECTURE_KNOWLEDGE.get(arch, _ARCHITECTURE_KNOWLEDGE["lightgbm"])
    training_minutes = _estimate_training_minutes(arch, num_rows, num_cols)
    ram_mb = _estimate_ram_mb(arch, num_rows)
    disk_mb = knowledge["disk_mb"]
    return ComputationalBudget(
        estimated_training_minutes=training_minutes,
        estimated_ram_mb=ram_mb,
        expected_disk_mb=disk_mb,
        gpu_required=knowledge["gpu"],
    )


def format_plan_summary(plan: dict[str, Any]) -> str:
    lines = []
    arch = plan.get("architecture_selected", {})
    lines.append(f"Architecture: {arch.get('name', 'unknown')}")
    lines.append(f"  Expected training time: ~{arch.get('expected_training_minutes', '?')} min")
    lines.append(f"  Expected peak memory: ~{arch.get('expected_ram_mb', '?')} MB")
    mr = arch.get("expected_metric_range")
    if mr:
        lines.append(f"  Expected metric range: [{mr[0]:.2f}, {mr[1]:.2f}]")

    pipeline = plan.get("preprocessing_pipeline", [])
    if pipeline:
        step_names = [s.get("name", "?") for s in pipeline]
        lines.append(f"  Preprocessing: {' -> '.join(step_names)}")

    hp = plan.get("hyperparameter_strategy", {})
    lines.append(f"  Tuning: {hp.get('approach', 'manual')} ({hp.get('max_trials', 1)} trials)")

    budget = plan.get("computational_budget", {})
    if budget.get("gpu_required"):
        lines.append("  GPU: required")

    alt = plan.get("alternatives", [])
    if alt:
        alt_names = [a.get("name", "?") for a in alt[:2]]
        lines.append(f"  Alternatives: {', '.join(alt_names)}")

    return "\n".join(lines)


def format_script_header_comment(plan_summary: str) -> str:
    return f"\nDesign Summary:\n{plan_summary}\n"

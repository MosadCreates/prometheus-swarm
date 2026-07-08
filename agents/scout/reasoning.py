"""
Scout Engineering Reasoning Engine.

Each function is pure, deterministic, and independently unit-testable.
No LLM calls, no Redis, no file I/O beyond the DataFrame parameter.

Each returns a dict matching EngineeringDecision fields:
    title, rationale, confidence, alternatives, selected
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_CLASSIFICATION_KEYWORDS = [
    "classify",
    "classification",
    "detect",
    "predict category",
    "binary",
    "multiclass",
    "spam",
    "fraud",
    "churn",
    "survived",
    "convert",
    "yes/no",
    "true/false",
    "0/1",
]
_REGRESSION_KEYWORDS = [
    "regression",
    "predict value",
    "forecast",
    "estimate",
    "continuous",
    "price",
    "sales",
    "temperature",
    "amount",
]
_TIME_INDICATORS = ["date", "time", "timestamp", "year", "month", "dayofweek"]
_ID_INDICATORS = ["id", "uuid", "key", "code", "identifier"]


def _load_target_column(df, target_column: str | None):
    if target_column and target_column in df.columns:
        return df[target_column].dropna()
    return None


def reason_problem_type(
    problem_description: str,
    df: "pd.DataFrame",
    target_column: str | None = None,
) -> dict[str, Any]:
    target = _load_target_column(df, target_column)
    desc_lower = problem_description.lower()

    class_count = target.nunique() if target is not None else None

    # Determine task type from data first, then description for confidence
    is_classification = False
    is_regression = False

    if target is not None:
        if class_count == 2:
            is_classification = True
        elif class_count is not None and class_count <= 20:
            is_classification = True
        elif class_count is not None and class_count > 20:
            if target.dtype.kind in ("i", "u", "f"):
                is_regression = True
            else:
                is_classification = True

    # Use description keywords to boost confidence
    cls_matches = sum(1 for kw in _CLASSIFICATION_KEYWORDS if kw in desc_lower)
    reg_matches = sum(1 for kw in _REGRESSION_KEYWORDS if kw in desc_lower)

    if is_classification and cls_matches > 0:
        selected = "classification"
        confidence = 0.95
        rationale = (
            f"Target has {class_count} unique values and description mentions classification"
        )
    elif is_classification:
        selected = "classification"
        confidence = 0.85
        rationale = f"Target has {class_count} unique values"
    elif is_regression and reg_matches > 0:
        selected = "regression"
        confidence = 0.92
        rationale = "Target is numeric with many unique values and description mentions regression"
    elif is_regression:
        selected = "regression"
        confidence = 0.80
        rationale = "Target is continuous numeric with many unique values"
    elif cls_matches > reg_matches:
        selected = "classification"
        confidence = 0.70
        rationale = "Problem description suggests classification"
    elif reg_matches > cls_matches:
        selected = "regression"
        confidence = 0.70
        rationale = "Problem description suggests regression"
    else:
        selected = "classification"
        confidence = 0.60
        rationale = "Could not determine task type from data; defaulting to classification"

    alternatives = ["regression", "classification"]
    if selected == "classification":
        alternatives = ["classification", "regression"]

    return {
        "title": "Problem Type Identification",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": alternatives,
        "selected": selected,
    }


def reason_data_quality(eda_result: dict[str, Any]) -> dict[str, Any]:
    warnings = eda_result.get("data_warnings", [])
    missing_rate = eda_result.get("missing_value_rate", {})
    high_card = eda_result.get("high_cardinality_columns", [])

    missing_values = [c for c, r in missing_rate.items() if r > 0]
    high_missing = [c for c, r in missing_rate.items() if r > 0.3]

    issues = []
    if high_missing:
        issues.append(f"high_missing_rate({len(high_missing)} cols)")
    if high_card:
        issues.append(f"high_cardinality({len(high_card)} cols)")
    if warnings:
        issues.append(f"{len(warnings)} warnings")

    if not issues:
        confidence = 0.95
        rationale = "No significant data quality issues detected"
        selected = "clean"
    elif len(issues) == 1:
        confidence = 0.75
        rationale = f"Minor data quality issue: {issues[0]}"
        selected = "acceptable"
    elif len(issues) == 2:
        confidence = 0.60
        rationale = f"Moderate data quality issues: {', '.join(issues)}"
        selected = "needs_attention"
    else:
        confidence = 0.40
        rationale = f"Significant data quality issues: {', '.join(issues)}"
        selected = "needs_cleanup"

    return {
        "title": "Data Quality Assessment",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": ["clean", "acceptable", "needs_attention", "needs_cleanup"],
        "selected": selected,
    }


def reason_leakage(
    df: "pd.DataFrame",
    target_column: str | None = None,
) -> dict[str, Any]:
    import pandas as pd

    if not target_column or target_column not in df.columns:
        return {
            "title": "Leakage Detection",
            "rationale": "No target column specified; skipping leakage analysis",
            "confidence": 1.0,
            "alternatives": [],
            "selected": "no_analysis",
        }

    target = df[target_column].dropna()
    leak_sources = []
    col_lower = {c: c.lower() for c in df.columns}

    # Check for ID/UUID columns
    for col, lower in col_lower.items():
        if col == target_column:
            continue
        if any(ind in lower for ind in _ID_INDICATORS):
            leak_sources.append(f"'{col}' looks like an identifier column")

    # Check for time-based leakage
    for col, lower in col_lower.items():
        if col == target_column:
            continue
        if any(ti in lower for ti in _TIME_INDICATORS):
            if target.dtype.kind in ("i", "u", "f"):
                leak_sources.append(f"'{col}' may cause time-based leakage")

    # Check for near-perfect correlation with target
    numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns
    if target.dtype.kind in ("i", "u", "f") and len(numeric_cols) > 1:
        try:
            corr = df[numeric_cols].corrwith(target).dropna()
            high_corr = corr[corr.abs() > 0.95]
            for c in high_corr.index:
                if c != target_column:
                    leak_sources.append(f"'{c}' has {high_corr[c]:.2f} correlation with target")
        except Exception:
            pass

    if not leak_sources:
        return {
            "title": "Leakage Detection",
            "rationale": "No obvious leakage sources detected",
            "confidence": 0.90,
            "alternatives": [],
            "selected": "no_leakage_detected",
        }

    return {
        "title": "Leakage Detection",
        "rationale": f"Potential leakage detected: {'; '.join(leak_sources[:3])}",
        "confidence": round(max(0.3, 1.0 - len(leak_sources) * 0.15), 2),
        "alternatives": ["drop_leaky_columns", "exclude_before_splitting"],
        "selected": "flag_for_review",
    }


def reason_preprocessing(df: "pd.DataFrame") -> dict[str, Any]:
    numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    text_cols = []
    for c in df.select_dtypes(include=["object"]).columns:
        avg_len = df[c].dropna().astype(str).str.len().mean()
        if avg_len > 50:
            text_cols.append(c)
            if c in categorical_cols:
                categorical_cols.remove(c)

    steps = []
    if any(df[c].isna().any() for c in numeric_cols):
        steps.append("median_imputation_numeric")
    if any(df[c].isna().any() for c in categorical_cols):
        steps.append("mode_imputation_categorical")
    if categorical_cols:
        steps.append("ordinal_encoding")
    if len(numeric_cols) > 1:
        ranges = [df[c].max() - df[c].min() for c in numeric_cols if df[c].min() != df[c].max()]
        if ranges and max(ranges) > 10 * min(ranges):
            steps.append("standard_scaling")
    if text_cols:
        steps.append("tfidf_vectorization")

    selected = " -> ".join(steps) if steps else "passthrough"
    rationale = f"Pipeline: {selected}" if steps else "No preprocessing needed"

    return {
        "title": "Preprocessing Strategy",
        "rationale": rationale,
        "confidence": 0.88,
        "alternatives": [
            "passthrough",
            "median_imputation + ordinal_encode",
            "knn_imputation + onehot_encode + robust_scaler",
        ],
        "selected": selected,
    }


def reason_imbalance(eda_result: dict[str, Any]) -> dict[str, Any] | None:
    ratio = eda_result.get("class_imbalance_ratio")
    if ratio is None:
        return None

    if ratio > 20:
        confidence = 0.90
        selected = "smote"
        rationale = f"Severe imbalance (ratio={ratio:.1f}:1); SMOTE recommended to generate synthetic minority samples"
    elif ratio > 5:
        confidence = 0.85
        selected = "class_weight"
        rationale = (
            f"Moderate imbalance (ratio={ratio:.1f}:1); class weighting adjusts loss function"
        )
    elif ratio > 3:
        confidence = 0.75
        selected = "focal_loss"
        rationale = f"Mild imbalance (ratio={ratio:.1f}:1); focal loss down-weights easy examples"
    else:
        return None

    return {
        "title": "Class Imbalance Strategy",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": ["none", "class_weight", "smote", "focal_loss"],
        "selected": selected,
    }


def reason_architecture(mission_brief: dict[str, Any]) -> dict[str, Any]:
    modality = mission_brief.get("modality", "tabular")
    task_type = mission_brief.get("task_type", "classification")
    num_rows = mission_brief.get("dataset", {}).get("num_rows", 0)
    imbalance_ratio = mission_brief.get("data_quality", {}).get("class_imbalance_ratio")

    if modality == "tabular":
        if num_rows < 1_000_000:
            primary = "lightgbm"
            fallbacks = ["xgboost"]
            rationale = f"Tabular data with {num_rows} rows; LightGBM is fast and handles mixed data types well"
        else:
            primary = "tabnet"
            fallbacks = ["lightgbm", "xgboost"]
            rationale = (
                f"Large tabular dataset ({num_rows} rows); TabNet handles complex interactions"
            )
    elif modality == "text":
        primary = "distilbert"
        fallbacks = ["lightgbm_with_tfidf"]
        rationale = "Text modality; DistilBERT provides efficient transformer-based classification"
    elif modality == "image":
        primary = "efficientnet"
        fallbacks = ["resnet"]
        rationale = "Image modality; EfficientNet-B0 balances accuracy and compute"
    else:
        primary = "lightgbm"
        fallbacks = ["xgboost"]
        rationale = "Unknown modality; defaulting to LightGBM"

    if imbalance_ratio and imbalance_ratio > 20:
        rationale += (
            f" with class imbalance (ratio={imbalance_ratio:.1f}); SMOTE pre-sampling recommended"
        )

    return {
        "title": "Architecture Selection",
        "rationale": rationale,
        "confidence": 0.85,
        "alternatives": [primary] + fallbacks,
        "selected": primary,
    }


def reason_validation(
    task_type: str,
    num_rows: int,
    class_imbalance_ratio: float | None = None,
) -> dict[str, Any]:
    if num_rows < 500:
        selected = "stratified_5fold"
        confidence = 0.90
        rationale = f"Small dataset ({num_rows} rows); stratified 5-fold cross-validation maximizes sample usage"
    elif num_rows < 5000:
        if class_imbalance_ratio and class_imbalance_ratio > 3:
            selected = "stratified_5fold"
            confidence = 0.88
            rationale = f"Moderate dataset ({num_rows} rows) with imbalance; stratified folds preserve class distribution"
        else:
            selected = "stratified_5fold"
            confidence = 0.85
            rationale = f"Moderate dataset ({num_rows} rows); stratified 5-fold cross-validation"
    elif num_rows < 50000:
        selected = "stratified_kfold"
        confidence = 0.80
        rationale = f"Large dataset ({num_rows} rows); 3-fold cross-validation balances speed and reliability"
    else:
        selected = "train_val_split"
        confidence = 0.75
        rationale = f"Very large dataset ({num_rows} rows); single train/val split sufficient"

    if class_imbalance_ratio and class_imbalance_ratio > 10:
        selected = selected.replace("5fold", "3fold") if "5fold" in selected else selected
        rationale += " with stratified sampling due to class imbalance"
        confidence = round(confidence - 0.05, 2)

    return {
        "title": "Validation Strategy",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": ["train_val_split", "stratified_5fold", "stratified_3fold", "kfold"],
        "selected": selected,
    }


def reason_feature_engineering(
    df: "pd.DataFrame",
    target_column: str | None = None,
) -> dict[str, Any]:
    """Analyse features and recommend engineering strategies.

    Examines existing features for transformation needs, interaction potential,
    and suggests new feature candidates based on data patterns.
    """
    numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
    categorical_cols = df.select_dtypes(include=["object", "category"]).columns.tolist()
    text_cols = []
    for c in df.select_dtypes(include=["object"]).columns:
        if df[c].dropna().astype(str).str.len().mean() > 50:
            text_cols.append(c)
            if c in categorical_cols:
                categorical_cols.remove(c)

    recs = []
    if text_cols:
        recs.append(f"Apply TF-IDF vectorization to {len(text_cols)} text column(s)")
    for col in numeric_cols:
        if col == target_column:
            continue
        s = df[col].dropna()
        if len(s) < 2:
            continue
        skew = s.skew()
        if abs(skew) > 2:
            recs.append(
                f"Consider log or Box-Cox transform for skewed column: '{col}' (skew={skew:.1f})"
            )
        min_val, max_val = s.min(), s.max()
        if max_val > 1e6 or min_val < -1e6:
            recs.append(
                f"Consider scaling for wide-range column: '{col}' range=[{min_val:.0f}, {max_val:.0f}]"
            )
        zero_frac = (s == 0).mean()
        if zero_frac > 0.5:
            recs.append(
                f"Column '{col}' has {zero_frac:.0%} zeros; consider indicator feature or imputation"
            )

    for col in categorical_cols:
        n_unique = df[col].nunique()
        if n_unique > 20:
            recs.append(
                f"High-cardinality categorical '{col}' ({n_unique} values); consider target encoding or feature hashing"
            )

    if len(numeric_cols) > 1 and target_column and target_column in df.columns:
        target = df[target_column].dropna()
        if target.dtype.kind in ("i", "u", "f"):
            strong = []
            for col in numeric_cols:
                if col == target_column:
                    continue
                try:
                    corr = abs(float(df[col].corr(target)))
                    if corr > 0.5:
                        strong.append(col)
                except Exception:
                    pass
            if strong:
                recs.append(f"Strongly correlated features with target: {strong}")

    if not recs:
        selected = "no_feature_engineering_needed"
        rationale = "Features appear well-formed; no transformations recommended"
        confidence = 0.90
    elif len(recs) <= 2:
        selected = "minor_engineering"
        rationale = "; ".join(recs)
        confidence = 0.85
    else:
        selected = "significant_engineering"
        rationale = "; ".join(recs[:4])
        confidence = 0.75

    return {
        "title": "Feature Engineering Recommendations",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": ["no_feature_engineering_needed", "automated_feature_learning"],
        "selected": selected,
        "recommendations": recs[:5],
    }


def reason_outliers(eda_result: dict[str, Any]) -> dict[str, Any]:
    """Analyse outlier counts and recommend handling strategy.

    Reads outlier_counts from enhanced EDA to decide whether clipping,
    capping, or robust scaling is warranted.
    """
    outlier_counts = eda_result.get("outlier_counts", {})
    if not outlier_counts:
        return {
            "title": "Outlier Handling Strategy",
            "rationale": "No numeric columns with significant outliers detected",
            "confidence": 0.95,
            "alternatives": ["none", "iqr_clipping", "robust_scaling"],
            "selected": "none",
        }

    cols_with_outliers = [(c, int(v)) for c, v in outlier_counts.items() if int(v) > 0]
    if not cols_with_outliers:
        return {
            "title": "Outlier Handling Strategy",
            "rationale": "No significant outliers detected",
            "confidence": 0.95,
            "alternatives": ["none", "iqr_clipping", "robust_scaling"],
            "selected": "none",
        }

    total_outliers = sum(c[1] for c in cols_with_outliers)
    severity = "mild" if total_outliers < 20 else "moderate" if total_outliers < 100 else "severe"

    if severity == "severe":
        selected = "robust_scaling"
        confidence = 0.80
        rationale = f"{total_outliers} outliers across {len(cols_with_outliers)} columns; robust scaling recommended to reduce influence"
    elif severity == "moderate":
        selected = "iqr_clipping"
        confidence = 0.85
        rationale = f"{total_outliers} outliers across {len(cols_with_outliers)} columns; IQR-based clipping advised"
    else:
        selected = "none"
        confidence = 0.90
        rationale = (
            f"Minor outlier presence ({total_outliers} total); models should handle naturally"
        )

    return {
        "title": "Outlier Handling Strategy",
        "rationale": rationale,
        "confidence": round(confidence, 2),
        "alternatives": ["none", "iqr_clipping", "robust_scaling"],
        "selected": selected,
        "affected_columns": [c for c, _ in cols_with_outliers],
    }


def reason_risks(
    eda_result: dict[str, Any],
    problem_description: str = "",
) -> list[str]:
    risks = []
    warnings = eda_result.get("data_warnings", [])
    missing_rate = eda_result.get("missing_value_rate", {})
    imbalance = eda_result.get("class_imbalance_ratio")
    num_rows = eda_result.get("num_rows", 0)
    high_card = eda_result.get("high_cardinality_columns", [])

    if warnings:
        risks.extend(warnings[:3])

    high_missing = [c for c, r in missing_rate.items() if r > 0.3]
    if high_missing:
        risks.append(
            f"High missing rate (>30%) in {len(high_missing)} columns may degrade model quality"
        )

    if imbalance and imbalance > 20:
        risks.append(
            f"Severe class imbalance (ratio={imbalance:.1f}:1); model may ignore minority class"
        )
    elif imbalance and imbalance > 5:
        risks.append(
            f"Moderate class imbalance (ratio={imbalance:.1f}:1); consider using class weighting"
        )

    if num_rows < 100:
        risks.append(f"Very small dataset ({num_rows} rows); model may not generalize")

    if high_card and len(high_card) > 1:
        risks.append(
            f"Multiple high-cardinality columns ({len(high_card)}) may cause dimensionality issues"
        )

    desc_lower = problem_description.lower()
    if "real-time" in desc_lower or "low latency" in desc_lower:
        risks.append("Low-latency requirement may limit model complexity")
    if "limited data" in desc_lower or "small data" in desc_lower:
        risks.append("Data scarcity noted in problem description")

    return risks[:5]


def adjust_with_experience(
    decisions: dict[str, Any],
    experiences: list[dict[str, Any]],
    boost_threshold: float = 0.10,
    penalty_threshold: float = 0.20,
    boost_amount: float = 0.05,
    penalty_amount: float = 0.10,
) -> dict[str, Any]:
    """Adjust reasoning confidence based on historical experience accuracy.

    For each decision dict in the reasoning map, if similar past experiences exist:
      - If past predictions were accurate (avg prediction_error < boost_threshold):
        boost confidence by boost_amount (capped at 0.98).
      - If past predictions were inaccurate (avg prediction_error > penalty_threshold):
        reduce confidence by penalty_amount (floored at 0.40).
      - If no historical data or prediction_error is unknown: keep unchanged.

    Also adjusts architecture confidence upward if the architecture has a high
    historical pass_ratio, or downward if it has a high escalate_ratio.

    Args:
        decisions: The EngineeringReasoning dict (with keys like 'architecture',
            'problem_type', 'preprocessing', etc.). Each value is a dict with
            'confidence', 'selected', etc., or a list (risks).
        experiences: List of dicts from query_similar_experiences().
        boost_threshold: Max avg prediction error to trigger a boost (default 0.10).
        penalty_threshold: Min avg prediction error to trigger a penalty (default 0.20).
        boost_amount: Amount to boost confidence (default 0.05).
        penalty_amount: Amount to reduce confidence (default 0.10).

    Returns:
        Updated decisions dict with adjusted confidences.
    """
    if not experiences:
        return decisions

    # Filter to jobs that actually completed (have achieved_metric)
    completed = [e for e in experiences if e.get("achieved_metric") is not None]
    if not completed:
        return decisions

    errors = [e["prediction_error"] for e in completed if e.get("prediction_error") is not None]
    avg_error = sum(errors) / len(errors) if errors else None

    pass_outcomes = [e for e in completed if e.get("outcome") == "pass"]
    fail_outcomes = [e for e in completed if e.get("outcome") in ("retry", "escalate")]

    for key, decision in decisions.items():
        if not isinstance(decision, dict) or "confidence" not in decision:
            continue

        conf = decision["confidence"]

        if key == "architecture":
            arch = decision.get("selected", "")
            arch_experiences = [e for e in completed if e.get("architecture") == arch]
            if arch_experiences:
                arch_errors = [
                    e["prediction_error"]
                    for e in arch_experiences
                    if e.get("prediction_error") is not None
                ]
                arch_avg_error = sum(arch_errors) / len(arch_errors) if arch_errors else avg_error
                arch_passes = len([e for e in arch_experiences if e.get("outcome") == "pass"])
                arch_total = len(arch_experiences)

                if arch_avg_error is not None and arch_avg_error < boost_threshold:
                    conf = min(0.98, conf + boost_amount)
                elif arch_avg_error is not None and arch_avg_error > penalty_threshold:
                    conf = max(0.40, conf - penalty_amount)

                if arch_total >= 3 and arch_passes / arch_total > 0.8:
                    conf = min(0.98, conf + 0.03)

        if avg_error is not None:
            if avg_error < boost_threshold and key != "architecture":
                conf = min(0.98, conf + boost_amount)
            elif avg_error > penalty_threshold and key != "architecture":
                conf = max(0.40, conf - penalty_amount)

        decisions[key]["confidence"] = round(conf, 2)

    # Recompute overall_confidence
    confs = [
        d["confidence"] for d in decisions.values() if isinstance(d, dict) and "confidence" in d
    ]
    if confs and "overall_confidence" in decisions:
        overall = sum(confs) / len(confs)
        if overall < 0.40:
            overall = 0.40
        decisions["overall_confidence"] = round(overall, 2)

    return decisions

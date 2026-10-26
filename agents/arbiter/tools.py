"""Arbiter tools — evaluation metrics and decision logic.

All functions accept data directly for testability. No file I/O in compute functions.
"""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_classification_metrics(
    y_true: list[float],
    y_pred: list[float],
    y_prob: list[float] | None = None,
) -> dict[str, float]:
    """Compute classification metrics: AUC, F1, precision, recall.

    Args:
        y_true: Ground truth labels (0 or 1)
        y_pred: Predicted labels (0 or 1)
        y_prob: Predicted probabilities (for AUC)

    Returns:
        dict with keys: auc_roc, f1, precision, recall, accuracy
    """
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
    )

    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)
    n_classes = max(len(np.unique(y_true_arr)), len(np.unique(y_pred_arr)))
    avg = "binary" if n_classes == 2 else "macro"

    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true_arr, y_pred_arr)),
        "f1": float(f1_score(y_true_arr, y_pred_arr, average=avg, zero_division=0)),
        "precision": float(precision_score(y_true_arr, y_pred_arr, average=avg, zero_division=0)),
        "recall": float(recall_score(y_true_arr, y_pred_arr, average=avg, zero_division=0)),
    }

    if y_prob is not None and n_classes > 1:
        try:
            if n_classes == 2:
                metrics["auc_roc"] = float(roc_auc_score(y_true_arr, y_prob))
            else:
                metrics["auc_roc"] = float(roc_auc_score(y_true_arr, y_prob, multi_class="ovr"))
        except Exception as e:
            logger.warning(f"AUC computation failed: {e}")
            metrics["auc_roc"] = 0.0
    else:
        metrics["auc_roc"] = 0.0

    # Dataset-relative AUC threshold (CLAUDE.md §3.5):
    # Imbalanced datasets have a higher random baseline.
    pos_ratio = float(np.mean(y_true_arr))
    neg_ratio = 1.0 - pos_ratio
    imbalance_ratio = max(pos_ratio, neg_ratio) / max(min(pos_ratio, neg_ratio), 0.001)
    metrics["threshold_auc"] = max(0.55, 0.80 - 0.03 * min(imbalance_ratio, 10.0))

    return metrics


def compute_regression_metrics(
    y_true: list,
    y_pred: list,
) -> dict[str, float]:
    """Compute regression metrics: RMSE, MAE, R².

    Threshold strategy: threshold_rmse = std(y_true) * 0.85
    (Model must beat naive mean prediction by >= 15%)

    Args:
        y_true: Ground truth values
        y_pred: Predicted values

    Returns:
        dict with keys: rmse, mae, r2, std_target, threshold_rmse
    """
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    y_true_arr = np.array(pd.to_numeric(y_true, errors="coerce"), dtype=float)
    y_pred_arr = np.array(pd.to_numeric(y_pred, errors="coerce"), dtype=float)

    mask = ~(np.isnan(y_true_arr) | np.isnan(y_pred_arr))
    y_true_arr = y_true_arr[mask]
    y_pred_arr = y_pred_arr[mask]
    if len(y_true_arr) == 0:
        return {
            "rmse": float("inf"),
            "mae": float("inf"),
            "r2": -float("inf"),
            "std_target": 1.0,
            "threshold_rmse": 0.85,
            "error": "All values NaN",
        }

    std_target = float(np.std(y_true_arr))
    rmse = float(np.sqrt(mean_squared_error(y_true_arr, y_pred_arr)))

    return {
        "rmse": rmse,
        "mae": float(mean_absolute_error(y_true_arr, y_pred_arr)),
        "r2": float(r2_score(y_true_arr, y_pred_arr)),
        "std_target": std_target,
        "threshold_rmse": std_target * 0.85,
    }


def make_decision(
    task_type: str,
    metrics: dict[str, float],
    crash_count: int = 0,
) -> tuple[str, str]:
    """Make PASS / RETRY / ESCALATE decision based on metrics.

    Args:
        task_type: "classification" or "regression"
        metrics: metrics dict from compute_*_metrics()
        crash_count: number of crashes during training

    Returns:
        (decision, reason) where decision is "pass", "retry", or "escalate"
    """
    if crash_count >= 3:
        return "escalate", f"Training had {crash_count} crashes. Escalating to human."

    if task_type == "classification":
        auc = metrics.get("auc_roc", 0.0)
        threshold = metrics.get("threshold_auc", 0.80)
        if auc >= threshold:
            return "pass", f"AUC={auc:.4f} >= threshold={threshold:.4f}. Model passes."
        elif auc >= threshold * 0.85:
            return (
                "retry",
                f"AUC={auc:.4f} within 15% of threshold={threshold:.4f}. Retry with new architecture.",
            )
        else:
            return (
                "escalate",
                f"AUC={auc:.4f} < {threshold * 0.85:.4f} (far below threshold={threshold:.4f}). Escalating.",
            )

    elif task_type == "regression":
        rmse = metrics.get("rmse", float("inf"))
        threshold = metrics.get("threshold_rmse", 0.0)
        if rmse <= threshold:
            return "pass", f"RMSE={rmse:.4f} <= threshold={threshold:.4f}. Model passes."
        elif rmse <= threshold * 1.15:
            return "retry", f"RMSE={rmse:.4f} within 15% of threshold={threshold:.4f}. Retry."
        else:
            return "escalate", f"RMSE={rmse:.4f} far above threshold={threshold:.4f}. Escalating."

    else:
        return "escalate", f"Unknown task type: {task_type}"


def generate_failure_analysis(
    metrics: dict[str, float],
    decision: str,
    reason: str,
) -> str:
    """Generate a human-readable failure analysis string."""
    lines = [
        "=== Arbiter Evaluation Report ===",
        f"Decision: {decision.upper()}",
        f"Reason: {reason}",
        "",
        "Metrics:",
    ]
    for key, value in metrics.items():
        if isinstance(value, float):
            lines.append(f"  {key}: {value:.4f}")
        else:
            lines.append(f"  {key}: {value}")

    return "\n".join(lines)


def _error_mask(
    y_true: list,
    y_pred: list,
    task_type: str,
    tol: float = 0.10,
) -> np.ndarray:
    """Per-row error indicator.

    Classification: mismatch between predicted and true label.
    Regression: relative absolute error exceeding ``tol`` (10% of the true value
    by default — robust to scale differences).
    """
    yt = np.asarray(y_true)
    yp = np.asarray(y_pred)
    if len(yt) == 0 or len(yt) != len(yp):
        return np.zeros(max(len(yt), len(yp)), dtype=bool)
    if task_type == "regression":
        scale = np.maximum(np.abs(yt), 1e-9)
        return np.abs(yp - yt) > tol * scale
    return (yp != yt).astype(bool)


def analyze_error_subset(
    X_test: pd.DataFrame | np.ndarray | list | None,
    y_true: list,
    y_pred: list,
    task_type: str = "classification",
    feature_names: list[str] | None = None,
    n_segments: int = 5,
    max_features: int = 6,
) -> dict[str, Any]:
    """Identify the subsets of data the model gets wrong.

    For each feature (up to ``max_features``) this segments the rows into
    ``n_segments`` bins (numeric) or per-value groups (categorical) and computes
    the error rate / mean error inside every segment. The highest-error segments
    are returned, ranked, with a one-line textual summary.

    When ``X_test`` is None (e.g. the training script did not save features),
    falls back to a label-level analysis: per-class error rates plus confidence
    buckets — still answers "which subset of data is the model weak on" without
    raw features.

    Args:
        X_test: Feature matrix (DataFrame, ndarray, or None).
        y_true: Ground-truth labels/values.
        y_pred: Model predictions.
        task_type: "classification" or "regression".
        feature_names: Column names for ndarray X_test.
        n_segments: Number of bins for numeric features.
        max_features: Cap on how many features to segment.

    Returns:
        dict with keys: has_features, segments (list of dicts: feature, segment,
        n_samples, n_errors, error_rate, mean_error), summary (one-line str),
        labels (per-class error rates when no features available).
    """
    err = _error_mask(y_true, y_pred, task_type)
    try:
        yp_arr = np.asarray(y_pred, dtype=float)
    except (ValueError, TypeError):
        yp_arr = np.zeros(len(y_pred), dtype=float)

    segments: list[dict[str, Any]] = []
    labels: list[dict[str, Any]] = []

    # ── Label-level view (always computed; primary when X absent) ─────────
    yt_arr = np.asarray(y_true)
    try:
        for label in np.unique(yt_arr):
            m = yt_arr == label
            if not np.any(m):
                continue
            seg_err = err[m]
            n = int(np.sum(m))
            labels.append(
                {
                    "label": str(label),
                    "n_samples": n,
                    "n_errors": int(np.sum(seg_err)),
                    "error_rate": round(float(np.mean(seg_err)), 4),
                }
            )
        labels.sort(key=lambda d: d["error_rate"], reverse=True)
    except Exception:
        labels = []

    if X_test is None:
        return {
            "has_features": False,
            "segments": [],
            "labels": labels,
            "summary": _build_error_summary(labels, has_features=False),
        }

    # ── Feature-level segmentation ────────────────────────────────────────
    try:
        X = X_test if isinstance(X_test, pd.DataFrame) else pd.DataFrame(np.asarray(X_test))
    except Exception as e:
        logger.warning(f"analyze_error_subset: cannot frame X_test: {e}")
        return {
            "has_features": False,
            "segments": [],
            "labels": labels,
            "summary": _build_error_summary(labels, has_features=False),
        }

    if feature_names and X.shape[1] == len(feature_names):
        X.columns = feature_names

    features = list(X.columns)[:max_features]
    for feature in features:
        try:
            col = X[feature].replace([np.inf, -np.inf], np.nan)
            segments.extend(
                _segment_feature(
                    col,
                    err,
                    yt_arr,
                    yp_arr,
                    feature_name=str(feature),
                    n_segments=n_segments,
                    task_type=task_type,
                )
            )
        except Exception as e:
            logger.debug(f"analyze_error_subset: skip {feature}: {e}")

    # Rank by error rate, keep the worst few across features.
    segments.sort(key=lambda d: d.get("error_rate", 0.0), reverse=True)
    top = segments[: max(6, max_features)]

    return {
        "has_features": True,
        "segments": top,
        "labels": labels,
        "summary": _build_error_summary(top, has_features=True),
    }


def _segment_feature(
    col: pd.Series,
    err: np.ndarray,
    yt_arr: np.ndarray,
    yp_arr: np.ndarray,
    feature_name: str,
    n_segments: int,
    task_type: str,
) -> list[dict[str, Any]]:
    """Segment one feature and return per-segment error stats."""
    if col.dtype.kind in "biufc":  # numeric
        numeric = pd.to_numeric(col, errors="coerce")
        n_unique = numeric.nunique(dropna=True)
        if n_unique <= n_segments:
            # Treat low-cardinality numeric as categorical groups
            return _group_segments(col.astype(str), err, yt_arr, yp_arr, feature_name, task_type)
        return _bin_segments(numeric, err, yt_arr, yp_arr, feature_name, n_segments, task_type)
    return _group_segments(col.astype(str), err, yt_arr, yp_arr, feature_name, task_type)


def _bin_segments(
    numeric: pd.Series,
    err: np.ndarray,
    yt_arr: np.ndarray,
    yp_arr: np.ndarray,
    feature_name: str,
    n_segments: int,
    task_type: str,
) -> list[dict[str, Any]]:
    if numeric.notna().sum() < n_segments:
        return []
    try:
        binned = pd.qcut(numeric, q=n_segments, duplicates="drop")
    except Exception:
        binned = pd.cut(numeric, bins=n_segments)
    codes = binned.cat.codes.to_numpy()  # -1 where NaN
    categories = binned.cat.categories
    out: list[dict[str, Any]] = []
    for code in np.unique(codes):
        if code < 0:
            continue
        mask = codes == code
        seg_err = err[mask]
        segment = _fmt_interval(categories[int(code)]) if int(code) < len(categories) else str(code)
        out.append(
            {
                "feature": feature_name,
                "segment": segment,
                "n_samples": int(seg_err.size),
                "n_errors": int(np.sum(seg_err)),
                "error_rate": round(float(np.mean(seg_err)), 4),
                "mean_error": round(float(np.mean(np.abs(yp_arr[mask] - yt_arr[mask]))), 4),
            }
        )
    return out


def _group_segments(
    col: pd.Series,
    err: np.ndarray,
    yt_arr: np.ndarray,
    yp_arr: np.ndarray,
    feature_name: str,
    task_type: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    counts = col.value_counts()
    for value, count in counts.head(15).items():
        mask = (col == value).to_numpy()
        seg_err = err[mask]
        out.append(
            {
                "feature": feature_name,
                "segment": str(value),
                "n_samples": int(count),
                "n_errors": int(np.sum(seg_err)),
                "error_rate": round(float(np.mean(seg_err)), 4),
                "mean_error": round(float(np.mean(np.abs(yp_arr[mask] - yt_arr[mask]))), 4),
            }
        )
    return out


def _fmt_interval(interval) -> str:
    """Human-readable segment label for a numeric bin."""
    try:
        if hasattr(interval, "left") and hasattr(interval, "right"):
            left, right = interval.left, interval.right
            if np.isinf(left) or np.isinf(right):
                return f"({_num(left)}, {_num(right)})"
            return f"{_num(left)} – {_num(right)}"
    except Exception:
        pass
    return str(interval)


def _num(v) -> str:
    try:
        f = float(v)
        return f"{f:.2f}"
    except Exception:
        return str(v)


def _build_error_summary(entries: list[dict[str, Any]], has_features: bool) -> str:
    """One-line summary of where errors concentrate."""
    if not entries:
        return "No error subset identified (all segments within tolerance)."
    worst = entries[0]
    n = worst.get("n_samples", 0)
    rate = worst.get("error_rate", 0.0)
    if rate <= 0.0:
        return "No error subset identified (all segments within tolerance)."
    if has_features:
        return (
            f"Errors concentrate in '{worst.get('feature')}' segment "
            f"'{worst.get('segment')}' — {rate * 100:.1f}% error over {n} samples."
        )
    return (
        f"Errors concentrate on label '{worst.get('label')}' — "
        f"{rate * 100:.1f}% error over {n} samples."
    )

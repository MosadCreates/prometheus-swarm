"""Arbiter tools — evaluation metrics and decision logic.

All functions accept data directly for testability. No file I/O in compute functions.
"""

import logging

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

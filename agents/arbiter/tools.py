"""Arbiter tools — evaluation metrics and decision logic.

All functions accept data directly for testability. No file I/O in compute functions.
"""

import logging

import numpy as np

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

    metrics: dict[str, float] = {
        "accuracy": float(accuracy_score(y_true_arr, y_pred_arr)),
        "f1": float(f1_score(y_true_arr, y_pred_arr, zero_division=0)),
        "precision": float(precision_score(y_true_arr, y_pred_arr, zero_division=0)),
        "recall": float(recall_score(y_true_arr, y_pred_arr, zero_division=0)),
    }

    if y_prob is not None and len(np.unique(y_true_arr)) > 1:
        try:
            metrics["auc_roc"] = float(roc_auc_score(y_true_arr, y_prob))
        except Exception as e:
            logger.warning(f"AUC computation failed: {e}")
            metrics["auc_roc"] = 0.0
    else:
        metrics["auc_roc"] = 0.0

    return metrics


def compute_regression_metrics(
    y_true: list[float],
    y_pred: list[float],
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

    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)

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
        if auc >= 0.80:
            return "pass", f"AUC={auc:.4f} >= 0.80. Model passes."
        elif auc >= 0.68:
            return (
                "retry",
                f"AUC={auc:.4f} < 0.80 but within 15% margin. Retry with new architecture.",
            )
        else:
            return "escalate", f"AUC={auc:.4f} < 0.68 (far below threshold). Escalating."

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

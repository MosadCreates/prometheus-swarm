"""Evaluation metrics computation. No CLI rendering, no file I/O beyond loading arrays."""

import logging
import os
from typing import Any

import numpy as np

from agents.arbiter.models import EvaluationResult

logger = logging.getLogger(__name__)


def load_checkpoint_data(
    job_id: str,
    checkpoint_dir: str | None = None,
) -> dict[str, Any]:
    """Load evaluation artifacts from the checkpoint directory.

    ALWAYS loads from y_test.npy (held-out test set).
    Never loads training data. Raises FileNotFoundError if test set is missing.

    Args:
        job_id: Job identifier.
        checkpoint_dir: Override directory. Defaults to outputs/{job_id}/checkpoints.

    Returns:
        dict with keys: y_true, y_pred, y_prob, checkpoint_path, num_samples
    """
    if checkpoint_dir is None:
        from runtime.paths import get_job_paths

        checkpoint_dir = str(get_job_paths(job_id).checkpoints_dir)

    checkpoint_path = os.path.join(checkpoint_dir, "best.ckpt")

    y_true_path = os.path.join(checkpoint_dir, "y_test.npy")
    y_pred_path = os.path.join(checkpoint_dir, "y_pred.npy")
    y_prob_path = os.path.join(checkpoint_dir, "y_prob.npy")

    # ── Guard: refuse to load training data ─────────────────────────────
    train_path = os.path.join(checkpoint_dir, "y_train.npy")
    if not os.path.exists(y_true_path) and os.path.exists(train_path):
        raise FileNotFoundError(
            f"Found y_train.npy but y_test.npy is missing at {y_true_path}. "
            "Arbiter must evaluate on held-out test set, never training data. "
            "Ensure the training script saves y_test.npy, y_pred.npy, and y_prob.npy."
        )

    if not os.path.exists(y_true_path):
        raise FileNotFoundError(
            f"Test labels not found at {y_true_path}. "
            "Ensure training completed and evaluation artifacts exist. "
            "Arbiter evaluates on held-out test set (y_test.npy), never training data."
        )
    if not os.path.exists(y_pred_path):
        raise FileNotFoundError(f"Predictions not found at {y_pred_path}.")

    y_true = np.load(y_true_path, allow_pickle=True)
    y_pred = np.load(y_pred_path, allow_pickle=True)
    y_prob = None
    if os.path.exists(y_prob_path):
        y_prob = np.load(y_prob_path, allow_pickle=True)

    return {
        "y_true": y_true.tolist(),
        "y_pred": y_pred.tolist(),
        "y_prob": y_prob.tolist() if y_prob is not None else None,
        "checkpoint_path": checkpoint_path,
        "num_samples": len(y_true),
    }


def compute_metrics(
    task_type: str,
    y_true: list,
    y_pred: list,
    y_prob: list | None = None,
) -> dict[str, float]:
    """Compute evaluation metrics using sklearn.

    Args:
        task_type: "classification" or "regression"
        y_true: Ground truth values
        y_pred: Predicted values
        y_prob: Predicted probabilities (classification only)

    Returns:
        dict of metric name to float value
    """
    if task_type == "classification":
        return _compute_classification_metrics(y_true, y_pred, y_prob)
    else:
        return _compute_regression_metrics(y_true, y_pred)


def _detect_pos_label(
    y_true: np.ndarray,
    y_prob: np.ndarray | None,
) -> str | int | None:
    """Detect the positive class label for binary classification.

    For numeric labels {0, 1}, returns None (sklearn default pos_label=1).
    For string labels, determines which label is positive by checking
    which class has higher mean predicted probability. Falls back to the
    second unique label if probabilities aren't available.
    """
    labels = np.unique(y_true)
    if len(labels) != 2:
        return None
    if np.issubdtype(y_true.dtype, np.number):
        return None
    if y_prob is not None:
        label_0 = labels[0]
        label_1 = labels[1]
        mean_prob_0 = float(np.mean(y_prob[y_true == label_0]))
        mean_prob_1 = float(np.mean(y_prob[y_true == label_1]))
        return str(label_1 if mean_prob_1 >= mean_prob_0 else label_0)
    return str(labels[1])


def _compute_classification_metrics(
    y_true: list,
    y_pred: list,
    y_prob: list | None = None,
) -> dict[str, float]:
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
        roc_auc_score,
        confusion_matrix,
    )

    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)
    n_classes = max(len(np.unique(y_true_arr)), len(np.unique(y_pred_arr)))
    avg = "binary" if n_classes == 2 else "macro"

    pos_label = _detect_pos_label(y_true_arr, np.array(y_prob) if y_prob is not None else None)

    binary_kwargs = {}
    if avg == "binary" and pos_label is not None:
        binary_kwargs["pos_label"] = pos_label

    try:
        accuracy = float(accuracy_score(y_true_arr, y_pred_arr))
    except Exception:
        accuracy = 0.0

    try:
        f1 = float(f1_score(y_true_arr, y_pred_arr, average=avg, zero_division=0, **binary_kwargs))
    except Exception:
        f1 = 0.0

    try:
        precision = float(
            precision_score(y_true_arr, y_pred_arr, average=avg, zero_division=0, **binary_kwargs)
        )
    except Exception:
        precision = 0.0

    try:
        recall = float(
            recall_score(y_true_arr, y_pred_arr, average=avg, zero_division=0, **binary_kwargs)
        )
    except Exception:
        recall = 0.0

    metrics: dict[str, float] = {
        "accuracy": accuracy,
        "f1": f1,
        "precision": precision,
        "recall": recall,
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

    try:
        cm = confusion_matrix(y_true_arr, y_pred_arr)
        metrics["confusion_matrix"] = cm.tolist()
    except Exception:
        pass

    return metrics


def _compute_regression_metrics(
    y_true: list,
    y_pred: list,
) -> dict[str, float]:
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

    y_true_arr = np.array(y_true, dtype=float)
    y_pred_arr = np.array(y_pred, dtype=float)

    mask = ~(np.isnan(y_true_arr) | np.isnan(y_pred_arr))
    y_true_arr = y_true_arr[mask]
    y_pred_arr = y_pred_arr[mask]

    if len(y_true_arr) == 0:
        return {
            "rmse": float("inf"),
            "mae": float("inf"),
            "r2": -float("inf"),
        }

    return {
        "rmse": float(np.sqrt(mean_squared_error(y_true_arr, y_pred_arr))),
        "mae": float(mean_absolute_error(y_true_arr, y_pred_arr)),
        "r2": float(r2_score(y_true_arr, y_pred_arr)),
    }


def evaluate(
    job_id: str,
    task_type: str = "classification",
    checkpoint_dir: str | None = None,
) -> EvaluationResult:
    """Load checkpoint data and compute metrics. Convenience wrapper.

    Args:
        job_id: Job identifier.
        task_type: "classification" or "regression"
        checkpoint_dir: Override checkpoint directory.

    Returns:
        EvaluationResult with computed metrics.

    Raises:
        FileNotFoundError: If evaluation artifacts are missing.
    """
    data = load_checkpoint_data(job_id, checkpoint_dir=checkpoint_dir)
    metrics = compute_metrics(
        task_type,
        data["y_true"],
        data["y_pred"],
        y_prob=data["y_prob"],
    )
    return EvaluationResult.from_metrics_dict(
        metrics=metrics,
        task_type=task_type,
        checkpoint_path=data["checkpoint_path"],
        num_samples=data["num_samples"],
    )

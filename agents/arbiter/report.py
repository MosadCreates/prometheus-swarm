"""Evaluation report writer. Saves structured evaluation results to disk."""

import csv
import json
import logging
import os

from agents.arbiter.models import (
    DecisionResult,
    EvaluationReport,
    EvaluationResult,
    MissionConstraints,
)
from runtime.retry_state import load_retry_state

logger = logging.getLogger(__name__)


def save_evaluation_report(
    job_id: str,
    evaluation_result: EvaluationResult,
    decision: DecisionResult,
    constraints: MissionConstraints,
    output_dir: str | None = None,
) -> str:
    """Save evaluation report to disk.

    Args:
        job_id: Job identifier.
        evaluation_result: Computed evaluation metrics and metadata.
        decision: Decision result with explanation.
        constraints: User-defined mission constraints.
        output_dir: Override output directory. Defaults to outputs/{job_id}.

    Returns:
        Path to the saved report file.
    """
    if output_dir is None:
        from runtime.paths import get_job_paths

        output_dir = str(get_job_paths(job_id).job_dir)

    os.makedirs(output_dir, exist_ok=True)

    report = EvaluationReport(
        job_id=job_id,
        metric=evaluation_result.metric,
        metric_value=evaluation_result.metric_value,
        threshold=constraints.threshold,
        decision=decision.decision,
        checkpoint_path=evaluation_result.checkpoint_path,
        explanation=decision.explanation,
        all_metrics=evaluation_result.all_metrics,
    )

    report_dict = report.to_dict()

    # Append retry history from persisted retry state if available
    retry_state = load_retry_state(job_id)
    if retry_state and retry_state.history:
        # Re-read existing report to merge history from prior attempts
        existing_path = os.path.join(output_dir, "evaluation_report.json")
        existing_history: list[dict] = []
        if os.path.exists(existing_path):
            try:
                with open(existing_path, encoding="utf-8") as f:
                    existing = json.load(f)
                existing_history = existing.get("retry_history", [])
            except (json.JSONDecodeError, FileNotFoundError):
                pass
        report_dict["retry_history"] = existing_history
        current_entry = {
            "attempt": retry_state.attempt_number,
            "metric_value": decision.metric_value,
            "metric_name": evaluation_result.metric,
            "decision": decision.decision,
            "architecture": retry_state.current_architecture,
        }
        if existing_history and existing_history[-1].get("attempt") == retry_state.attempt_number:
            existing_history[-1] = current_entry
        else:
            existing_history.append(current_entry)
        report_dict["retry_history"] = existing_history

    report_path = os.path.join(output_dir, "evaluation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_dict, f, indent=2)

    logger.info(f"[job={job_id}] Evaluation report saved to {report_path}")
    return report_path


def save_decision_report(
    job_id: str,
    decision: DecisionResult,
    output_dir: str | None = None,
) -> str:
    """Save just the decision summary to a separate JSON file.

    Args:
        job_id: Job identifier.
        decision: Decision result.
        output_dir: Override output directory.

    Returns:
        Path to the saved decision file.
    """
    if output_dir is None:
        from runtime.paths import get_job_paths

        output_dir = str(get_job_paths(job_id).job_dir)

    os.makedirs(output_dir, exist_ok=True)

    decision_path = os.path.join(output_dir, "decision.json")
    with open(decision_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "job_id": job_id,
                "decision": decision.decision,
                "metric_value": decision.metric_value,
                "threshold": decision.threshold,
                "explanation": decision.explanation,
            },
            f,
            indent=2,
        )

    logger.info(f"[job={job_id}] Decision report saved to {decision_path}")
    return decision_path


def save_metrics_csv(
    job_id: str,
    metrics: dict[str, float],
    output_dir: str | None = None,
) -> str:
    """Save all computed metrics as CSV.

    Args:
        job_id: Job identifier.
        metrics: Flat dict of metric names to float values.
        output_dir: Override output directory. Defaults to outputs/{job_id}.

    Returns:
        Path to the saved CSV file.
    """
    if output_dir is None:
        from runtime.paths import get_job_paths

        output_dir = str(get_job_paths(job_id).job_dir)

    os.makedirs(output_dir, exist_ok=True)

    csv_path = os.path.join(output_dir, "metrics.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value"])
        for key, value in sorted(metrics.items()):
            if isinstance(value, (int, float)):
                writer.writerow([key, value])

    logger.info(f"[job={job_id}] Metrics CSV saved to {csv_path}")
    return csv_path


def save_evaluation_plots(
    job_id: str,
    y_true: list,
    y_pred: list,
    y_prob: list | None = None,
    task_type: str = "classification",
    output_dir: str | None = None,
) -> list[str]:
    """Generate and save evaluation plots: confusion matrix, ROC curve, PR curve.

    Args:
        job_id: Job identifier.
        y_true: Ground truth labels.
        y_pred: Predicted labels.
        y_prob: Predicted probabilities (required for ROC/PR curves).
        task_type: "classification" or "regression".
        output_dir: Override output directory. Defaults to outputs/{job_id}/plots.

    Returns:
        List of paths to saved plot files (may be empty if plotting fails).
    """
    if output_dir is None:
        from runtime.paths import get_job_paths

        output_dir = str(get_job_paths(job_id).plots_dir)

    os.makedirs(output_dir, exist_ok=True)

    try:
        import io

        import numpy as np
        from matplotlib import pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping evaluation plots")
        return []

    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)

    saved_paths: list[str] = []

    try:
        plt.switch_backend("Agg")
    except Exception:
        pass

    # ── Confusion matrix (classification only) ─────────────────────────
    if task_type == "classification":
        try:
            from sklearn.metrics import ConfusionMatrixDisplay, confusion_matrix

            fig, ax = plt.subplots(figsize=(6, 5))
            cm = confusion_matrix(y_true_arr, y_pred_arr)
            ConfusionMatrixDisplay(cm).plot(ax=ax, cmap="Blues", values_format="d")
            ax.set_title(f"Confusion Matrix — {job_id}")
            fig.tight_layout()
            cm_path = os.path.join(output_dir, "confusion_matrix.png")
            fig.savefig(cm_path, dpi=150)
            plt.close(fig)
            saved_paths.append(cm_path)
            logger.info(f"[job={job_id}] Confusion matrix saved to {cm_path}")
        except Exception as e:
            logger.warning(f"[job={job_id}] Failed to save confusion matrix: {e}")

        # ── ROC curve ───────────────────────────────────────────────────
        if y_prob is not None:
            try:
                from sklearn.metrics import RocCurveDisplay, roc_curve

                n_classes = len(np.unique(y_true_arr))
                fig, ax = plt.subplots(figsize=(6, 5))

                if n_classes == 2:
                    fpr, tpr, _ = roc_curve(y_true_arr, y_prob)
                    ax.plot(fpr, tpr, label=f"ROC (AUC={_compute_auc(y_true_arr, y_prob):.3f})")
                else:
                    from sklearn.metrics import auc, roc_curve
                    from sklearn.preprocessing import label_binarize

                    classes = np.unique(y_true_arr)
                    y_bin = label_binarize(y_true_arr, classes=classes)
                    y_prob_arr = np.array(y_prob)
                    if y_prob_arr.ndim == 1:
                        y_prob_arr = np.column_stack([1 - y_prob_arr, y_prob_arr])
                    for i, c in enumerate(classes):
                        if i < y_prob_arr.shape[1]:
                            fpr, tpr, _ = roc_curve(y_bin[:, i], y_prob_arr[:, i])
                            ax.plot(fpr, tpr, label=f"Class {c} (AUC={auc(fpr, tpr):.3f})")

                ax.plot([0, 1], [0, 1], "k--", alpha=0.4)
                ax.set_xlabel("False Positive Rate")
                ax.set_ylabel("True Positive Rate")
                ax.set_title(f"ROC Curve — {job_id}")
                ax.legend(loc="lower right")
                fig.tight_layout()
                roc_path = os.path.join(output_dir, "roc_curve.png")
                fig.savefig(roc_path, dpi=150)
                plt.close(fig)
                saved_paths.append(roc_path)
                logger.info(f"[job={job_id}] ROC curve saved to {roc_path}")
            except Exception as e:
                logger.warning(f"[job={job_id}] Failed to save ROC curve: {e}")

        # ── Precision-Recall curve ─────────────────────────────────────
        if y_prob is not None:
            try:
                from sklearn.metrics import PrecisionRecallDisplay, precision_recall_curve

                n_classes = len(np.unique(y_true_arr))
                fig, ax = plt.subplots(figsize=(6, 5))

                if n_classes == 2:
                    prec, rec, _ = precision_recall_curve(y_true_arr, y_prob)
                    ax.plot(rec, prec, label=f"PR (AP={_compute_ap(y_true_arr, y_prob):.3f})")
                else:
                    from sklearn.metrics import average_precision_score
                    from sklearn.preprocessing import label_binarize

                    classes = np.unique(y_true_arr)
                    y_bin = label_binarize(y_true_arr, classes=classes)
                    y_prob_arr = np.array(y_prob)
                    if y_prob_arr.ndim == 1:
                        y_prob_arr = np.column_stack([1 - y_prob_arr, y_prob_arr])
                    for i, c in enumerate(classes):
                        if i < y_prob_arr.shape[1]:
                            prec, rec, _ = precision_recall_curve(y_bin[:, i], y_prob_arr[:, i])
                            ap = average_precision_score(y_bin[:, i], y_prob_arr[:, i])
                            ax.plot(rec, prec, label=f"Class {c} (AP={ap:.3f})")

                ax.set_xlabel("Recall")
                ax.set_ylabel("Precision")
                ax.set_title(f"PR Curve — {job_id}")
                ax.legend(loc="lower left")
                fig.tight_layout()
                pr_path = os.path.join(output_dir, "pr_curve.png")
                fig.savefig(pr_path, dpi=150)
                plt.close(fig)
                saved_paths.append(pr_path)
                logger.info(f"[job={job_id}] PR curve saved to {pr_path}")
            except Exception as e:
                logger.warning(f"[job={job_id}] Failed to save PR curve: {e}")

    return saved_paths


def _compute_auc(y_true, y_prob) -> float:
    """Safe AUC computation for plot annotations."""
    try:
        from sklearn.metrics import roc_auc_score

        return float(roc_auc_score(y_true, y_prob))
    except Exception:
        return 0.0


def _compute_ap(y_true, y_prob) -> float:
    """Safe average precision computation for plot annotations."""
    try:
        from sklearn.metrics import average_precision_score

        return float(average_precision_score(y_true, y_prob))
    except Exception:
        return 0.0

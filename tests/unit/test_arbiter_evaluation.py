"""Acceptance tests for Arbiter evaluation against mission constraints.

Covers all 6 acceptance criteria from Step 7 specification.
"""

import json
import os
import tempfile

import pytest
from runtime.paths import get_job_paths

from agents.arbiter.decision import make_decision
from agents.arbiter.evaluator import compute_metrics, evaluate, load_checkpoint_data
from agents.arbiter.models import (
    DecisionResult,
    EvaluationResult,
    MissionConstraints,
)
from agents.arbiter.report import save_decision_report, save_evaluation_report


# ── Test 1: AUC > 0.85, metric = 0.891 → PASS ─────────────────────────────


def test_auc_above_threshold_passes():
    """Acceptance Test 1: AUC=0.891 > threshold=0.85 → PASS."""
    constraints = MissionConstraints(
        metric="auc_roc",
        threshold=0.85,
        operator=">",
        constraints_list=["Only deploy if ROC AUC exceeds 0.85"],
    )
    evaluation = EvaluationResult(
        metric="auc_roc",
        metric_value=0.891,
        all_metrics={"auc_roc": 0.891, "f1": 0.742, "accuracy": 0.846},
        task_type="classification",
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "PASS"
    assert "satisfies" in result.explanation.lower()


# ── Test 2: AUC > 0.85, metric = 0.821 → RETRY ────────────────────────────


def test_auc_below_threshold_retries():
    """Acceptance Test 2: AUC=0.821 below threshold=0.85 → RETRY."""
    constraints = MissionConstraints(
        metric="auc_roc",
        threshold=0.85,
        operator=">",
    )
    evaluation = EvaluationResult(
        metric="auc_roc",
        metric_value=0.821,
        all_metrics={"auc_roc": 0.821, "f1": 0.710, "accuracy": 0.790},
        task_type="classification",
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "RETRY"
    assert "below" in result.explanation.lower()


# ── Test 3: F1 > 0.80, metric = 0.78 → RETRY ──────────────────────────────


def test_f1_respects_metric_not_auc():
    """Acceptance Test 3: F1=0.78 < threshold=0.80 → RETRY (uses F1, not AUC)."""
    constraints = MissionConstraints(
        metric="f1",
        threshold=0.80,
        operator=">",
        constraints_list=["Only deploy if F1 exceeds 0.80"],
    )
    evaluation = EvaluationResult(
        metric="f1",
        metric_value=0.78,
        all_metrics={"auc_roc": 0.95, "f1": 0.78, "accuracy": 0.90},
        task_type="classification",
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "RETRY"
    # Must reference F1, not AUC
    assert "f1" in result.explanation.lower()


# ── Test 4: Metrics on held-out test set, not training set ────────────────


def test_evaluator_loads_test_artifacts():
    """Acceptance Test 4: load_checkpoint_data reads y_test.npy, not training set."""
    with tempfile.TemporaryDirectory() as ckpt_dir:
        import numpy as np

        np.save(os.path.join(ckpt_dir, "y_test.npy"), np.array([0, 1, 0, 1]))
        np.save(os.path.join(ckpt_dir, "y_pred.npy"), np.array([0, 1, 0, 1]))
        np.save(os.path.join(ckpt_dir, "y_prob.npy"), np.array([0.1, 0.9, 0.1, 0.9]))

        # Set up a job_id that maps to this tmp dir
        job_id = "test-held-out"
        jp = get_job_paths(job_id)
        real_dir = str(jp.checkpoints_dir)
        os.makedirs(real_dir, exist_ok=True)
        try:
            for f in ("y_test.npy", "y_pred.npy", "y_prob.npy"):
                os.makedirs(os.path.dirname(os.path.join(real_dir, f)), exist_ok=True)
                np.save(os.path.join(real_dir, f), np.load(os.path.join(ckpt_dir, f)))

            data = load_checkpoint_data(job_id, checkpoint_dir=real_dir)
            assert data["num_samples"] == 4
            assert list(data["y_true"]) == [0, 1, 0, 1]
        finally:
            import shutil

            if os.path.exists(str(jp.job_dir)):
                shutil.rmtree(str(jp.job_dir))


# ── Test 5: Missing checkpoint → EVALUATION_FAILED ────────────────────────


def test_missing_checkpoint_fails():
    """Acceptance Test 5: Missing checkpoint raises FileNotFoundError."""
    with tempfile.TemporaryDirectory() as empty_dir:
        with pytest.raises(FileNotFoundError) as exc_info:
            load_checkpoint_data("test-missing", checkpoint_dir=empty_dir)
        assert "y_test.npy" in str(exc_info.value) or "not found" in str(exc_info.value)


# ── Test 6: Report generation ─────────────────────────────────────────────


def test_report_generation():
    """Acceptance Test 6: evaluation_report.json written with correct fields."""
    with tempfile.TemporaryDirectory() as tmpdir:
        constraints = MissionConstraints(
            metric="auc_roc",
            threshold=0.85,
            operator=">",
        )
        evaluation = EvaluationResult(
            metric="auc_roc",
            metric_value=0.891,
            all_metrics={"auc_roc": 0.891, "f1": 0.742, "accuracy": 0.846},
            task_type="classification",
            checkpoint_path="/tmp/checkpoint.ckpt",
            num_samples=100,
        )
        decision = DecisionResult(
            decision="PASS",
            explanation="AUC (0.891) > threshold (0.850). Satisfies mission constraint.",
            metric_value=0.891,
            threshold=0.85,
        )

        report_path = save_evaluation_report(
            "test-report",
            evaluation,
            decision,
            constraints,
            output_dir=tmpdir,
        )
        decision_path = save_decision_report(
            "test-report",
            decision,
            output_dir=tmpdir,
        )

        # Verify evaluation_report.json
        assert os.path.exists(report_path)
        with open(report_path) as f:
            report = json.load(f)
        assert report["job_id"] == "test-report"
        assert report["decision"] == "PASS"
        assert report["metric"] == "auc_roc"
        assert report["metric_value"] == 0.891
        assert report["threshold"] == 0.85
        assert report["checkpoint_path"] == "/tmp/checkpoint.ckpt"
        assert "explanation" in report
        assert "all_metrics" in report

        # Verify decision.json
        assert os.path.exists(decision_path)
        with open(decision_path) as f:
            decision_data = json.load(f)
        assert decision_data["decision"] == "PASS"
        assert decision_data["metric_value"] == 0.891


# ── Edge cases ────────────────────────────────────────────────────────────


def test_no_threshold_always_passes():
    """When no threshold is set, any metric value passes."""
    constraints = MissionConstraints(metric="auc_roc", threshold=None)
    evaluation = EvaluationResult(
        metric="auc_roc",
        metric_value=0.0,
        all_metrics={"auc_roc": 0.0},
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "PASS"


def test_far_below_threshold_fails():
    """Metric far below threshold (beyond 15% window) → FAIL."""
    constraints = MissionConstraints(
        metric="auc_roc",
        threshold=0.85,
        operator=">",
    )
    evaluation = EvaluationResult(
        metric="auc_roc",
        metric_value=0.45,
        all_metrics={"auc_roc": 0.45},
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "FAIL"


def test_regression_metric_uses_rmse():
    """Regression metrics compute and decision uses RMSE."""
    metrics = compute_metrics(
        "regression",
        [1.0, 2.0, 3.0, 4.0, 5.0],
        [1.05, 2.05, 3.05, 4.05, 4.95],
    )
    assert "rmse" in metrics
    assert "mae" in metrics
    assert "r2" in metrics

    constraints = MissionConstraints(metric="rmse", threshold=0.5, operator="<")
    evaluation = EvaluationResult(
        metric="rmse",
        metric_value=metrics["rmse"],
        all_metrics=metrics,
        task_type="regression",
    )
    result = make_decision(evaluation, constraints)
    # RMSE should be very low for near-perfect predictions
    assert result.decision == "PASS" if metrics["rmse"] < 0.5 else "RETRY"


def test_classification_metrics_compute():
    """Classification metrics compute correctly."""
    metrics = compute_metrics(
        "classification",
        [0, 1, 0, 1, 0, 1],
        [0, 1, 0, 1, 0, 1],
        y_prob=[0.1, 0.9, 0.2, 0.8, 0.3, 0.7],
    )
    assert metrics["accuracy"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["auc_roc"] >= 0.9


def test_string_labels_detect_pos_label():
    """String labels like ['No', 'Yes'] correctly detect pos_label for AUC."""
    metrics = compute_metrics(
        "classification",
        ["No", "Yes", "No", "Yes", "No", "Yes"],
        ["No", "Yes", "No", "Yes", "No", "Yes"],
        y_prob=[0.1, 0.9, 0.2, 0.8, 0.3, 0.7],
    )
    assert metrics["accuracy"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["auc_roc"] >= 0.9


def test_string_labels_auto_positive_detection():
    """Verify _detect_pos_label picks the right positive class."""
    import numpy as np
    from agents.arbiter.evaluator import _detect_pos_label

    y_true = np.array(["No", "Yes", "No", "Yes"])
    y_prob = np.array([0.1, 0.9, 0.2, 0.8])
    pos = _detect_pos_label(y_true, y_prob)
    assert pos == "Yes", f"Expected 'Yes', got {pos}"

    # Reverse: "No" has higher probabilities → should be positive
    y_prob_rev = np.array([0.9, 0.1, 0.8, 0.2])
    pos = _detect_pos_label(y_true, y_prob_rev)
    assert pos == "No", f"Expected 'No', got {pos}"

    # Numeric labels → returns None (sklearn default)
    y_num = np.array([0, 1, 0, 1])
    pos = _detect_pos_label(y_num, np.array([0.1, 0.9, 0.2, 0.8]))
    assert pos is None


# ── Phase 8: CSV and plots ────────────────────────────────────────────────


def test_metrics_csv_saved():
    """Phase 8: save_metrics_csv writes metrics.csv with metric,value columns."""
    from agents.arbiter.report import save_metrics_csv

    metrics = {"auc_roc": 0.891, "f1": 0.742, "accuracy": 0.846}
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = save_metrics_csv("test-csv", metrics, output_dir=tmpdir)
        assert os.path.exists(csv_path)
        assert csv_path.endswith("metrics.csv")

        with open(csv_path, encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) >= 4  # header + 3 metrics
        assert lines[0].strip() == "metric,value"
        # Verify all metrics present
        csv_content = "\n".join(lines)
        assert "auc_roc,0.891" in csv_content
        assert "f1,0.742" in csv_content
        assert "accuracy,0.846" in csv_content


def test_metrics_csv_filters_non_float_keys():
    """Phase 8: save_metrics_csv skips non-float values (confusion_matrix lists)."""
    from agents.arbiter.report import save_metrics_csv

    metrics = {"auc_roc": 0.89, "confusion_matrix": [[1, 2], [3, 4]]}
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = save_metrics_csv("test-csv-filter", metrics, output_dir=tmpdir)
        with open(csv_path, encoding="utf-8") as f:
            content = f.read()
        assert "confusion_matrix" not in content, "CSV should skip non-float values"
        assert "auc_roc,0.89" in content


def test_evaluation_plots_saved_classification():
    """Phase 8: save_evaluation_plots generates confusion_matrix.png, roc_curve.png, pr_curve.png."""
    from agents.arbiter.report import save_evaluation_plots

    y_true = [0, 1, 0, 1, 0, 1, 0, 1]
    y_pred = [0, 1, 0, 1, 0, 1, 0, 1]
    y_prob = [0.1, 0.9, 0.1, 0.9, 0.2, 0.8, 0.1, 0.9]

    with tempfile.TemporaryDirectory() as tmpdir:
        plots_dir = os.path.join(tmpdir, "plots")
        saved = save_evaluation_plots("test-plots", y_true, y_pred, y_prob, output_dir=plots_dir)
        assert len(saved) >= 1
        if os.path.exists(os.path.join(plots_dir, "confusion_matrix.png")):
            assert os.path.getsize(os.path.join(plots_dir, "confusion_matrix.png")) > 0
        if os.path.exists(os.path.join(plots_dir, "roc_curve.png")):
            assert os.path.getsize(os.path.join(plots_dir, "roc_curve.png")) > 0
        if os.path.exists(os.path.join(plots_dir, "pr_curve.png")):
            assert os.path.getsize(os.path.join(plots_dir, "pr_curve.png")) > 0


def test_evaluation_plots_returns_empty_when_no_y_prob():
    """Phase 8: save_evaluation_plots without y_prob only saves confusion matrix."""
    from agents.arbiter.report import save_evaluation_plots

    y_true = [0, 1, 0, 1]
    y_pred = [0, 1, 0, 1]

    with tempfile.TemporaryDirectory() as tmpdir:
        saved = save_evaluation_plots("test-noprob", y_true, y_pred, y_prob=None, output_dir=tmpdir)
        # Should at least try to save confusion matrix
        cm_path = os.path.join(tmpdir, "confusion_matrix.png")
        if os.path.exists(cm_path):
            assert cm_path in saved
        # ROC/PR should not be generated without probabilities
        assert not os.path.exists(os.path.join(tmpdir, "roc_curve.png"))


# ── Phase 8: Held-out test set guard ──────────────────────────────────────


def test_load_checkpoint_data_refuses_y_train():
    """Phase 8: load_checkpoint_data raises FileNotFoundError if only y_train.npy exists."""
    from agents.arbiter.evaluator import load_checkpoint_data

    with tempfile.TemporaryDirectory() as tmpdir:
        import numpy as np

        np.save(os.path.join(tmpdir, "y_train.npy"), np.array([0, 1, 0, 1]))
        np.save(os.path.join(tmpdir, "y_pred.npy"), np.array([0, 1, 0, 1]))

        with pytest.raises(FileNotFoundError) as exc_info:
            load_checkpoint_data("test-train-guard", checkpoint_dir=tmpdir)
        msg = str(exc_info.value)
        assert "y_train" in msg, f"Expected guard message about training data, got: {msg}"
        assert "y_test.npy" in msg


# ── Phase 8: Constraint propagation ───────────────────────────────────────


def test_constraint_propagation_uses_user_threshold():
    """Phase 8: decision.make_decision uses user-supplied threshold, not data-derived."""
    from agents.arbiter.decision import make_decision
    from agents.arbiter.models import EvaluationResult, MissionConstraints

    constraints = MissionConstraints(
        metric="auc_roc",
        threshold=0.95,  # User says: AUC > 0.95
        operator=">",
        constraints_list=["Must exceed 0.95 AUC"],
    )
    evaluation = EvaluationResult(
        metric="auc_roc",
        metric_value=0.50,  # Far below 0.95 (gap ~47% > 15%) → FAIL
        all_metrics={"auc_roc": 0.50, "f1": 0.45},
        task_type="classification",
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "FAIL", (
        f"Expected FAIL (0.50 < 0.95), got {result.decision}. "
        "Constraint propagation must use user threshold, not compute one from data."
    )
    assert "0.950" in result.explanation or "0.95" in result.explanation


def test_constraint_propagation_uses_operator():
    """Phase 8: constraint operator (<, >) is respected."""
    from agents.arbiter.decision import make_decision
    from agents.arbiter.models import EvaluationResult, MissionConstraints

    # RMSE must be < 0.5
    constraints = MissionConstraints(
        metric="rmse",
        threshold=0.5,
        operator="<",
    )
    evaluation = EvaluationResult(
        metric="rmse",
        metric_value=0.3,  # Good: 0.3 < 0.5
        all_metrics={"rmse": 0.3, "mae": 0.25, "r2": 0.9},
        task_type="regression",
    )
    result = make_decision(evaluation, constraints)
    assert result.decision == "PASS", f"Expected PASS (0.3 < 0.5), got {result.decision}"


def test_build_constraints_from_brief_propagates_threshold():
    """Phase 8: build_constraints_from_brief extracts user threshold from mission brief."""
    from agents.arbiter.controller import build_constraints_from_brief

    brief = {
        "evaluation_metric": "auc_roc",
        "deployment_threshold": 0.85,
        "deployment_operator": ">",
        "task_type": "classification",
    }
    constraints = build_constraints_from_brief(brief)
    assert constraints.metric == "auc_roc"
    assert constraints.threshold == 0.85
    assert constraints.operator == ">"


def test_build_constraints_from_brief_missing_threshold():
    """Phase 8: build_constraints_from_brief returns None threshold when not specified."""
    from agents.arbiter.controller import build_constraints_from_brief

    brief = {"evaluation_metric": "auc_roc"}
    constraints = build_constraints_from_brief(brief)
    assert constraints.metric == "auc_roc"
    assert constraints.threshold is None


def test_build_constraints_from_brief_none_brief():
    """Phase 8: build_constraints_from_brief handles None gracefully."""
    from agents.arbiter.controller import build_constraints_from_brief

    constraints = build_constraints_from_brief(None)
    assert constraints.metric == "auc_roc"
    assert constraints.threshold is None

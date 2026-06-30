"""Unit tests for Arbiter metrics computation and decision logic."""

from agents.arbiter.tools import (
    compute_classification_metrics,
    compute_regression_metrics,
    make_decision,
)


def test_classification_perfect():
    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1],
        y_pred=[0, 1, 0, 1],
        y_prob=[0.1, 0.9, 0.1, 0.9],
    )
    assert metrics["auc_roc"] >= 0.9
    assert metrics["f1"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0


def test_classification_worst():
    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1],
        y_pred=[1, 0, 1, 0],
        y_prob=[0.9, 0.1, 0.9, 0.1],
    )
    assert metrics["auc_roc"] < 0.3
    assert metrics["f1"] == 0.0


def test_classification_decision_pass():
    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1, 0, 1, 0, 1],
        y_pred=[0, 1, 0, 1, 0, 1, 0, 1],
        y_prob=[0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9],
    )
    decision, reason = make_decision("classification", metrics, crash_count=0)
    assert decision == "pass", f"Expected pass, got {decision}: {reason}"


def test_classification_decision_retry():
    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1, 0, 1, 0, 1],
        y_pred=[1, 0, 0, 1, 0, 1, 0, 1],
        y_prob=[0.55, 0.5, 0.6, 0.5, 0.3, 0.7, 0.4, 0.8],
    )
    decision, reason = make_decision("classification", metrics, crash_count=0)
    assert decision == "retry", f"Expected retry, got {decision}: {reason}"


def test_regression_metrics():
    metrics = compute_regression_metrics(
        y_true=[1.0, 2.0, 3.0, 4.0, 5.0],
        y_pred=[1.1, 2.2, 2.9, 4.1, 4.8],
    )
    assert "rmse" in metrics
    assert "mae" in metrics
    assert "r2" in metrics
    assert "std_target" in metrics
    assert "threshold_rmse" in metrics
    assert metrics["threshold_rmse"] == metrics["std_target"] * 0.85


def test_regression_decision_pass():
    metrics = compute_regression_metrics(
        y_true=[1.0, 2.0, 3.0, 4.0, 5.0],
        y_pred=[1.05, 2.05, 3.05, 4.05, 4.95],
    )
    decision, reason = make_decision("regression", metrics, crash_count=0)
    assert decision == "pass", f"Expected pass, got {decision}: {reason}"


def test_regression_decision_retry():
    metrics = compute_regression_metrics(
        y_true=[1.0, 2.0, 3.0, 4.0, 5.0],
        y_pred=[2.3, 3.3, 4.3, 5.3, 6.3],
    )
    decision, reason = make_decision("regression", metrics, crash_count=0)
    assert decision == "retry", f"Expected retry, got {decision}: {reason}"


def test_escalate_on_high_crash_count():
    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1],
        y_pred=[0, 0, 0, 1],
        y_prob=[0.1, 0.3, 0.1, 0.9],
    )
    decision, reason = make_decision("classification", metrics, crash_count=5)
    assert decision == "escalate", f"Expected escalate, got {decision}: {reason}"
    assert "crashes" in reason.lower()

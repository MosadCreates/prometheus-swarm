"""Pure decision engine. Compares metrics against user-supplied constraints.

No CLI rendering, no file I/O. Every decision includes an explanation.
"""

from agents.arbiter.models import DecisionResult, EvaluationResult, MissionConstraints


def make_decision(
    evaluation: EvaluationResult,
    constraints: MissionConstraints,
) -> DecisionResult:
    """Compare evaluation results against mission constraints.

    Rules:
        1. If constraints.threshold is None → PASS (no threshold to enforce)
        2. If metric value satisfies constraint operator → PASS
        3. If metric value is within 15% of threshold → RETRY
        4. Otherwise → FAIL

    Args:
        evaluation: Computed evaluation metrics.
        constraints: User-defined mission constraints from the brief.

    Returns:
        DecisionResult with decision string and explanation.
    """
    if not constraints.has_threshold:
        return DecisionResult(
            decision="PASS",
            explanation="No deployment threshold specified. Model passes by default.",
            metric_value=evaluation.metric_value,
            threshold=None,
        )

    value = evaluation.metric_value
    threshold = constraints.threshold
    assert threshold is not None

    metric_name = constraints.metric.upper() if constraints.metric else "METRIC"
    operator_symbol = constraints.operator

    if constraints.passes(value):
        return DecisionResult(
            decision="PASS",
            explanation=(
                f"{metric_name} ({value:.4f}) {operator_symbol} "
                f"threshold ({threshold:.4f}). Metric satisfies mission constraint."
            ),
            metric_value=value,
            threshold=threshold,
        )

    if constraints.within_retry_window(value):
        gap_pct = abs(value - threshold) / max(abs(threshold), 0.001) * 100
        return DecisionResult(
            decision="RETRY",
            explanation=(
                f"{metric_name} ({value:.4f}) is below required threshold "
                f"({threshold:.4f}, {operator_symbol}) by {gap_pct:.1f}%. "
                f"Within retry window. Consider retraining with different architecture."
            ),
            metric_value=value,
            threshold=threshold,
        )

    gap_pct = abs(value - threshold) / max(abs(threshold), 0.001) * 100
    return DecisionResult(
        decision="FAIL",
        explanation=(
            f"{metric_name} ({value:.4f}) does not satisfy constraint "
            f"({threshold:.4f}, {operator_symbol}). Gap: {gap_pct:.1f}%. "
            f"Manual intervention required."
        ),
        metric_value=value,
        threshold=threshold,
    )

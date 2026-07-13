"""Arbiter controller — orchestrates model evaluation against mission constraints.

Called after Furnace completes training. Loads the checkpoint, computes
metrics, compares against the user's deployment threshold from the mission
brief, and publishes the decision event.
"""

import json
import logging
from datetime import datetime, timezone

from agents.arbiter.decision import make_decision
from agents.arbiter.evaluator import evaluate, load_checkpoint_data
from agents.arbiter.models import (
    DecisionResult,
    EvaluationResult,
    MissionConstraints,
)
from agents.arbiter.report import (
    save_decision_report,
    save_evaluation_plots,
    save_evaluation_report,
    save_metrics_csv,
)
from bus.events import (
    EVALUATION_FAILED,
    EVALUATION_PASS,
    EVALUATION_RETRY,
    EVALUATION_STARTED,
    STREAM_ARBITER_OUTPUT,
)
from bus.publisher import publish
from prometheus.cli.mission.state_logger import log_mission_state

logger = logging.getLogger(__name__)


def build_constraints_from_brief(brief: dict | None) -> MissionConstraints:
    if brief is None:
        return MissionConstraints(metric="auc_roc")

    from contracts import MissionBrief

    try:
        mb = MissionBrief.model_validate(brief)
        metric = mb.evaluation_metric or "auc_roc"
        threshold = mb.deployment_threshold
        operator = mb.deployment_operator or ">"
        if mb.constraints:
            threshold = threshold or mb.constraints.deployment_threshold
            operator = mb.constraints.deployment_operator or operator
    except Exception:
        metric = brief.get("evaluation_metric") or "auc_roc"
        threshold = brief.get("deployment_threshold")
        operator = brief.get("deployment_operator") or ">"
        constraints_raw = brief.get("constraints", {})
        if isinstance(constraints_raw, dict):
            threshold = threshold or constraints_raw.get("deployment_threshold")
            operator = constraints_raw.get("deployment_operator") or operator

    if threshold is not None:
        try:
            threshold = float(threshold)
        except (ValueError, TypeError):
            threshold = None

    constraint_strings = []
    raw_parsed = brief.get("constraints_list") or brief.get("parsed_constraints") or []
    if isinstance(raw_parsed, list):
        constraint_strings = [str(c) for c in raw_parsed]

    logger.info(
        f"Arbiter constraints: metric={metric}, threshold={threshold}, "
        f"operator={operator}, from_brief={brief is not None}"
    )

    return MissionConstraints(
        metric=metric,
        threshold=threshold,
        operator=operator,
        constraints_list=constraint_strings,
    )


async def run_evaluation(
    job_id: str,
    redis_client,
    renderer=None,
    task_type: str = "classification",
    checkpoint_dir: str | None = None,
) -> dict:
    """Run the full evaluation pipeline.

    Steps:
        1. Load mission brief and extract constraints
        2. Load checkpoint and test data
        3. Compute evaluation metrics
        4. Make decision against constraints
        5. Save evaluation report
        6. Publish event to the bus
        7. Return decision summary

    Args:
        job_id: Job identifier.
        redis_client: Async Redis client for publishing events.
        renderer: Optional Rich console for CLI output (must have .print()).
        task_type: "classification" or "regression"
        checkpoint_dir: Override checkpoint directory.

    Returns:
        dict with keys: decision, explanation, metric_value, threshold, report_path
    """
    log_mission_state("ARBITER_START", job_id)
    logger.info(f"[job={job_id}] Arbiter evaluation started")

    if renderer:
        from agents.arbiter.ui import show_loading, show_start

        show_start(renderer)
        show_loading(renderer, "Loading mission brief")

    # Step 1: Load mission brief and extract constraints
    brief = None
    try:
        brief_raw = await redis_client.get(f"job:{job_id}:mission_brief")
        if brief_raw:
            brief = json.loads(brief_raw) if isinstance(brief_raw, str) else brief_raw
    except Exception:
        logger.warning(f"[job={job_id}] Failed to read mission brief")

    constraints = build_constraints_from_brief(brief)

    # Step 2: Load checkpoint and test data
    if renderer:
        show_loading(renderer, "Loading checkpoint and test data")

    try:
        checkpoint_data = load_checkpoint_data(job_id, checkpoint_dir=checkpoint_dir)
    except FileNotFoundError as e:
        logger.error(f"[job={job_id}] {e}")
        if renderer:
            from agents.arbiter.ui import show_checkpoint_missing, show_error

            show_checkpoint_missing(renderer, str(e))
        await _publish_failed(job_id, redis_client, str(e))
        return {
            "decision": "FAIL",
            "explanation": str(e),
            "metric_value": 0.0,
            "threshold": constraints.threshold,
            "report_path": None,
        }

    # Step 3: Compute metrics
    if renderer:
        show_loading(renderer, "Computing evaluation metrics")

    evaluation_result = evaluate(job_id, task_type=task_type, checkpoint_dir=checkpoint_dir)

    # Step 4: Make decision
    if renderer:
        show_loading(renderer, "Comparing against mission requirements")

    decision = make_decision(evaluation_result, constraints)

    # Step 5: Save reports — always evaluation.json, metrics.csv, decision.json
    report_path = save_evaluation_report(
        job_id,
        evaluation_result,
        decision,
        constraints,
    )
    save_metrics_csv(job_id, evaluation_result.all_metrics)
    save_decision_report(job_id, decision)

    # Step 5b: Save evaluation plots (confusion matrix, ROC, PR curve)
    save_evaluation_plots(
        job_id,
        y_true=checkpoint_data["y_true"],
        y_pred=checkpoint_data["y_pred"],
        y_prob=checkpoint_data.get("y_prob"),
        task_type=task_type,
    )

    # Step 6: Publish event
    await _publish_decision(job_id, redis_client, decision, constraints, report_path)

    # Step 7: Render results
    if renderer:
        from agents.arbiter.ui import show_decision, show_failure, show_pass, show_retry

        show_decision(renderer, evaluation_result, decision, constraints)
        if decision.decision == "PASS":
            show_pass(renderer)
        elif decision.decision == "RETRY":
            show_retry(renderer)
        else:
            show_failure(renderer)

    log_mission_state(
        "ARBITER_COMPLETE",
        job_id,
        metric_name=evaluation_result.metric,
        metric_value=evaluation_result.metric_value,
        deployment_threshold=constraints.threshold,
        decision=decision.decision,
        operator=constraints.operator,
    )

    logger.info(
        f"[job={job_id}] Arbiter complete: {decision.decision} | "
        f"{evaluation_result.metric}={evaluation_result.metric_value:.4f} | "
        f"threshold={constraints.threshold}"
    )

    return {
        "decision": decision.decision,
        "explanation": decision.explanation,
        "metric_value": evaluation_result.metric_value,
        "metric_name": evaluation_result.metric,
        "threshold": constraints.threshold,
        "report_path": report_path,
        "all_metrics": evaluation_result.all_metrics,
    }


async def _publish_decision(
    job_id: str,
    redis_client,
    decision: DecisionResult,
    constraints: MissionConstraints,
    report_path: str,
) -> None:
    from contracts.events import EvaluationPassEvent, EvaluationRetryEvent, EvaluationFailedEvent

    event_map = {
        "PASS": (
            EVALUATION_PASS,
            EvaluationPassEvent(
                job_id=job_id,
                eval_report_path=report_path,
                primary_metric=constraints.metric,
                primary_metric_value=decision.metric_value,
                threshold=constraints.threshold,
            ),
        ),
        "RETRY": (
            EVALUATION_RETRY,
            EvaluationRetryEvent(
                job_id=job_id,
                eval_report_path=report_path,
                primary_metric=constraints.metric,
                primary_metric_value=decision.metric_value,
                threshold=constraints.threshold,
                reason=decision.explanation,
            ),
        ),
        "FAIL": (
            EVALUATION_FAILED,
            EvaluationFailedEvent(
                job_id=job_id,
                reason=decision.explanation,
            ),
        ),
    }
    entry = event_map.get(decision.decision)
    if entry is None:
        entry = (
            EVALUATION_FAILED,
            EvaluationFailedEvent(job_id=job_id, reason=decision.explanation),
        )
    event_type, payload = entry

    await publish(redis_client, STREAM_ARBITER_OUTPUT, event_type, payload)
    logger.info(f"[job={job_id}] Published {event_type} to {STREAM_ARBITER_OUTPUT}")


async def _publish_failed(
    job_id: str,
    redis_client,
    reason: str,
) -> None:
    from contracts.events import EvaluationFailedEvent

    await publish(
        redis_client,
        STREAM_ARBITER_OUTPUT,
        EVALUATION_FAILED,
        EvaluationFailedEvent(job_id=job_id, reason=reason),
    )
    logger.info(f"[job={job_id}] Published {EVALUATION_FAILED}")

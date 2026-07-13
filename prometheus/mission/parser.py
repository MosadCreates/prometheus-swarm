from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from prometheus.mission.models import (
    METRIC_ALIASES,
    TASK_TYPE_ALIASES,
    ParsedMission,
)

logger = logging.getLogger(__name__)

_LLM_SYSTEM_PROMPT = """You are a mission parser for an autonomous ML engineering system.

Given a user's natural-language description of an ML problem, extract structured fields.

Return ONLY valid JSON with this exact schema:
{
  "problem_summary": "concise 1-sentence summary",
  "dataset_path": "path to dataset file if mentioned, or empty string",
  "target_column": "name of the target column if mentioned, or empty string",
  "evaluation_metric": "primary metric name (e.g. auc_roc, f1, accuracy, rmse, mae, r2)",
  "deployment_threshold": number between 0 and 1, or null if not specified,
  "deployment_operator": ">" if metric must be above threshold, "<" if below, or ">" if not specified,
  "task_type": "classification" | "regression" | "clustering" | "object_detection" | "segmentation" | "text_generation" | "forecasting",
  "constraints": ["list of additional constraints mentioned"]
}

Rules:
- If the task type is not explicitly stated, infer it from context.
- If dataset path is a filename without a directory, leave it as the filename.
- If evaluation metric is not stated, infer the most appropriate metric for the task.
- deployment_threshold must be null if not specified. Never invent one.
- Return ONLY the JSON object. No explanation. No markdown."""


async def parse_mission(description: str) -> ParsedMission:
    """Parse a free-form mission description into structured fields.

    Uses the LLM to extract fields, then normalises known values.
    Retries once if parsing fails.
    """
    from agents.llm_client import get_llm_response

    for attempt in range(2):
        try:
            response = await get_llm_response(
                system_prompt=_LLM_SYSTEM_PROMPT,
                user_message=description,
                job_id="mission-parse",
                agent_name="mission-parser",
                max_retries=2,
            )
            text = response.get("text", "")
            raw = _extract_json(text)
            if raw is None:
                if attempt == 0:
                    continue
                return _fallback(description)

            parsed = _normalise(raw, description)
            parsed.dataset_exists = _check_dataset(parsed.dataset_path)
            return parsed

        except Exception as e:
            logger.warning(f"Parse attempt {attempt + 1} failed: {e}")
            if attempt == 1:
                return _fallback(description)

    return _fallback(description)


def _extract_json(text: str) -> dict | None:
    """Extract a JSON object from LLM response text."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    return None


def _normalise(raw: dict, original: str) -> ParsedMission:
    """Normalise parsed fields into canonical forms."""
    dataset_path = (raw.get("dataset_path") or "").strip()
    target_column = (raw.get("target_column") or "").strip()
    metric = (raw.get("evaluation_metric") or "").strip().lower()
    task = (raw.get("task_type") or "").strip().lower()
    threshold = raw.get("deployment_threshold")
    operator = raw.get("deployment_operator", ">")

    # Normalise operator
    if operator not in (">", ">=", "<", "<="):
        operator = ">"

    # Normalise metric
    normal_metric = METRIC_ALIASES.get(metric, metric)
    if normal_metric and normal_metric not in {
        "accuracy",
        "f1",
        "precision",
        "recall",
        "auc_roc",
        "rmse",
        "mae",
        "mse",
        "r2",
    }:
        normal_metric = metric

    # Normalise task type
    normal_task = TASK_TYPE_ALIASES.get(task, task)

    # Normalise threshold
    if threshold is not None:
        try:
            threshold = float(threshold)
        except (ValueError, TypeError):
            threshold = None

    constraints = raw.get("constraints") or []

    return ParsedMission(
        original_prompt=original,
        problem_summary=raw.get("problem_summary") or original[:200],
        dataset_path=dataset_path,
        target_column=target_column,
        evaluation_metric=normal_metric,
        deployment_threshold=threshold,
        deployment_operator=operator,
        task_type=normal_task,
        constraints=list(constraints),
    )


def _fallback(description: str) -> ParsedMission:
    """Create a minimal ParsedMission when LLM parsing fails."""
    path = _guess_dataset_path(description)
    return ParsedMission(
        original_prompt=description,
        problem_summary=description[:200],
        dataset_path=path,
        target_column="",
        evaluation_metric="",
        task_type="classification",
        warnings=["Could not fully parse mission description"],
    )


def _guess_dataset_path(description: str) -> str:
    """Try to find a dataset path mentioned in the description."""
    match = re.search(
        r"(?:dataset|data|file)[:\s]+([^\s,.]+)",
        description,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    return ""


def _check_dataset(path: str) -> bool:
    """Check if the dataset file exists on disk."""
    if not path:
        return False
    if os.path.exists(path):
        return True
    for prefix in [".", "./data", "./datasets", "./dataset"]:
        candidate = os.path.join(prefix, os.path.basename(path))
        if os.path.exists(candidate):
            return True
    return False

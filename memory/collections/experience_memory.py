"""
experience_memory collection.

Stores actual training outcomes (metric, time, crashes, decisions, pipeline)
after each job completes. Scout and Forge query this during the next job to
reuse proven engineering patterns from similar past problems.

Stage 3 enrichment:
- Rich embedding text captures full dataset profile + decisions + outcome
- Dataset fingerprint stored as metadata for filtered queries
- Pipeline steps, feature engineering, patch history stored
- New query_best_pipeline() returns the most successful architecture+pipeline
  for a given problem context
"""

import json
import logging
import os
from typing import Any

from memory.chroma_client import ChromaClient
from memory.schemas import ExperienceRecord

logger = logging.getLogger(__name__)

COLLECTION_NAME = "experience_memory"


def _get_collection():
    return ChromaClient().get_or_create_collection(COLLECTION_NAME)


def _build_embedding_text(record: ExperienceRecord) -> str:
    """Build a rich embedding text that captures full problem context.

    The embedding text includes:
    - Modality, task, dataset size
    - Data quality characteristics (imbalance, missing rates, cardinality)
    - Architecture and outcome
    - Engineering decisions summary
    - Pipeline steps and feature engineering

    This enables semantic similarity search to find truly similar past problems.
    """
    parts = [
        f"Modality: {record.modality}",
        f"Task: {record.task_type}",
        f"Rows: {record.num_rows}",
        f"Columns: {record.num_columns}",
        f"Architecture: {record.architecture}",
        f"Outcome: {record.outcome}",
    ]

    fp = record.dataset_fingerprint or {}
    if fp.get("class_imbalance_ratio") is not None:
        parts.append(f"Imbalance: {fp['class_imbalance_ratio']}")
    if fp.get("high_cardinality_columns"):
        parts.append(f"HighCardinality: {len(fp['high_cardinality_columns'])} cols")
    missing_rate = fp.get("missing_rate_summary", {})
    if missing_rate:
        parts.append(f"MissingRate: {json.dumps(missing_rate)}")

    col_types = fp.get("column_types", {})
    numeric_count = sum(1 for v in col_types.values() if v in ("numeric", "int64", "float64"))
    categorical_count = sum(1 for v in col_types.values() if v in ("categorical", "object"))
    text_count = sum(1 for v in col_types.values() if v == "text")
    if numeric_count or categorical_count or text_count:
        parts.append(f"ColTypes: num={numeric_count} cat={categorical_count} txt={text_count}")

    if record.engineering_decisions:
        ed = record.engineering_decisions
        if "preprocessing" in ed:
            parts.append(f"Preprocessing: {ed['preprocessing']}")
        if "imbalance" in ed:
            parts.append(f"ImbalanceStrategy: {ed['imbalance']}")
        if "validation" in ed:
            parts.append(f"Validation: {ed['validation']}")
        if "leakage" in ed:
            parts.append(f"LeakageCheck: {ed['leakage']}")

    if record.pipeline_steps:
        parts.append(f"Pipeline: {' -> '.join(record.pipeline_steps[:5])}")
    if record.feature_engineering:
        parts.append(f"FeatureEng: {'; '.join(record.feature_engineering[:3])}")

    if record.achieved_metric is not None:
        parts.append(f"Metric: {record.achieved_metric}")
    if record.total_crashes > 0:
        parts.append(f"Crashes: {record.total_crashes}")
    ps = record.patch_summary or {}
    if ps.get("total_attempts", 0) > 0:
        parts.append(f"Patches: {ps['total_attempts']} attempts")
        if ps.get("categories"):
            parts.append(f"PatchCats: {', '.join(ps['categories'][:3])}")

    return " | ".join(parts)


def _build_metadata(record: ExperienceRecord) -> dict[str, str]:
    """Build searchable metadata dict from the full record."""
    fp = record.dataset_fingerprint or {}
    col_types = fp.get("column_types", {})
    numeric_count = sum(1 for v in col_types.values() if v in ("numeric", "int64", "float64"))
    categorical_count = sum(1 for v in col_types.values() if v in ("categorical", "object"))

    meta: dict[str, str] = {
        "job_id": record.job_id,
        "modality": record.modality,
        "task_type": record.task_type,
        "num_rows": str(record.num_rows),
        "num_columns": str(record.num_columns),
        "architecture": record.architecture,
        "outcome": record.outcome,
    }

    if record.class_imbalance_ratio is not None:
        meta["class_imbalance_ratio"] = str(record.class_imbalance_ratio)
    if record.achieved_metric is not None:
        meta["achieved_metric"] = str(record.achieved_metric)
    if record.expected_metric_range:
        meta["expected_metric_low"] = str(record.expected_metric_range[0])
        meta["expected_metric_high"] = str(record.expected_metric_range[1])
    if record.expected_training_minutes is not None:
        meta["expected_training_minutes"] = str(record.expected_training_minutes)
    if record.actual_training_minutes is not None:
        meta["actual_training_minutes"] = str(record.actual_training_minutes)

    meta["total_crashes"] = str(record.total_crashes)
    meta["patch_success"] = str(record.patch_success)

    # Datatset fingerprint metadata for filtered queries
    meta["numeric_columns"] = str(numeric_count)
    meta["categorical_columns"] = str(categorical_count)

    imbalance_val = fp.get("class_imbalance_ratio")
    meta["imbalance_ratio"] = str(imbalance_val) if imbalance_val is not None else "none"

    missing_rate = fp.get("missing_rate_summary", {})
    meta["has_missing_values"] = "true" if any(v > 0 for v in missing_rate.values()) else "false"

    outlier_count = fp.get("outlier_count", 0)
    meta["outlier_count"] = str(outlier_count)

    ps = record.patch_summary or {}
    meta["patch_total_attempts"] = str(ps.get("total_attempts", 0))
    meta["patch_categories"] = ",".join(ps.get("categories", []))

    if record.engineering_decisions:
        meta["engineering_decisions_json"] = json.dumps(record.engineering_decisions)

    return meta


def store_experience(record: ExperienceRecord) -> None:
    """Store an actual training outcome for future retrieval.

    Embedding text is built from the full problem context including data quality,
    engineering decisions, pipeline, and outcome so that semantically similar
    past experiences are found by problem characteristics, not just metadata.

    Args:
        record: ExperienceRecord with actual outcomes from a completed job.
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    except Exception as e:
        logger.warning(f"Experience memory: embedding model load failed: {e}")
        return

    text = _build_embedding_text(record)
    embedding = model.encode(text).tolist()
    metadata = _build_metadata(record)

    collection = _get_collection()
    collection.add(
        ids=[record.job_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[text],
    )

    logger.info(
        f"Experience stored: {record.job_id} | "
        f"arch={record.architecture} outcome={record.outcome} "
        f"metric={record.achieved_metric} "
        f"decisions={bool(record.engineering_decisions)} "
        f"fingerprint={bool(record.dataset_fingerprint)}"
    )


def query_similar_experiences(
    modality: str,
    task_type: str,
    num_rows: int,
    architecture: str | None = None,
    k: int = 5,
    num_columns: int | None = None,
    imbalance_ratio: float | None = None,
) -> list[dict[str, Any]]:
    """Retrieve K most similar past experiences for a given problem context.

    Args:
        modality: "tabular", "text", or "image"
        task_type: "classification", "regression", etc.
        num_rows: Number of rows in the new dataset
        architecture: Optional architecture filter
        k: Number of results to return
        num_columns: Optional column count filter (improves dataset similarity)
        imbalance_ratio: Optional imbalance ratio filter

    Returns:
        List of dicts with keys: job_id, architecture, outcome, achieved_metric,
        expected_metric_low, expected_metric_high, actual_training_minutes,
        total_crashes, patch_success, similarity_score, prediction_error,
        pipeline_steps, feature_engineering, patch_summary, engineering_decisions.
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        # Build a rich query embedding that includes dataset characteristics
        query_parts = [f"Modality: {modality}", f"Task: {task_type}", f"Rows: {num_rows}"]
        if num_columns is not None:
            query_parts.append(f"Columns: {num_columns}")
        if imbalance_ratio is not None:
            query_parts.append(f"Imbalance: {imbalance_ratio}")
        text = " | ".join(query_parts)
        embedding = model.encode(text).tolist()
    except Exception as e:
        logger.warning(f"Experience memory: embedding failed: {e}")
        return []

    collection = _get_collection()

    where_filter: dict[str, Any] = {"modality": modality}
    if architecture:
        where_filter["architecture"] = architecture

    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where=where_filter,
    )

    experiences = []
    if results and results.get("ids") and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results.get("metadatas") else {}
            distance = results["distances"][0][i] if results.get("distances") else 0.0

            achieved = _safe_float(meta.get("achieved_metric"))
            expected_low = _safe_float(meta.get("expected_metric_low"))
            expected_high = _safe_float(meta.get("expected_metric_high"))

            prediction_error = None
            if (
                achieved is not None
                and expected_low is not None
                and expected_high is not None
                and expected_high != expected_low
            ):
                expected_mid = (expected_low + expected_high) / 2.0
                prediction_error = abs(achieved - expected_mid) / max(abs(expected_mid), 0.001)

            # Parse enriched fields from metadata
            engineering_decisions = {}
            ed_json = meta.get("engineering_decisions_json", "")
            if ed_json:
                try:
                    engineering_decisions = json.loads(ed_json)
                except (json.JSONDecodeError, TypeError):
                    pass

            pipeline_steps_str = meta.get("pipeline_steps", "")
            pipeline_steps = pipeline_steps_str.split(" -> ") if pipeline_steps_str else []
            feature_eng_str = meta.get("feature_engineering", "")
            feature_engineering = feature_eng_str.split("; ") if feature_eng_str else []

            experiences.append(
                {
                    "job_id": doc_id,
                    "architecture": meta.get("architecture", ""),
                    "outcome": meta.get("outcome", ""),
                    "achieved_metric": achieved,
                    "expected_metric_low": expected_low,
                    "expected_metric_high": expected_high,
                    "actual_training_minutes": _safe_float(meta.get("actual_training_minutes")),
                    "total_crashes": int(meta.get("total_crashes", "0")),
                    "patch_success": meta.get("patch_success", "False") == "True",
                    "similarity_score": round(max(0.0, 1.0 - float(distance)), 4),
                    "prediction_error": (
                        round(prediction_error, 4) if prediction_error is not None else None
                    ),
                    "pipeline_steps": pipeline_steps,
                    "feature_engineering": feature_engineering,
                    "patch_total_attempts": int(meta.get("patch_total_attempts", "0")),
                    "patch_categories": (
                        meta.get("patch_categories", "").split(",")
                        if meta.get("patch_categories")
                        else []
                    ),
                    "engineering_decisions": engineering_decisions,
                    "outlier_count": int(meta.get("outlier_count", "0")),
                    "has_missing_values": meta.get("has_missing_values", "false") == "true",
                    "imbalance_ratio": meta.get("imbalance_ratio", "none"),
                }
            )

    return experiences


def query_by_dataset_profile(
    modality: str,
    task_type: str,
    num_rows: int,
    num_columns: int | None = None,
    imbalance_ratio: float | None = None,
    has_missing: bool | None = None,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Find experiences with a similar dataset profile.

    Uses rich embedding + metadata filters to surface datasets that match
    on data quality characteristics (imbalance, missing values, column count).

    Args:
        modality: "tabular", "text", or "image"
        task_type: "classification", "regression", etc.
        num_rows: Number of rows in the dataset
        num_columns: Optional column count
        imbalance_ratio: Optional imbalance ratio
        has_missing: Optional missing values filter
        k: Max results

    Returns:
        List of experience dicts sorted by similarity.
    """
    return query_similar_experiences(
        modality=modality,
        task_type=task_type,
        num_rows=num_rows,
        k=k,
        num_columns=num_columns,
        imbalance_ratio=imbalance_ratio,
    )


def query_best_pipeline(
    modality: str,
    task_type: str,
    num_rows: int,
    num_columns: int | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Recommend the best past pipeline(s) for a given problem context.

    Returns only experiences with "pass" outcome, sorted by achieved_metric
    descending, so the caller can see what architectures + configurations
    worked best for similar problems.

    Args:
        modality: "tabular", "text", or "image"
        task_type: "classification", "regression", etc.
        num_rows: Number of rows
        num_columns: Optional column count for better similarity
        k: Number of recommendations

    Returns:
        List of successful experience dicts sorted by achieved_metric desc.
    """
    experiences = query_similar_experiences(
        modality=modality,
        task_type=task_type,
        num_rows=num_rows,
        k=20,  # Fetch more, then filter + sort
        num_columns=num_columns,
    )

    # Filter to completed pass outcomes with a metric
    successful = [
        e
        for e in experiences
        if e.get("outcome") == "pass" and e.get("achieved_metric") is not None
    ]
    successful.sort(key=lambda e: e["achieved_metric"], reverse=True)

    return successful[:k]


def query_architecture_confidence(
    architecture: str, modality: str, task_type: str
) -> dict[str, Any]:
    """Return aggregate confidence signal for a given architecture.

    Computes historical pass/retry/escalate ratio and average prediction error.

    Returns:
        dict with keys: total_jobs, pass_count, retry_count, escalate_count,
        pass_ratio, avg_prediction_error, avg_crashes, avg_metric.
    """
    experiences = query_similar_experiences(
        modality, task_type, 0, architecture=architecture, k=100
    )
    if not experiences:
        return {
            "total_jobs": 0,
            "pass_ratio": None,
            "avg_prediction_error": None,
            "avg_crashes": None,
            "avg_metric": None,
        }

    outcomes = [e["outcome"] for e in experiences]
    passes = outcomes.count("pass")
    retries = outcomes.count("retry")
    escalates = outcomes.count("escalate")

    errors = [e["prediction_error"] for e in experiences if e["prediction_error"] is not None]
    crashes = [e["total_crashes"] for e in experiences]
    metrics = [e["achieved_metric"] for e in experiences if e["achieved_metric"] is not None]

    return {
        "total_jobs": len(experiences),
        "pass_count": passes,
        "retry_count": retries,
        "escalate_count": escalates,
        "pass_ratio": round(passes / len(experiences), 4) if experiences else 0.0,
        "avg_prediction_error": round(sum(errors) / len(errors), 4) if errors else None,
        "avg_crashes": round(sum(crashes) / len(crashes), 2) if crashes else 0.0,
        "avg_metric": round(sum(metrics) / len(metrics), 4) if metrics else None,
    }


def _safe_float(val: str | None) -> float | None:
    if val is None or val == "none":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

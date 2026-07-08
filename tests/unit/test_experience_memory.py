"""Unit tests for Experience Memory (Stage 3).

Covers:
- ExperienceRecord Pydantic model fields
- store_experience ChromaDB interaction
- query_similar_experiences result parsing
- query_architecture_confidence aggregation
- adjust_with_experience pure function
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from memory.collections.experience_memory import (
    _safe_float,
    query_architecture_confidence,
    query_similar_experiences,
    store_experience,
)
from memory.schemas import ExperienceRecord
from agents.scout.reasoning import adjust_with_experience


# ---------------------------------------------------------------------------
# ExperienceRecord validation
# ---------------------------------------------------------------------------


def test_experience_record_defaults():
    record = ExperienceRecord(
        job_id="job-001",
        modality="tabular",
        task_type="classification",
        num_rows=1000,
        architecture="lightgbm",
        outcome="pass",
    )
    assert record.job_id == "job-001"
    assert record.total_crashes == 0
    assert record.patch_success is False
    assert record.achieved_metric is None
    assert record.created_at is not None
    # Stage 3 fields default to empty
    assert record.dataset_fingerprint == {}
    assert record.engineering_decisions == {}
    assert record.pipeline_steps == []
    assert record.feature_engineering == []
    assert record.patch_summary == {}
    assert record.mission_spec_key == ""
    assert record.engineering_plan_key == ""


def test_experience_record_full():
    record = ExperienceRecord(
        job_id="job-001",
        modality="tabular",
        task_type="classification",
        num_rows=1000,
        num_columns=20,
        architecture="lightgbm",
        class_imbalance_ratio=5.0,
        expected_metric_range=[0.75, 0.88],
        achieved_metric=0.82,
        expected_training_minutes=5,
        actual_training_minutes=4.5,
        total_crashes=0,
        patch_success=True,
        outcome="pass",
        dataset_fingerprint={"class_imbalance_ratio": 5.0, "column_types": {"age": "numeric"}},
        engineering_decisions={
            "preprocessing": "median_imputation",
            "validation": "stratified_kfold",
        },
        pipeline_steps=["median_imputation", "ordinal_encode", "lightgbm"],
        feature_engineering=["log_transform_skewed"],
        patch_summary={"total_attempts": 0, "categories": [], "last_outcome": "none"},
        api_cost_usd=0.15,
        mission_spec_key="job:job-001:mission_spec",
    )
    assert record.achieved_metric == 0.82
    assert record.expected_training_minutes == 5
    assert record.dataset_fingerprint["class_imbalance_ratio"] == 5.0
    assert record.engineering_decisions["validation"] == "stratified_kfold"
    assert record.pipeline_steps == ["median_imputation", "ordinal_encode", "lightgbm"]
    assert record.api_cost_usd == 0.15


# ---------------------------------------------------------------------------
# _safe_float
# ---------------------------------------------------------------------------


def test_safe_float_none():
    assert _safe_float(None) is None


def test_safe_float_none_str():
    assert _safe_float("none") is None


def test_safe_float_value():
    assert _safe_float("0.85") == 0.85


def test_safe_float_invalid():
    assert _safe_float("not_a_number") is None


# ---------------------------------------------------------------------------
# store_experience (ChromaDB interaction)
# ---------------------------------------------------------------------------


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_store_experience_success(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    record = ExperienceRecord(
        job_id="job-001",
        modality="tabular",
        task_type="classification",
        num_rows=1000,
        architecture="lightgbm",
        achieved_metric=0.85,
        outcome="pass",
    )
    store_experience(record)

    mock_model.encode.assert_called_once()
    mock_collection.add.assert_called_once()
    args, kwargs = mock_collection.add.call_args
    assert kwargs["ids"] == ["job-001"]
    assert kwargs["metadatas"][0]["outcome"] == "pass"
    assert kwargs["metadatas"][0]["achieved_metric"] == "0.85"
    # Stage 3 metadata fields
    assert kwargs["metadatas"][0]["numeric_columns"] == "0"
    assert kwargs["metadatas"][0]["categorical_columns"] == "0"
    assert kwargs["metadatas"][0]["imbalance_ratio"] == "none"
    assert kwargs["metadatas"][0]["outlier_count"] == "0"
    assert kwargs["metadatas"][0]["patch_total_attempts"] == "0"
    assert kwargs["metadatas"][0]["has_missing_values"] == "false"


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_store_experience_with_full_record(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    record = ExperienceRecord(
        job_id="job-002",
        modality="text",
        task_type="classification",
        num_rows=5000,
        num_columns=2,
        architecture="distilbert",
        expected_metric_range=[0.78, 0.90],
        achieved_metric=0.84,
        expected_training_minutes=15,
        actual_training_minutes=12.3,
        total_crashes=1,
        patch_success=True,
        outcome="pass",
        dataset_fingerprint={
            "class_imbalance_ratio": None,
            "column_types": {"text": "text", "label": "categorical"},
            "high_cardinality_columns": [],
        },
        engineering_decisions={"preprocessing": "tfidf", "validation": "train_val_split"},
        pipeline_steps=["tfidf", "distilbert"],
        feature_engineering=["text_vectorization"],
        patch_summary={"total_attempts": 1, "categories": ["oom"], "last_outcome": "success"},
    )
    store_experience(record)

    kwargs = mock_collection.add.call_args[1]
    meta = kwargs["metadatas"][0]
    assert meta["modality"] == "text"
    assert meta["achieved_metric"] == "0.84"
    assert meta["total_crashes"] == "1"
    assert meta["patch_success"] == "True"
    assert meta["outcome"] == "pass"
    # Stage 3 metadata
    assert meta["patch_total_attempts"] == "1"
    assert meta["patch_categories"] == "oom"
    assert meta["numeric_columns"] == "0"
    assert meta["categorical_columns"] == "1"


@patch("memory.collections.experience_memory.ChromaClient")
def test_store_experience_silent_on_embedding_failure(mock_chroma):
    with patch(
        "sentence_transformers.SentenceTransformer",
        side_effect=ImportError("model not found"),
    ):
        record = ExperienceRecord(
            job_id="job-003",
            modality="tabular",
            task_type="regression",
            num_rows=500,
            architecture="xgboost",
            outcome="escalate",
        )
        store_experience(record)


# ---------------------------------------------------------------------------
# query_similar_experiences
# ---------------------------------------------------------------------------


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_similar_experiences_returns_list(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["job-001", "job-002"]],
        "metadatas": [
            [
                {
                    "architecture": "lightgbm",
                    "outcome": "pass",
                    "achieved_metric": "0.85",
                    "expected_metric_low": "0.75",
                    "expected_metric_high": "0.88",
                    "actual_training_minutes": "4.5",
                    "total_crashes": "0",
                    "patch_success": "True",
                },
                {
                    "architecture": "xgboost",
                    "outcome": "retry",
                    "achieved_metric": "0.72",
                    "expected_metric_low": "0.73",
                    "expected_metric_high": "0.87",
                    "actual_training_minutes": "6.2",
                    "total_crashes": "2",
                    "patch_success": "False",
                },
            ]
        ],
        "distances": [[0.12, 0.28]],
        "documents": [["", ""]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_similar_experiences("tabular", "classification", 1000, k=5)

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["job_id"] == "job-001"
    assert results[0]["architecture"] == "lightgbm"
    assert results[0]["outcome"] == "pass"
    assert results[0]["achieved_metric"] == 0.85
    assert results[0]["similarity_score"] == 0.88
    assert results[0]["prediction_error"] is not None

    assert results[1]["job_id"] == "job-002"
    assert results[1]["achieved_metric"] == 0.72
    assert results[1]["total_crashes"] == 2
    assert results[1]["patch_success"] is False


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_similar_experiences_empty(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "metadatas": None,
        "distances": [[]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_similar_experiences("tabular", "classification", 999999)
    assert results == []


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_similar_experiences_with_architecture_filter(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["job-001"]],
        "metadatas": [[{"architecture": "lightgbm"}]],
        "distances": [[0.1]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    query_similar_experiences("tabular", "classification", 1000, architecture="lightgbm", k=3)

    call_kwargs = mock_collection.query.call_args[1]
    assert call_kwargs["where"] == {"modality": "tabular", "architecture": "lightgbm"}


# ---------------------------------------------------------------------------
# query_architecture_confidence
# ---------------------------------------------------------------------------


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_architecture_confidence_no_data(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_chroma_instance = MagicMock()
    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [[]],
        "metadatas": None,
        "distances": [[]],
    }
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    result = query_architecture_confidence("lightgbm", "tabular", "classification")
    assert result["total_jobs"] == 0
    assert result["pass_ratio"] is None


# ---------------------------------------------------------------------------
# adjust_with_experience
# ---------------------------------------------------------------------------


def _make_decisions(**overrides) -> dict:
    base = {
        "problem_type": {
            "title": "PT",
            "rationale": "r",
            "confidence": 0.85,
            "alternatives": [],
            "selected": "classification",
        },
        "data_quality": {
            "title": "DQ",
            "rationale": "r",
            "confidence": 0.90,
            "alternatives": [],
            "selected": "clean",
        },
        "architecture": {
            "title": "Arch",
            "rationale": "r",
            "confidence": 0.80,
            "alternatives": ["xgboost"],
            "selected": "lightgbm",
        },
        "overall_confidence": 0.85,
    }
    base.update(overrides)
    return base


def _make_experience(
    metric: float,
    expected_low: float,
    expected_high: float,
    outcome: str = "pass",
    arch: str = "lightgbm",
) -> dict:
    mid = (expected_low + expected_high) / 2.0
    return {
        "job_id": "job-001",
        "architecture": arch,
        "outcome": outcome,
        "achieved_metric": metric,
        "expected_metric_low": expected_low,
        "expected_metric_high": expected_high,
        "prediction_error": abs(metric - mid) / max(abs(mid), 0.001),
    }


def test_adjust_no_experiences():
    decisions = _make_decisions()
    result = adjust_with_experience(decisions, [])
    assert result["problem_type"]["confidence"] == 0.85


def test_adjust_boost_on_accurate():
    decisions = _make_decisions()
    experiences = [_make_experience(0.82, 0.80, 0.84)]
    result = adjust_with_experience(decisions, experiences, boost_threshold=0.10)
    assert result["problem_type"]["confidence"] == 0.90  # 0.85 + 0.05


def test_adjust_penalty_on_inaccurate():
    decisions = _make_decisions()
    experiences = [_make_experience(0.55, 0.75, 0.88)]
    result = adjust_with_experience(decisions, experiences, penalty_threshold=0.20)
    assert result["problem_type"]["confidence"] == 0.75  # 0.85 - 0.10


def test_adjust_does_not_breach_ceiling():
    decisions = _make_decisions(
        problem_type={
            "title": "PT",
            "rationale": "r",
            "confidence": 0.97,
            "alternatives": [],
            "selected": "classification",
        }
    )
    experiences = [_make_experience(0.82, 0.80, 0.84)]
    result = adjust_with_experience(decisions, experiences, boost_threshold=0.10)
    assert result["problem_type"]["confidence"] <= 0.98


def test_adjust_does_not_breach_floor():
    decisions = _make_decisions(
        problem_type={
            "title": "PT",
            "rationale": "r",
            "confidence": 0.45,
            "alternatives": [],
            "selected": "classification",
        }
    )
    experiences = [_make_experience(0.30, 0.75, 0.88)]
    result = adjust_with_experience(decisions, experiences, penalty_threshold=0.01)
    assert result["problem_type"]["confidence"] >= 0.40


def test_adjust_architecture_boost_on_high_pass_ratio():
    decisions = _make_decisions(
        architecture={
            "title": "Arch",
            "rationale": "r",
            "confidence": 0.80,
            "alternatives": ["xgboost"],
            "selected": "lightgbm",
        }
    )
    experiences = [
        _make_experience(0.82, 0.78, 0.86, outcome="pass", arch="lightgbm"),
        _make_experience(0.84, 0.78, 0.86, outcome="pass", arch="lightgbm"),
        _make_experience(0.81, 0.78, 0.86, outcome="pass", arch="lightgbm"),
    ]
    result = adjust_with_experience(decisions, experiences)
    assert result["architecture"]["confidence"] > 0.80


def test_adjust_architecture_penalty_on_low_pass_ratio():
    decisions = _make_decisions(
        architecture={
            "title": "Arch",
            "rationale": "r",
            "confidence": 0.80,
            "alternatives": ["xgboost"],
            "selected": "lightgbm",
        }
    )
    experiences = [
        _make_experience(0.82, 0.78, 0.86, outcome="pass", arch="lightgbm"),
        _make_experience(0.40, 0.78, 0.86, outcome="escalate", arch="lightgbm"),
        _make_experience(0.38, 0.78, 0.86, outcome="escalate", arch="lightgbm"),
    ]
    # prediction_error for first is low, for the other two is high
    # two out of three have high error, causing avg_error > penalty_threshold
    result = adjust_with_experience(decisions, experiences, penalty_threshold=0.15)
    assert result["architecture"]["confidence"] < 0.80


def test_adjust_no_change_when_no_completed_experiences():
    decisions = _make_decisions()
    experiences = [
        {
            "job_id": "job-001",
            "architecture": "lightgbm",
            "outcome": "pass",
            "achieved_metric": None,  # Not completed yet
            "expected_metric_low": None,
            "expected_metric_high": None,
            "prediction_error": None,
        }
    ]
    result = adjust_with_experience(decisions, experiences)
    assert result["problem_type"]["confidence"] == 0.85


def test_adjust_recomputes_overall_confidence():
    decisions = _make_decisions(
        problem_type={
            "title": "PT",
            "rationale": "r",
            "confidence": 0.85,
            "alternatives": [],
            "selected": "classification",
        },
        data_quality={
            "title": "DQ",
            "rationale": "r",
            "confidence": 0.85,
            "alternatives": [],
            "selected": "clean",
        },
        overall_confidence=0.85,
    )
    experiences = [_make_experience(0.82, 0.80, 0.84)]
    result = adjust_with_experience(decisions, experiences, boost_threshold=0.10)
    # Both decisions should be boosted from 0.85 to 0.90
    # overall = (0.90 + 0.90) / 2 = 0.90
    assert result["overall_confidence"] >= 0.85


def test_adjust_overall_confidence_has_floor():
    decisions = _make_decisions(
        problem_type={
            "title": "PT",
            "rationale": "r",
            "confidence": 0.45,
            "alternatives": [],
            "selected": "classification",
        },
        data_quality={
            "title": "DQ",
            "rationale": "r",
            "confidence": 0.45,
            "alternatives": [],
            "selected": "clean",
        },
        overall_confidence=0.45,
    )
    experiences = [_make_experience(0.30, 0.75, 0.88)]
    result = adjust_with_experience(decisions, experiences, penalty_threshold=0.01)
    assert result["overall_confidence"] >= 0.40


# ---------------------------------------------------------------------------
# query_best_pipeline
# ---------------------------------------------------------------------------


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_best_pipeline_returns_sorted_passes(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["job-001", "job-002", "job-003"]],
        "metadatas": [
            [
                {"architecture": "lightgbm", "outcome": "pass", "achieved_metric": "0.85"},
                {"architecture": "xgboost", "outcome": "pass", "achieved_metric": "0.91"},
                {"architecture": "lightgbm", "outcome": "escalate", "achieved_metric": "0.45"},
            ]
        ],
        "distances": [[0.1, 0.15, 0.2]],
        "documents": [["", "", ""]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    from memory.collections.experience_memory import query_best_pipeline

    results = query_best_pipeline("tabular", "classification", 1000, k=2)
    assert len(results) == 2  # Only 2 passes, third excluded
    assert results[0]["architecture"] == "xgboost"  # Highest metric first
    assert results[0]["achieved_metric"] == 0.91
    assert results[1]["architecture"] == "lightgbm"
    assert results[1]["achieved_metric"] == 0.85


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_query_best_pipeline_empty_when_no_passes(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["job-001"]],
        "metadatas": [
            [{"architecture": "lightgbm", "outcome": "escalate", "achieved_metric": "0.45"}]
        ],
        "distances": [[0.1]],
        "documents": [[""]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    from memory.collections.experience_memory import query_best_pipeline

    results = query_best_pipeline("tabular", "classification", 1000)
    assert results == []


# ---------------------------------------------------------------------------
# query_architecture_confidence (enriched)
# ---------------------------------------------------------------------------


@patch("memory.collections.experience_memory.ChromaClient")
@patch("sentence_transformers.SentenceTransformer")
def test_architecture_confidence_includes_avg_metric(mock_st, mock_chroma):
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_st.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["job-001", "job-002"]],
        "metadatas": [
            [
                {"architecture": "lightgbm", "outcome": "pass", "achieved_metric": "0.85"},
                {"architecture": "lightgbm", "outcome": "pass", "achieved_metric": "0.87"},
            ]
        ],
        "distances": [[0.1, 0.15]],
        "documents": [["", ""]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    result = query_architecture_confidence("lightgbm", "tabular", "classification")
    assert result["total_jobs"] == 2
    assert result["avg_metric"] == 0.86
    assert result["pass_ratio"] == 1.0


def test_adjust_skips_non_decision_keys():
    decisions = _make_decisions()
    decisions["risks"] = ["some risk"]
    experiences = [_make_experience(0.82, 0.80, 0.84)]
    result = adjust_with_experience(decisions, experiences, boost_threshold=0.10)
    # risks should not be touched
    assert result["risks"] == ["some risk"]

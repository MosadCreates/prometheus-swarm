"""Unit tests for Mission Report generation."""

import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestrator.mission_report import (
    _compute_prediction_vs_actual,
    _generate_lessons_learned,
    _render_markdown,
    generate_mission_report,
)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_REPORT_DATA = {
    "report_version": "1.0",
    "job_id": "job-001",
    "status": "COMPLETED",
    "created_at": "2026-07-07T12:00:00Z",
    "overview": {
        "problem_description": "Predict survival on Titanic",
        "task_type": "classification",
        "modality": "tabular",
        "dataset": {"file_path": "/data/titanic.csv", "num_rows": 891, "num_columns": 11},
        "pipeline_duration_seconds": 300,
    },
    "scout_analysis": {
        "decisions": {
            "problem_type": {
                "title": "Problem Type",
                "selected": "classification",
                "confidence": 0.95,
            },
            "data_quality": {"title": "Data Quality", "selected": "clean", "confidence": 0.95},
            "architecture": {"title": "Architecture", "selected": "lightgbm", "confidence": 0.85},
        },
        "risks": [],
        "overall_confidence": 0.88,
    },
    "forge_plan": {
        "architecture_selected": {
            "name": "lightgbm",
            "expected_training_minutes": 5,
            "expected_ram_mb": 257,
            "expected_metric_range": [0.75, 0.88],
            "reason_for_selection": "lightgbm is fast for small tabular data",
        },
        "alternatives": [
            {"name": "xgboost", "expected_training_minutes": 6, "expected_ram_mb": 257},
        ],
        "preprocessing_pipeline": [
            {"name": "median_imputation_numeric", "library": "sklearn.impute.SimpleImputer"},
            {"name": "ordinal_encoding", "library": "sklearn.preprocessing.OrdinalEncoder"},
        ],
        "hyperparameter_strategy": {"approach": "optuna_bayesian", "max_trials": 30},
        "computational_budget": {"gpu_required": False},
        "fallback_plan": "Switch to XGBoost with same preprocessing",
    },
    "training_outcome": {
        "best_val_metric": 0.85,
        "total_epochs": 50,
        "total_crashes": 0,
        "crashes_recovered": 0,
        "actual_training_minutes": 4.5,
    },
    "evaluation": {
        "primary_metric": "auc_roc",
        "primary_metric_value": 0.854,
        "all_metrics": {"auc_roc": 0.854, "accuracy": 0.832, "f1": 0.811},
        "decision": "pass",
        "decision_reason": "Metrics exceed threshold",
    },
    "deployment": {
        "endpoint_url": "http://localhost:8080/predict",
        "model_format": "onnx",
        "p95_latency_ms": 45,
    },
}


# ---------------------------------------------------------------------------
# Prediction vs Actual
# ---------------------------------------------------------------------------


def test_metric_within_range():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    comparisons = data["prediction_vs_actual"]
    metric_comp = [c for c in comparisons if c["estimate"] == "metric_range"]
    assert len(metric_comp) == 1
    assert metric_comp[0]["within_range"] is True
    assert "error_pct" in metric_comp[0]


def test_metric_outside_range():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["forge_plan"]["architecture_selected"]["expected_metric_range"] = [0.90, 0.95]
    data = _compute_prediction_vs_actual(data)
    m = [c for c in data["prediction_vs_actual"] if c["estimate"] == "metric_range"][0]
    assert m["within_range"] is False


def test_training_time_comparison():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    t = [c for c in data["prediction_vs_actual"] if c["estimate"] == "training_time"]
    assert len(t) == 1
    assert "error_pct" in t[0]
    assert t[0]["predicted"] == "5 min"


def test_confidence_calibration_pass():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    c = [
        comp
        for comp in data["prediction_vs_actual"]
        if comp["estimate"] == "confidence_calibration"
    ]
    assert len(c) == 1
    assert c[0]["calibration"] == "well_calibrated"


def test_no_comparisons_when_no_plan():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["scout_analysis"] = {}
    data["forge_plan"] = {}
    data = _compute_prediction_vs_actual(data)
    assert len(data["prediction_vs_actual"]) == 0


def test_no_comparisons_when_no_metric():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["training_outcome"] = {}
    data["evaluation"] = {}
    data["scout_analysis"] = {}
    data = _compute_prediction_vs_actual(data)
    assert len(data["prediction_vs_actual"]) == 0


# ---------------------------------------------------------------------------
# Lessons Learned
# ---------------------------------------------------------------------------


def test_lessons_metric_within_range():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("within predicted range" in l for l in lessons)


def test_lessons_training_time():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("faster" in l or "slower" in l for l in lessons)


def test_lessons_no_crashes():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("No training crashes" in l for l in lessons)


def test_lessons_deployment():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("deployed" in l.lower() for l in lessons)


def test_lessons_escalated():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["status"] = "ESCALATED"
    data["evaluation"]["decision"] = "escalate"
    data = _compute_prediction_vs_actual(data)
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("escalated" in l for l in lessons)


def test_lessons_empty_when_no_data():
    data = _generate_lessons_learned({"status": "unknown"})
    assert isinstance(data["lessons_learned"], list)


def test_lessons_with_failures():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["failures_and_recoveries"] = {
        "error_categories": ["shape_mismatch", "oom"],
        "entries": [
            {
                "exception_type": "ValueError",
                "error_category": "shape_mismatch",
                "repair_strategy": "Re-align feature list",
                "patch_outcome": "success",
                "confidence_score": 0.85,
            },
            {
                "exception_type": "MemoryError",
                "error_category": "oom",
                "repair_strategy": "Reduce batch size 50%",
                "patch_outcome": "rollback",
                "confidence_score": 0.72,
            },
        ],
    }
    data = _compute_prediction_vs_actual(data)
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("shape_mismatch" in l and "repaired" in l for l in lessons)
    assert any("rolled back" in l and "MemoryError" in l for l in lessons)
    assert any("Encountered errors" in l for l in lessons)


def test_lessons_with_experience_comparison():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["experience_comparison"] = {
        "completed": 8,
        "avg_metric": 0.80,
        "best_metric": 0.90,
        "avg_crashes": 2.0,
        "pass_ratio": 0.75,
    }
    data = _compute_prediction_vs_actual(data)
    data = _generate_lessons_learned(data)
    lessons = data["lessons_learned"]
    assert any("outperformed" in l and "0.80" in l for l in lessons) or any(
        "in line with" in l for l in lessons
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def test_markdown_contains_sections():
    data = _compute_prediction_vs_actual(copy.deepcopy(_SAMPLE_REPORT_DATA))
    data = _generate_lessons_learned(data)
    md = _render_markdown(data)
    assert "## 1. Overview" in md
    assert "## 2. Scout Analysis" in md
    assert "## 3. Forge Engineering Plan" in md
    assert "## 4. Training Outcome" in md
    assert "## 5. Evaluation" in md
    assert "## 6. Deployment" in md
    assert "## 7. Prediction vs Actual" in md
    assert "## 8. Lessons Learned" in md


def test_markdown_with_failures_and_experience():
    data = copy.deepcopy(_SAMPLE_REPORT_DATA)
    data["failures_and_recoveries"] = {
        "total_patch_attempts": 2,
        "successful_patches": 1,
        "rollbacks": 1,
        "escalations": 0,
        "error_categories": ["shape_mismatch", "oom"],
        "entries": [
            {
                "exception_type": "ValueError",
                "error_category": "shape_mismatch",
                "repair_strategy": "Re-align feature list",
                "patch_outcome": "success",
                "confidence_score": 0.85,
            },
            {
                "exception_type": "MemoryError",
                "error_category": "oom",
                "repair_strategy": "Reduce batch size 50%",
                "patch_outcome": "rollback",
                "confidence_score": 0.72,
            },
        ],
    }
    data["experience_comparison"] = {
        "total_similar": 10,
        "completed": 8,
        "avg_metric": 0.82,
        "best_metric": 0.90,
        "avg_crashes": 1.5,
        "pass_ratio": 0.75,
        "most_common_architecture": "lightgbm",
    }
    data["lessons_learned"] = ["Shape mismatch repaired by re-aligning features"]
    md = _render_markdown(data)
    assert "## 5. Failures & Recoveries" in md, f"Missing Failures section in:\n{md}"
    assert "## 6. Evaluation" in md
    assert "## 7. Deployment" in md
    assert "## 8. Experience Comparison" in md
    assert "## 9. Lessons Learned" in md
    assert "shape_mismatch" in md
    assert "MemoryError" in md
    assert "Avg crashes per job" in md
    assert "Historical pass ratio" in md


def test_markdown_contains_key_values():
    md = _render_markdown(_SAMPLE_REPORT_DATA)
    assert "lightgbm" in md
    assert "0.854" in md
    assert "http://localhost:8080/predict" in md


def test_markdown_status_icon():
    md = _render_markdown(_SAMPLE_REPORT_DATA)
    assert "COMPLETED" in md or "✅" in md


def test_markdown_escalated():
    data = {**_SAMPLE_REPORT_DATA, "status": "ESCALATED"}
    md = _render_markdown(data)
    assert "ESCALATED" in md


def test_markdown_handles_missing_sections():
    data = {"job_id": "test", "status": "unknown", "created_at": "2026-01-01T00:00:00"}
    md = _render_markdown(data)
    assert "Mission Report" in md


# ---------------------------------------------------------------------------
# Full pipeline with mocked Redis
# ---------------------------------------------------------------------------


def _mock_redis(data: dict) -> AsyncMock:
    client = AsyncMock()

    async def mock_get(key: str):
        key = key.decode() if isinstance(key, bytes) else key
        val = data.get(key)
        if val is not None:
            return json.dumps(val).encode() if isinstance(val, (dict, list)) else str(val).encode()
        return None

    client.get = mock_get
    return client


@pytest.mark.asyncio
async def test_generate_mission_report_writes_json_and_md():
    brief = {
        "problem_description": "Test problem",
        "task_type": "classification",
        "modality": "tabular",
        "dataset": {"file_path": "/data/test.csv", "num_rows": 100, "num_columns": 5},
        "engineering_reasoning": {
            "problem_type": {"title": "PT", "selected": "classification", "confidence": 0.9},
            "overall_confidence": 0.9,
        },
    }
    plan = {
        "architecture_selected": {
            "name": "lightgbm",
            "expected_training_minutes": 3,
            "expected_ram_mb": 256,
            "expected_metric_range": [0.75, 0.88],
        },
    }
    training = {
        "best_val_metric": 0.82,
        "total_epochs": 30,
        "total_crashes_recovered": 0,
    }
    redis_data = {
        "job:job-001:mission_brief": brief,
        "job:job-001:engineering_plan": plan,
        "job:job-001:training_complete": training,
        "job:job-001:status": "COMPLETED",
        "job:job-001:crash_count": 0,
    }
    redis_client = _mock_redis(redis_data)
    deploy_data = {"endpoint_url": "http://localhost:8080/predict", "model_format": "onnx"}

    with patch("orchestrator.mission_report._OUTPUTS_DIR", tempfile.mkdtemp()):
        json_path = await generate_mission_report("job-001", redis_client, deploy_data=deploy_data)
        assert os.path.exists(json_path)
        md_path = json_path.replace(".json", ".md")
        assert os.path.exists(md_path)

        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["job_id"] == "job-001"
        assert report["status"] == "COMPLETED"
        assert report["forge_plan"]["architecture_selected"]["name"] == "lightgbm"
        assert report["deployment"]["endpoint_url"] == "http://localhost:8080/predict"
        assert len(report["lessons_learned"]) > 0


@pytest.mark.asyncio
async def test_generate_mission_report_escalated():
    redis_data = {
        "job:job-001:status": "ESCALATED",
    }
    redis_client = _mock_redis(redis_data)

    with patch("orchestrator.mission_report._OUTPUTS_DIR", tempfile.mkdtemp()):
        json_path = await generate_mission_report("job-001", redis_client)
        assert os.path.exists(json_path)
        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
        assert report["status"] == "ESCALATED"


@pytest.mark.asyncio
async def test_generate_mission_report_silent_on_redis_failure():
    failing_client = AsyncMock()
    failing_client.get.side_effect = Exception("Redis down")

    with patch("orchestrator.mission_report._OUTPUTS_DIR", tempfile.mkdtemp()):
        json_path = await generate_mission_report("job-001", failing_client)
        assert os.path.exists(json_path)
        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
        assert "error" not in report
        assert report["job_id"] == "job-001"

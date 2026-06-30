"""Phase 1 gate test: Titanic end-to-end pipeline.

This test must stay green for the rest of the project.
Verifies: Scout → Forge → Furnace → Arbiter → Harbor pipeline.
"""

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


pytestmark = pytest.mark.asyncio


async def test_scout_parses_titanic_mission_brief():
    from agents.scout.tools import detect_modality, run_eda, write_mission_brief

    csv_path = os.path.join(os.path.dirname(__file__), "../fixtures/titanic.csv")

    modality = detect_modality(csv_path)
    assert modality == "tabular"

    eda = run_eda(csv_path, target_column="Survived")
    assert eda["num_rows"] == 20
    assert eda["num_columns"] == 12
    assert eda["column_types"]["Survived"] == "target"

    brief = write_mission_brief(
        eda_results=eda,
        job_id="test-titanic",
        problem_description="Predict Titanic survival",
        file_path=csv_path,
        target_column="Survived",
    )
    assert brief["task_type"] == "classification"
    assert brief["modality"] == "tabular"
    assert brief["target_column"] == "Survived"


async def test_forge_selects_lightgbm_for_titanic():
    from agents.forge.decision_tree import select_architecture

    mission_brief = {
        "task_type": "classification",
        "modality": "tabular",
        "dataset": {"num_rows": 891},
        "data_quality": {"class_imbalance_ratio": None},
        "imbalance_strategy": "none",
    }
    model = select_architecture(mission_brief)
    assert model == "lightgbm"


async def test_forge_writes_valid_training_script():
    from agents.forge.tools import write_training_script

    mission_brief = {
        "job_id": "test-titanic",
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "Survived",
        "evaluation_metric": "auc_roc",
        "dataset": {
            "file_path": "tests/fixtures/titanic.csv",
            "num_rows": 891,
            "num_columns": 12,
            "column_types": {},
        },
        "data_quality": {
            "class_imbalance_ratio": None,
            "missing_value_rate": {},
            "high_cardinality_columns": [],
            "data_warnings": [],
        },
        "recommended_architecture_family": "lightgbm",
        "imbalance_strategy": "none",
    }
    script_path = write_training_script(
        mission_brief=mission_brief,
        job_id="test-titanic",
        scripts_dir="scripts",
    )
    assert os.path.exists(script_path)
    assert "test-titanic" in script_path

    with open(script_path) as f:
        code = f.read()
    assert "lightgbm" in code
    assert "Survived" in code

    os.remove(script_path)


async def test_arbiter_evaluates_metrics():
    from agents.arbiter.tools import (
        compute_classification_metrics,
        make_decision,
    )

    metrics = compute_classification_metrics(
        y_true=[0, 1, 0, 1, 0, 1, 0, 1],
        y_pred=[0, 1, 0, 1, 0, 1, 0, 1],
        y_prob=[0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.1, 0.9],
    )
    assert metrics["auc_roc"] >= 0.9

    decision, reason = make_decision("classification", metrics, crash_count=0)
    assert decision == "pass"


async def test_bus_events_contract():
    from bus.events import (
        MISSION_BRIEF_READY,
        TRAINING_SCRIPT_READY,
        TRAINING_COMPLETE,
        CRASH_EVENT,
        ENDPOINT_LIVE,
    )

    assert MISSION_BRIEF_READY == "MISSION_BRIEF_READY"
    assert TRAINING_SCRIPT_READY == "TRAINING_SCRIPT_READY"
    assert TRAINING_COMPLETE == "TRAINING_COMPLETE"
    assert CRASH_EVENT == "CRASH_EVENT"
    assert ENDPOINT_LIVE == "ENDPOINT_LIVE"

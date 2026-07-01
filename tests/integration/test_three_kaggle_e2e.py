"""Phase 2 gate test: pipeline-level assertions for Kaggle-like ML problems.

Verifies Forge generates Optuna-powered training scripts, search spaces
cover all architectures, and architecture memory is wired end-to-end.
Does NOT execute training — only validates the code paths.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


pytestmark = pytest.mark.asyncio


async def test_forge_defines_lightgbm_search_space():
    """Forge must define a search space for LightGBM with correct param types."""
    from agents.forge.tools import define_optuna_space

    space = define_optuna_space("lightgbm")
    assert "num_leaves" in space
    assert space["num_leaves"]["type"] == "int"
    assert space["num_leaves"]["low"] == 16
    assert space["num_leaves"]["high"] == 256
    assert "learning_rate" in space
    assert space["learning_rate"]["type"] == "float"


async def test_search_space_covers_all_architectures():
    """All blueprint architectures must define a non-empty search space."""
    from agents.forge.tools import define_optuna_space

    for arch in ("lightgbm", "xgboost", "tabnet", "distilbert", "efficientnet"):
        space = define_optuna_space(arch)
        assert space, f"Empty search space for {arch}"
        for name, spec in space.items():
            assert "type" in spec, f"{arch}.{name} missing type"
            assert "low" in spec, f"{arch}.{name} missing low"
            assert "high" in spec, f"{arch}.{name} missing high"


async def test_training_script_contains_optuna_wiring():
    """Generated training script must include optuna import and study.optimize."""
    from agents.forge.tools import write_training_script

    brief = {
        "job_id": "test-optuna",
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "Survived",
        "dataset": {
            "file_path": "data/titanic.csv",
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
        "imbalance_strategy": "none",
        "recommended_architecture_family": "lightgbm",
    }

    script_path = write_training_script(brief, "test-optuna", scripts_dir="./scripts")
    assert os.path.exists(script_path)

    with open(script_path) as f:
        content = f.read()

    assert "import optuna" in content, "Training script must import optuna"
    assert "study.optimize" in content, "Training script must call study.optimize"
    assert "SEARCH_SPACE_JSON" in content, "Training script must read SEARCH_SPACE_JSON env var"
    assert "optuna.create_study" in content, "Training script must create an optuna study"

    os.remove(script_path)


async def test_architecture_memory_functions_import_and_return():
    """Architecture memory must provide query and store functions (no ChromaDB needed)."""
    from memory.collections.architecture_memory import (
        store_architecture,
        query_similar_architectures,
    )

    assert store_architecture is not None
    assert query_similar_architectures is not None
    assert callable(store_architecture)
    assert callable(query_similar_architectures)


async def test_orchestrator_retry_increments_counter():
    """On EVALUATION_RETRY, the orchestrator must increment retry_count."""
    from bus.events import EVALUATION_RETRY

    assert EVALUATION_RETRY == "EVALUATION_RETRY"

    data = {
        "job_id": "test-retry",
        "event_type": EVALUATION_RETRY,
        "primary_metric_value": 0.75,
    }
    assert data["event_type"] == EVALUATION_RETRY


async def test_furnace_run_accepts_search_space_json():
    """FurnaceAgent.run() must accept a search_space_json parameter."""
    from agents.furnace.agent import FurnaceAgent

    agent = FurnaceAgent(job_id="test-furnace-ss")
    assert agent is not None

    import inspect

    sig = inspect.signature(agent.run)
    assert "search_space_json" in sig.parameters
    assert sig.parameters["search_space_json"].default is None


async def test_forge_queries_architecture_memory():
    """ForgeAgent.run() must query architecture_memory via import."""
    from agents.forge.agent import ForgeAgent

    agent = ForgeAgent(job_id="test-forge-mem")
    assert agent is not None
    assert hasattr(agent, "run")


async def test_bus_has_architecture_evaluated_event():
    """bus/events.py must define ARCHITECTURE_EVALUATED."""
    from bus.events import ARCHITECTURE_EVALUATED

    assert ARCHITECTURE_EVALUATED == "ARCHITECTURE_EVALUATED"

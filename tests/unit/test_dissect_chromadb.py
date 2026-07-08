"""Unit tests for Dissect ↔ ChromaDB patch_memory integration.

Verifies that Dissect.handle_crash calls query_similar_patches before the LLM
call and store_patch after determining the patch outcome.
"""

import os
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


@pytest.fixture
def crash_event():
    return {
        "job_id": "test-dissect-chromadb",
        "exception_type": "ValueError",
        "exception_message": "X has 45 features, model expects 40",
        "traceback": 'Traceback\n  File "train.py", line 42, in fit\n    model.fit(X, y)\nValueError: X has 45 features, model expects 40',
        "script_path": "scripts/training_script_test-dissect-chromadb.py",
        "last_checkpoint_path": "",
        "epoch_at_crash": "0",
        "crash_attempt_number": "1",
    }


@pytest.fixture
def script_path(tmp_path):
    path = os.path.join(tmp_path, "training_script.py")
    with open(path, "w") as f:
        f.write("import pandas as pd\n\ndef train():\n    pass\n")
    return path


@pytest.mark.asyncio
async def test_dissect_queries_similar_patches_before_llm(crash_event, script_path):
    """Dissect should call query_similar_patches before generating a patch."""
    crash_event["script_path"] = script_path

    from agents.dissect.agent import DissectAgent

    agent = DissectAgent(job_id=crash_event["job_id"])
    agent.redis = MagicMock()
    agent.redis._client = AsyncMock()
    agent.redis._client.get = AsyncMock(return_value=None)
    agent.redis._client.setex = AsyncMock()
    agent.redis._client.rpush = AsyncMock()
    agent.call_llm = AsyncMock(
        return_value={"text": "import pandas as pd\n\ndef train():\n    pass\n"}
    )

    with (
        patch(
            "memory.collections.patch_memory.query_similar_patches",
            return_value=[
                {
                    "patch_id": "p1",
                    "similarity_score": 0.85,
                    "category": "shape_mismatch",
                    "outcome": "success",
                    "repair_strategy": "re-align feature list",
                }
            ],
        ) as mock_query,
        patch(
            "agents.dissect.agent.store_patch",
        ),
        patch(
            "agents.dissect.agent.run_sandbox_test",
            return_value=(True, "All good"),
        ),
        patch(
            "agents.dissect.agent.write_patch_log",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.agent.publish",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.repair_cache.cache_lookup",
            return_value=None,
        ),
        patch(
            "agents.dissect.repair_templates.find_matching_templates",
            return_value=[],
        ),
    ):
        await agent.handle_crash(crash_event)

    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args[1]
    assert "error_text" in call_kwargs
    assert call_kwargs["category"] == "shape_mismatch"
    assert call_kwargs["k"] == 3


@pytest.mark.asyncio
async def test_dissect_stores_patch_after_success(crash_event, script_path):
    """Dissect should call store_patch with outcome=success after a successful patch."""
    crash_event["script_path"] = script_path

    from agents.dissect.agent import DissectAgent

    agent = DissectAgent(job_id=crash_event["job_id"])
    agent.redis = MagicMock()
    agent.redis._client = AsyncMock()
    agent.redis._client.get = AsyncMock(return_value=None)
    agent.redis._client.setex = AsyncMock()
    agent.redis._client.rpush = AsyncMock()
    agent.call_llm = AsyncMock(
        return_value={"text": "import pandas as pd\n\ndef train():\n    pass\n"}
    )

    with (
        patch(
            "memory.collections.patch_memory.query_similar_patches",
            return_value=[],
        ),
        patch(
            "agents.dissect.agent.store_patch",
        ) as mock_store,
        patch(
            "agents.dissect.agent.run_sandbox_test",
            return_value=(True, "All good"),
        ),
        patch(
            "agents.dissect.agent.write_patch_log",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.agent.publish",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.repair_cache.cache_lookup",
            return_value=None,
        ),
        patch(
            "agents.dissect.repair_templates.find_matching_templates",
            return_value=[],
        ),
    ):
        await agent.handle_crash(crash_event)

    mock_store.assert_called_once()
    call_kwargs = mock_store.call_args[1]
    assert call_kwargs["outcome"] == "success"
    assert call_kwargs["job_id"] == "test-dissect-chromadb"
    assert call_kwargs["category"] == "shape_mismatch"
    assert call_kwargs["repair_strategy"] is not None


@pytest.mark.asyncio
async def test_dissect_stores_patch_after_escalation(crash_event, script_path):
    """Dissect should call store_patch with 'escalated' after 3 failed attempts."""
    crash_event["script_path"] = script_path
    crash_event["crash_attempt_number"] = "3"

    from agents.dissect.agent import DissectAgent

    agent = DissectAgent(job_id=crash_event["job_id"])
    agent.redis = MagicMock()
    agent.redis._client = AsyncMock()
    agent.redis._client.get = AsyncMock(return_value=None)
    agent.redis._client.setex = AsyncMock()
    agent.redis._client.rpush = AsyncMock()
    agent.call_llm = AsyncMock(
        return_value={"text": "import pandas as pd\n\ndef train():\n    pass\n"}
    )

    with (
        patch(
            "memory.collections.patch_memory.query_similar_patches",
            return_value=[],
        ),
        patch(
            "agents.dissect.agent.store_patch",
        ) as mock_store,
        patch(
            "agents.dissect.agent.run_sandbox_test",
            return_value=(False, "Still broken"),
        ),
        patch(
            "agents.dissect.agent.write_patch_log",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.agent.publish",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.repair_cache.cache_lookup",
            return_value=None,
        ),
        patch(
            "agents.dissect.repair_templates.find_matching_templates",
            return_value=[],
        ),
    ):
        await agent.handle_crash(crash_event)

    # store_patch should be called twice: once with "rollback", once with "escalated"
    assert mock_store.call_count >= 2
    outcomes = [call.kwargs["outcome"] for call in mock_store.call_args_list]
    assert "escalated" in outcomes


@pytest.mark.asyncio
async def test_dissect_stores_patch_after_rollback(crash_event, script_path):
    """Dissect should call store_patch with outcome=rollback after each failed attempt."""
    crash_event["script_path"] = script_path
    crash_event["crash_attempt_number"] = "1"

    from agents.dissect.agent import DissectAgent

    agent = DissectAgent(job_id=crash_event["job_id"])
    agent.redis = MagicMock()
    agent.redis._client = AsyncMock()
    agent.redis._client.get = AsyncMock(return_value=None)
    agent.redis._client.setex = AsyncMock()
    agent.redis._client.rpush = AsyncMock()
    agent.call_llm = AsyncMock(
        return_value={"text": "import pandas as pd\n\ndef train():\n    pass\n"}
    )

    with (
        patch(
            "memory.collections.patch_memory.query_similar_patches",
            return_value=[],
        ),
        patch(
            "agents.dissect.agent.store_patch",
        ) as mock_store,
        patch(
            "agents.dissect.agent.run_sandbox_test",
            return_value=(False, "Script still fails"),
        ),
        patch(
            "agents.dissect.agent.write_patch_log",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.agent.publish",
            new_callable=AsyncMock,
        ),
        patch(
            "agents.dissect.agent.rollback_patch",
            return_value=True,
        ),
        patch(
            "agents.dissect.repair_cache.cache_lookup",
            return_value=None,
        ),
        patch(
            "agents.dissect.repair_templates.find_matching_templates",
            return_value=[],
        ),
    ):
        agent._escalate = AsyncMock()
        await agent.handle_crash(crash_event)

    assert mock_store.call_count >= 1
    any_rollback = any(call.kwargs["outcome"] == "rollback" for call in mock_store.call_args_list)
    assert any_rollback, "At least one store_patch call should have outcome=rollback"

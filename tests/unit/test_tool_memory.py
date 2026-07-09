"""Unit tests for tool_memory ChromaDB collection."""

import uuid
from unittest.mock import patch, MagicMock

from memory.collections.tool_memory import store_tool, query_tools, register_agent_tools


@patch("memory.collections.tool_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_store_tool_success(mock_get_model, mock_chroma):
    """store_tool should encode docstring and add to ChromaDB."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.5, 0.5])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    tool_id = str(uuid.uuid4())
    store_tool(
        tool_id=tool_id,
        agent_name="Scout",
        tool_name="detect_modality",
        docstring="Detect the modality of a dataset from its file path.",
        source_file="agents.scout.tools",
    )

    mock_model.encode.assert_called_once()
    mock_collection.upsert.assert_called_once()
    args, kwargs = mock_collection.upsert.call_args
    assert kwargs["ids"] == [tool_id]
    assert kwargs["metadatas"][0]["tool_name"] == "detect_modality"
    assert kwargs["metadatas"][0]["agent_name"] == "Scout"


@patch("memory.collections.tool_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_query_tools_returns_list(mock_get_model, mock_chroma):
    """query_tools should return list of tool dicts sorted by similarity."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.5, 0.5])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["t1", "t2"]],
        "metadatas": [
            [
                {"tool_name": "detect_modality", "agent_name": "Scout"},
                {"tool_name": "select_architecture", "agent_name": "Forge"},
            ]
        ],
        "distances": [[0.1, 0.3]],
        "documents": [["Detect modality docstring", "Select architecture docstring"]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_tools("find dataset type", k=2)

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["tool_name"] == "detect_modality"
    assert results[0]["similarity_score"] == 0.9


@patch("memory.collections.tool_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_query_tools_empty_when_no_match(mock_get_model, mock_chroma):
    """query_tools returns empty list when ChromaDB has no matches."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.5, 0.5])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "metadatas": None, "distances": [[]]}
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_tools("nonexistent tool", k=5)
    assert results == []


@patch("memory.collections.tool_memory.store_tool")
def test_register_agent_tools_scout(mock_store_tool):
    """register_agent_tools should call store_tool for each public function with a docstring."""
    mock_store_tool.return_value = None

    count = register_agent_tools("Scout", "agents.scout.tools")

    assert count > 0
    assert mock_store_tool.call_count == count
    # Verify at least one known tool was registered
    tool_names = [call.kwargs["tool_name"] for call in mock_store_tool.call_args_list]
    assert "detect_modality" in tool_names
    assert "run_eda" in tool_names
    assert "write_mission_brief" in tool_names


@patch("memory.collections.tool_memory.store_tool")
def test_register_agent_tools_forge(mock_store_tool):
    """register_agent_tools should register Forge tools."""
    mock_store_tool.return_value = None
    count = register_agent_tools("Forge", "agents.forge.tools")
    assert count > 0
    tool_names = [call.kwargs["tool_name"] for call in mock_store_tool.call_args_list]
    assert "write_training_script" in tool_names
    assert "define_optuna_space" in tool_names


@patch("memory.collections.tool_memory.store_tool")
def test_register_agent_tools_dissect(mock_store_tool):
    """register_agent_tools should register Dissect tools."""
    mock_store_tool.return_value = None
    count = register_agent_tools("Dissect", "agents.dissect.tools")
    assert count > 0
    tool_names = [call.kwargs["tool_name"] for call in mock_store_tool.call_args_list]
    assert "apply_patch" in tool_names
    assert "rollback_patch" in tool_names
    assert "compute_diff" in tool_names
    assert "run_sandbox_test" in tool_names


@patch("memory.collections.tool_memory.store_tool")
def test_register_agent_tools_arbiter(mock_store_tool):
    """register_agent_tools should register Arbiter tools."""
    mock_store_tool.return_value = None
    count = register_agent_tools("Arbiter", "agents.arbiter.tools")
    assert count > 0
    tool_names = [call.kwargs["tool_name"] for call in mock_store_tool.call_args_list]
    assert "compute_classification_metrics" in tool_names
    assert "make_decision" in tool_names


@patch("memory.collections.tool_memory.store_tool")
def test_register_agent_tools_graceful_on_bad_module(mock_store_tool):
    """register_agent_tools returns 0 for non-existent module without raising."""
    count = register_agent_tools("Ghost", "agents.ghost.tools")
    assert count == 0

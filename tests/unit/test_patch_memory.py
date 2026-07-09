"""Unit tests for patch_memory ChromaDB collection."""

import uuid
from unittest.mock import patch, MagicMock

from memory.collections.patch_memory import store_patch, query_similar_patches


@patch("memory.collections.patch_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_store_patch_success(mock_get_model, mock_chroma):
    """store_patch should encode text and add to ChromaDB collection."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    patch_id = str(uuid.uuid4())
    store_patch(
        patch_id=patch_id,
        job_id="test-job",
        exception_type="ValueError",
        exception_message="X has 45 features, model expects 40",
        category="shape_mismatch",
        repair_strategy="re-align feature list",
        diff_applied="--- original\n+++ patched\n@@ -1,3 +1,3 @@",
        outcome="success",
    )

    mock_model.encode.assert_called_once()
    mock_collection.upsert.assert_called_once()
    args, kwargs = mock_collection.upsert.call_args
    # ID is now a content hash (deterministic), not the passed patch_id
    assert len(kwargs["ids"][0]) == 32, "ID should be a SHA-256 hex digest (32 chars)"
    assert kwargs["metadatas"][0]["category"] == "shape_mismatch"
    assert kwargs["metadatas"][0]["outcome"] == "success"


@patch("memory.collections.patch_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_store_patch_outcome_escalated(mock_get_model, mock_chroma):
    """store_patch should record escalated outcomes."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    store_patch(
        patch_id=str(uuid.uuid4()),
        job_id="test-job",
        exception_type="RuntimeError",
        exception_message="CUDA OOM",
        category="cuda_oom",
        repair_strategy="halve batch size",
        diff_applied="diff...",
        outcome="escalated",
    )

    args, kwargs = mock_collection.upsert.call_args
    assert kwargs["metadatas"][0]["outcome"] == "escalated"


@patch("memory.collections.patch_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_query_similar_patches_returns_list(mock_get_model, mock_chroma):
    """query_similar_patches should return a list of patch dicts."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["p1", "p2"]],
        "metadatas": [
            [
                {"category": "shape_mismatch", "outcome": "success", "repair_strategy": "re-align"},
                {
                    "category": "shape_mismatch",
                    "outcome": "rollback",
                    "repair_strategy": "drop cols",
                },
            ]
        ],
        "distances": [[0.15, 0.35]],
        "documents": [["", ""]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_similar_patches("ValueError: shape mismatch", k=2)

    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["patch_id"] == "p1"
    assert results[0]["category"] == "shape_mismatch"
    assert results[0]["outcome"] == "success"
    assert results[0]["similarity_score"] == 0.85  # 1.0 - 0.15
    assert results[1]["patch_id"] == "p2"
    assert results[1]["similarity_score"] == 0.65  # 1.0 - 0.35


@patch("memory.collections.patch_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_query_similar_patches_empty_when_no_results(mock_get_model, mock_chroma):
    """query_similar_patches should return empty list when ChromaDB returns nothing."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {"ids": [[]], "metadatas": None, "distances": [[]]}
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    results = query_similar_patches("Novel error never seen before", k=3)
    assert results == []


@patch("memory.collections.patch_memory.ChromaClient")
@patch("memory.embeddings.get_embedding_model")
def test_query_similar_patches_with_category_filter(mock_get_model, mock_chroma):
    """query_similar_patches should pass category filter to ChromaDB query."""
    import numpy as np

    mock_model = MagicMock()
    mock_model.encode.return_value = np.array([0.1, 0.2, 0.3])
    mock_get_model.return_value = mock_model

    mock_collection = MagicMock()
    mock_collection.query.return_value = {
        "ids": [["p1"]],
        "metadatas": [[{"category": "shape_mismatch"}]],
        "distances": [[0.1]],
    }
    mock_chroma_instance = MagicMock()
    mock_chroma_instance.get_or_create_collection.return_value = mock_collection
    mock_chroma.return_value = mock_chroma_instance

    query_similar_patches("ValueError: shape", category="shape_mismatch", k=1)

    call_kwargs = mock_collection.query.call_args[1]
    assert call_kwargs["where"] == {"category": "shape_mismatch"}


@patch("memory.collections.patch_memory.ChromaClient")
def test_store_patch_silent_on_embedding_failure(mock_chroma):
    """store_patch should not raise when embedding fails."""
    with patch(
        "memory.embeddings.get_embedding_model",
        return_value=None,
    ):
        store_patch(
            patch_id=str(uuid.uuid4()),
            job_id="test-job",
            exception_type="ValueError",
            exception_message="test",
            category="novel_error",
            repair_strategy="manual",
            diff_applied="",
            outcome="success",
        )

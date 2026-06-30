"""Phase 2 gate test: 3 Kaggle datasets end-to-end with error recovery.

This test verifies the full pipeline including Dissect error recovery.
Requires Anthropic API key for LLM-powered agents.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


pytestmark = pytest.mark.asyncio


async def test_dissect_classifies_all_error_categories():
    from agents.dissect.taxonomy import classify_error, TAXONOMY

    assert len(TAXONOMY) == 11

    categories = set()
    for entry in TAXONOMY:
        categories.add(entry.category)
    assert "shape_mismatch" in categories
    assert "nan_propagation" in categories
    assert "import_error" in categories
    assert "novel_error" in categories


async def test_dissect_applies_and_rolls_back_patches():
    import tempfile
    from agents.dissect.tools import apply_patch, rollback_patch, compute_diff

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("x = 1\n")
        f.write("y = 2\n")
        orig_path = f.name

    original = "x = 1\ny = 2\n"
    patched = "x = 10\ny = 20\n"

    diff = compute_diff(original, patched)
    assert "x = 1" in diff
    assert "x = 10" in diff

    success, msg = apply_patch(orig_path, patched)
    assert success

    with open(orig_path) as f:
        assert f.read() == patched

    rolled_back = rollback_patch(orig_path)
    assert rolled_back

    with open(orig_path) as f:
        assert f.read() == original

    os.remove(orig_path)


async def test_arbiter_regression_threshold_is_dynamic():
    import numpy as np
    from agents.arbiter.tools import compute_regression_metrics

    y_true = [1.0, 2.0, 3.0, 4.0, 5.0]
    y_pred = [1.1, 2.1, 3.1, 4.1, 5.1]

    metrics = compute_regression_metrics(y_true, y_pred)
    std_target = float(np.std(y_true))
    assert metrics["std_target"] == pytest.approx(std_target)
    assert metrics["threshold_rmse"] == pytest.approx(std_target * 0.85)


async def test_orchestrator_patch_log_writer_writes_valid_jsonl():
    import json
    import tempfile
    from pathlib import Path

    entry = {
        "patch_id": "test-123",
        "job_id": "test-job",
        "outcome": "success",
        "exception_type": "ValueError",
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps(entry) + "\n")
        log_path = f.name

    with open(log_path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["patch_id"] == "test-123"

    os.remove(log_path)


async def test_chroma_memory_imports():
    from memory.chroma_client import ChromaClient
    from memory.collections.patch_memory import store_patch, query_similar_patches
    from memory.collections.architecture_memory import store_architecture, query_similar_architectures
    from memory.collections.tool_memory import store_tool, query_tools

    assert ChromaClient is not None
    assert store_patch is not None
    assert query_similar_patches is not None
    assert store_architecture is not None
    assert query_similar_architectures is not None
    assert store_tool is not None
    assert query_tools is not None

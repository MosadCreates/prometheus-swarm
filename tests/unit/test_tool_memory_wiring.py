"""Unit tests for tool-memory wiring into Forge — hermetic (no ChromaDB/Redis)."""

from agents.forge.tools import write_training_script
from memory.collections.tool_memory import (
    format_tool_hints,
    retrieve_relevant_tools,
)

TITANIC_BRIEF = {
    "job_id": "toolmem-1",
    "problem_description": "Titanic survival prediction",
    "task_type": "classification",
    "modality": "tabular",
    "target_column": "Survived",
    "evaluation_metric": "auc_roc",
    "dataset": {
        "file_path": "./tests/fixtures/titanic.csv",
        "num_rows": 891,
        "num_columns": 12,
        "column_types": {
            "PassengerId": "numeric",
            "Survived": "target",
            "Pclass": "numeric",
            "Name": "text",
            "Sex": "categorical",
            "Age": "numeric",
        },
    },
    "data_quality": {
        "class_imbalance_ratio": 1.5,
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "data_warnings": [],
    },
    "imbalance_strategy": "none",
}


def _fake_tool(name: str, doc: str, sim: float = 0.9) -> dict:
    return {
        "tool_id": f"Forge:{name}",
        "tool_name": name,
        "agent_name": "Forge",
        "docstring": doc,
        "similarity_score": sim,
    }


class TestFormatToolHints:
    def test_empty_list_returns_empty_string(self):
        assert format_tool_hints([]) == ""

    def test_formats_tool_name_and_doc_head(self):
        tools = [_fake_tool("load_csv", "Load a CSV into a DataFrame.\nSecond line.")]
        text = format_tool_hints(tools)
        assert "Available tools from tool memory:" in text
        assert "- load_csv [Forge]" in text
        assert "Load a CSV into a DataFrame." in text
        assert "Second line." not in text  # only the docstring head is used

    def test_similarity_score_rendered(self):
        tools = [_fake_tool("scale", "Scale numeric features.", sim=0.87)]
        assert "sim 0.87" in format_tool_hints(tools)


class TestRetrieveRelevantTools:
    def test_passthrough(self, monkeypatch):
        fake = [_fake_tool("onehot", "One-hot encode categories.")]
        monkeypatch.setattr(
            "memory.collections.tool_memory.query_tools",
            lambda query, k: fake,
        )
        result = retrieve_relevant_tools("Forge", "encode categorical features", k=5)
        assert result == fake

    def test_failure_returns_empty(self, monkeypatch):
        def boom(query, k):
            raise RuntimeError("ChromaDB down")

        monkeypatch.setattr("memory.collections.tool_memory.query_tools", boom)
        assert retrieve_relevant_tools("Forge", "anything") == []


class TestForgeIntegration:
    def test_write_training_script_injects_hints(self, tmp_path):
        """tool_memory_hints ride into the rendered script header."""
        hints = "Available tools from tool memory:\n  - load_csv [Forge]: Load a CSV."
        script_path = write_training_script(
            TITANIC_BRIEF,
            "toolmem-1",
            scripts_dir=str(tmp_path),
            architecture="lightgbm",
            design_summary="Architecture: lightgbm",
            redis_client=None,
            confidence=0.99,  # template path (deterministic)
            tool_memory_hints=hints,
        )
        with open(script_path, encoding="utf-8") as f:
            content = f.read()
        assert "Available tools from tool memory:" in content
        assert "load_csv [Forge]" in content

    def test_no_hints_when_param_omitted(self, tmp_path):
        script_path = write_training_script(
            TITANIC_BRIEF,
            "toolmem-2",
            scripts_dir=str(tmp_path),
            architecture="lightgbm",
            design_summary="Architecture: lightgbm",
            redis_client=None,
            confidence=0.99,
        )
        with open(script_path, encoding="utf-8") as f:
            content = f.read()
        assert "tool memory" not in content.lower()

    def test_hints_merge_preserves_design_summary(self, tmp_path):
        hints = "Available tools from tool memory:\n  - foo [Forge]: does things"
        script_path = write_training_script(
            TITANIC_BRIEF,
            "toolmem-3",
            scripts_dir=str(tmp_path),
            architecture="lightgbm",
            design_summary="Architecture: lightgbm",
            redis_client=None,
            confidence=0.99,
            tool_memory_hints=hints,
        )
        with open(script_path, encoding="utf-8") as f:
            content = f.read()
        assert "Architecture: lightgbm" in content
        assert "does things" in content

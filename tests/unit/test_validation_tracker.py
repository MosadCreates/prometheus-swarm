"""Tests for research/validation/tracker.py."""

import json
import uuid
from pathlib import Path

import pytest

from research.validation.models import (
    Experiment,
    ExperimentRun,
    ExperimentSet,
    ResearchHypothesis,
)
from research.validation.tracker import (
    delete_experiment_set,
    list_experiment_sets,
    load_experiment,
    load_experiment_set,
    save_experiment,
    save_experiment_set,
)


class TestExperimentSetPersistence:
    def test_save_and_load(self, tmp_path: Path):
        exp_set = ExperimentSet(name="test_save_load")
        exp_set.experiments["H1"] = Experiment(
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun(problem_id="P1"), ExperimentRun(problem_id="P2")],
        )
        path = save_experiment_set(exp_set, directory=str(tmp_path))
        assert path.exists()

        loaded = load_experiment_set(str(path))
        assert loaded.set_id == exp_set.set_id
        assert loaded.name == "test_save_load"
        assert "H1" in loaded.experiments
        assert len(loaded.experiments["H1"].runs) == 2

    def test_save_two_sets(self, tmp_path: Path):
        s1 = ExperimentSet(name="s1")
        s2 = ExperimentSet(name="s2")
        save_experiment_set(s1, directory=str(tmp_path))
        save_experiment_set(s2, directory=str(tmp_path))
        files = list_experiment_sets(directory=str(tmp_path))
        assert len(files) == 2

    def test_list_empty_dir(self, tmp_path: Path):
        files = list_experiment_sets(directory=str(tmp_path))
        assert files == []

    def test_list_nonexistent_dir(self):
        files = list_experiment_sets(directory="/nonexistent/path/xyz")
        assert files == []

    def test_delete_experiment_set(self, tmp_path: Path):
        s = ExperimentSet(name="to_delete")
        save_experiment_set(s, directory=str(tmp_path))
        assert delete_experiment_set(s.set_id, directory=str(tmp_path)) is True
        assert delete_experiment_set(s.set_id, directory=str(tmp_path)) is False

    def test_delete_nonexistent(self, tmp_path: Path):
        assert delete_experiment_set("nonexistent", directory=str(tmp_path)) is False

    def test_round_trip_with_comparisons(self, tmp_path: Path):
        from research.validation.models import ComparisonResult

        exp_set = ExperimentSet(name="comparisons")
        exp_set.comparisons["test_comp"] = ComparisonResult(
            metric_name="duration",
            p_value=0.01,
            effect_size=0.5,
            significant=True,
        )
        path = save_experiment_set(exp_set, directory=str(tmp_path))
        loaded = load_experiment_set(str(path))
        assert "test_comp" in loaded.comparisons
        assert loaded.comparisons["test_comp"].p_value == 0.01

    def test_save_load_unicode(self, tmp_path: Path):
        exp_set = ExperimentSet(name="üñí©ödé")
        path = save_experiment_set(exp_set, directory=str(tmp_path))
        loaded = load_experiment_set(str(path))
        assert loaded.name == "üñí©ödé"

    def test_save_load_metadata(self, tmp_path: Path):
        exp_set = ExperimentSet(
            name="metadata_test",
            git_commit="abc123",
            git_branch="main",
            python_version="3.11",
            mission_spec_version="1.0",
            execution_plan_version="1.0",
            planner_version="2.0",
        )
        path = save_experiment_set(exp_set, directory=str(tmp_path))
        loaded = load_experiment_set(str(path))
        assert loaded.git_commit == "abc123"
        assert loaded.python_version == "3.11"
        assert loaded.planner_version == "2.0"

    def test_save_experiment_legacy(self, tmp_path: Path):
        exp = Experiment(
            name="legacy",
            hypothesis=ResearchHypothesis.H2,
            runs=[ExperimentRun(problem_id="P1")],
        )
        path = save_experiment(exp, directory=str(tmp_path))
        assert path.exists()
        loaded = load_experiment(str(path))
        assert loaded.name == "legacy"
        assert loaded.hypothesis == ResearchHypothesis.H2
        assert len(loaded.runs) == 1

    def test_files_are_valid_json(self, tmp_path: Path):
        exp_set = ExperimentSet(name="valid_json")
        save_experiment_set(exp_set, directory=str(tmp_path))
        path = tmp_path / f"{exp_set.set_id}.json"
        data = json.loads(path.read_text())
        assert data["name"] == "valid_json"
        assert "set_id" in data

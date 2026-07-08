"""Tests for research/validation/reports.py."""

import json
from pathlib import Path

import pytest

from research.validation.models import (
    ComparisonResult,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    FailureReport,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)
from research.validation.reports import (
    generate_report,
    generate_summary_json,
    save_report_to_disk,
)


class TestGenerateReport:
    def test_empty_set(self):
        exp_set = ExperimentSet(name="empty")
        report = generate_report(exp_set)
        assert "Research Validation Report" in report
        assert "empty" in report

    def test_with_experiments(self):
        exp_set = ExperimentSet(name="test")
        exp_set.experiments["H1"] = Experiment(
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun(problem_id="P1")],
        )
        report = generate_report(exp_set)
        assert "H1" in report
        assert "Static Planner" in report

    def test_with_comparisons(self):
        exp_set = ExperimentSet(name="comps")
        exp_set.comparisons["RQ1_H1_vs_H2_duration"] = ComparisonResult(
            metric_name="duration",
            mean_a=10.0,
            mean_b=5.0,
            p_value=0.01,
            effect_size=1.2,
            effect_size_name="Cohen's d (large)",
            significant=True,
            ci_lower=2.0,
            ci_upper=8.0,
        )
        report = generate_report(exp_set)
        assert "p-value" in report
        assert "SIGNIFICANT" in report or "significant" in report or "Yes" in report

    def test_with_failure_report(self):
        exp_set = ExperimentSet(name="failures")
        fr = FailureReport(
            total_failed=3,
            categories={"training_failure": 2, "dataset_issue": 1},
            category_percentages={"training_failure": 66.7, "dataset_issue": 33.3},
        )
        report = generate_report(exp_set, failure_report=fr)
        assert "Failure Analysis" in report
        assert "training_failure" in report

    def test_with_figures(self, tmp_path: Path):
        exp_set = ExperimentSet(name="figs")
        fig_path = tmp_path / "research" / "figures" / "test_fig.png"
        fig_path.parent.mkdir(parents=True)
        fig_path.write_text("fake")
        report = generate_report(exp_set, figure_paths=[fig_path])
        assert "![test_fig]" in report

    def test_with_reproducibility(self):
        exp_set = ExperimentSet(
            name="repro",
            git_commit="abc123def456",
            git_branch="main",
            python_version="3.11.0",
            configuration_hash="cfg_hash_xyz",
            planner_version="2.0.0",
            mission_spec_version="1.0",
            execution_plan_version="1.0",
        )
        report = generate_report(exp_set)
        assert "Git commit" in report

    def test_with_custom_title(self):
        exp_set = ExperimentSet(name="custom")
        report = generate_report(exp_set, title="Custom Report Title")
        assert "Custom Report Title" in report


class TestGenerateSummaryJSON:
    def test_empty_set(self):
        exp_set = ExperimentSet(name="test")
        summary = generate_summary_json(exp_set)
        assert "generated_at" in summary
        assert summary["name"] == "test"

    def test_with_figures(self):
        exp_set = ExperimentSet(name="figs")
        summary = generate_summary_json(exp_set, figure_paths=[Path("fig1.png")])
        assert "figures" in summary
        assert "fig1.png" in summary["figures"][0]

    def test_with_data(self):
        exp_set = ExperimentSet(name="data")
        exp_set.experiments["H1"] = Experiment(
            hypothesis=ResearchHypothesis.H1,
            runs=[ExperimentRun(problem_id="P1")],
        )
        summary = generate_summary_json(exp_set)
        assert "hypotheses" in summary
        assert "H1" in summary["hypotheses"]


class TestSaveReportToDisk:
    def test_saves_md_and_json(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        monkeypatch.chdir(tmp_path)
        exp_set = ExperimentSet(name="save_test")
        md_path, json_path = save_report_to_disk(exp_set)
        assert md_path.exists()
        assert json_path.exists()
        md_content = md_path.read_text()
        json_content = json.loads(json_path.read_text())
        assert "save_test" in md_content
        assert json_content["name"] == "save_test"

"""Tests for research/validation/figures.py.

Note: These tests verify that figure generation runs without errors
and returns valid Path objects. Visual correctness is not tested.
"""

from pathlib import Path

import pytest

from research.validation.figures import (
    fig_crash_comparison,
    fig_deployment_success,
    fig_duration_comparison,
    fig_final_metric,
    fig_planner_calibration,
    generate_all_figures,
)
from research.validation.models import (
    ExperimentRun,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)


def _make_runs(
    count: int, duration: float = 10.0, metric: float = 0.85, success: bool = True, crashes: int = 0
) -> list[ExperimentRun]:
    return [
        ExperimentRun(
            problem_id=f"P{i}",
            system_metrics=SystemMetrics(duration_seconds=duration, crashes=crashes),
            research_metrics=ResearchMetrics(
                final_metric=metric,
                deployment_success=success,
                actual_success=success,
            ),
        )
        for i in range(count)
    ]


class TestFiguresSmoke:
    def test_duration_comparison(self):
        p = fig_duration_comparison(
            _make_runs(3, duration=5.0),
            _make_runs(3, duration=10.0),
            _make_runs(3, duration=15.0),
        )
        assert p.exists()
        assert p.suffix == ".png"

    def test_deployment_success(self):
        p = fig_deployment_success(
            _make_runs(3, success=True),
            _make_runs(3, success=False),
            _make_runs(3, success=True),
        )
        assert p.exists()

    def test_final_metric(self):
        p = fig_final_metric(
            _make_runs(3, metric=0.7),
            _make_runs(3, metric=0.8),
            _make_runs(3, metric=0.9),
        )
        assert p.exists()

    def test_crash_comparison(self):
        p = fig_crash_comparison(
            _make_runs(3, crashes=0),
            _make_runs(3, crashes=2),
            _make_runs(3, crashes=1),
        )
        assert p.exists()

    def test_planner_calibration_no_data(self):
        runs = [ExperimentRun()]
        p = fig_planner_calibration(runs)
        assert p.exists()

    def test_planner_calibration_with_data(self):
        runs = []
        for i in range(5):
            run = ExperimentRun(
                problem_id=f"P{i}",
                system_metrics=SystemMetrics(duration_seconds=(i + 1) * 60),
            )
            from research.validation.models import PlanningCalibration

            run.calibration = PlanningCalibration(
                predicted_duration_minutes=i + 1,
                actual_duration_minutes=(i + 1) * 1.2,
                planner_confidence=0.8,
                actual_deployment_success=True,
            )
            runs.append(run)
        p = fig_planner_calibration(runs)
        assert p.exists()

    def test_generate_all_figures(self):
        paths = generate_all_figures(
            _make_runs(3),
            _make_runs(3),
            _make_runs(3),
        )
        assert len(paths) == 10
        for p in paths:
            assert p.exists()
            assert p.suffix == ".png"

    def test_empty_data_generates_placeholders(self):
        paths = generate_all_figures([], [], [])
        assert len(paths) == 10
        for p in paths:
            assert p.exists()

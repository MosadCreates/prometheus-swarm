"""Research Validation Framework — Milestone 6.

A read-only evaluation layer operating on experiment artifacts
(Redis keys, baseline JSONs, ChromaDB queries). Produces metrics,
figures, reports, and statistical comparisons without modifying
agents, orchestrator, or planner.
"""

from research.validation.models import (
    ArchitectureSelectionAccuracy,
    ComparisonResult,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    FailureCategory,
    FailureReport,
    LearningCurvePoint,
    PlanningCalibration,
    ResearchHypothesis,
    ResearchMetrics,
    ResearchQuestion,
    SystemMetrics,
)
from research.validation.metrics import (
    aggregate_research_metrics,
    aggregate_system_metrics,
    compute_research_metrics,
    compute_system_metrics,
    summarize_experiment,
    summarize_set,
)
from research.validation.statistics import (
    bootstrap_ci,
    cliffs_delta,
    cohens_d,
    compare_all,
    compare_experiments,
)
from research.validation.tracker import (
    save_experiment_set,
    load_experiment_set,
    list_experiment_sets,
)
from research.validation.failures import (
    classify_failure,
    generate_failure_report,
)
from research.validation.figures import (
    generate_all_figures,
)

__all__ = [
    "ArchitectureSelectionAccuracy",
    "ComparisonResult",
    "Experiment",
    "ExperimentRun",
    "ExperimentSet",
    "FailureCategory",
    "FailureReport",
    "LearningCurvePoint",
    "PlanningCalibration",
    "ResearchHypothesis",
    "ResearchMetrics",
    "ResearchQuestion",
    "SystemMetrics",
    "aggregate_research_metrics",
    "aggregate_system_metrics",
    "bootstrap_ci",
    "cliffs_delta",
    "cohens_d",
    "compare_all",
    "compare_experiments",
    "compute_research_metrics",
    "compute_system_metrics",
    "save_experiment_set",
    "load_experiment_set",
    "list_experiment_sets",
    "classify_failure",
    "generate_failure_report",
    "generate_all_figures",
    "summarize_experiment",
    "summarize_set",
]

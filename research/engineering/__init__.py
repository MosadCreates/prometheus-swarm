"""Engineering improvement dashboard — post-benchmark analysis and reporting.

This module produces 9 deliverable files that measure template quality,
Forge reliability, Dissect effectiveness, LLM usage, knowledge progress,
performance profiling, and before/after benchmark comparisons.

Key data sources:
  - research/validation/models.py → ExperimentSet from benchmark runs
  - research/patch_log.jsonl → Dissect patch attempt records
  - research/benchmark/problems.json → Problem definitions
  - research/benchmark/results/*.json → Raw benchmark results
"""

from research.engineering.models import (
    BenchmarkComparison,
    BenchmarkConfig,
    DissectEffectiveness,
    EngineeringSummary,
    ForgeReliability,
    KnowledgeProgress,
    LlmUsage,
    PatchLogEntry,
    PerformanceProfile,
    RootCauseReport,
    TemplateQuality,
)
from research.engineering.reports import generate_all_reports

__all__ = [
    "BenchmarkComparison",
    "BenchmarkConfig",
    "DissectEffectiveness",
    "EngineeringSummary",
    "ForgeReliability",
    "KnowledgeProgress",
    "LlmUsage",
    "PatchLogEntry",
    "PerformanceProfile",
    "RootCauseReport",
    "TemplateQuality",
    "generate_all_reports",
]

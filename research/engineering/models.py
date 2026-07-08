"""Engineering improvement dashboard — Pydantic models for all 9 deliverables.

These models are distinct from research/validation/models.py. They track
engineering metrics (template quality, Forge cascade hits, Dissect patch
effectiveness, LLM cost, ChromaDB growth) rather than research hypotheses.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PatchOutcome(str, Enum):
    success = "success"
    rollback = "rollback"
    escalated = "escalated"


class CascadeLevel(str, Enum):
    rule = "level0_rule"
    template = "level1_template"
    cache = "level2_cache"
    memory = "level3_memory"
    llm = "level4_llm"
    escalation = "level5_escalation"


class ForgeStrategy(str, Enum):
    template = "template"
    cache = "cache"
    llm = "llm"


# ---------------------------------------------------------------------------
# 1. TemplateQuality — per-template pass/fail/error rates
# ---------------------------------------------------------------------------


class TemplateQuality(BaseModel):
    architecture: str = ""
    total_generations: int = 0
    passes: int = 0
    failures: int = 0
    error_rate: float = 0.0
    avg_val_metric: float | None = None
    median_val_metric: float | None = None
    error_types: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 2. ForgeReliability — cascade level distribution, strategy routing
# ---------------------------------------------------------------------------


class ForgeReliability(BaseModel):
    strategy_distribution: dict[str, int] = Field(default_factory=dict)
    cascade_hits: dict[str, int] = Field(default_factory=dict)
    cascade_misses: dict[str, int] = Field(default_factory=dict)
    architecture_selections: dict[str, int] = Field(default_factory=dict)
    prevention_rules_applied: int = 0
    fingerprint_cache_hits: int = 0
    fingerprint_cache_misses: int = 0
    avg_generation_duration_s: float | None = None
    template_quality_by_arch: dict[str, TemplateQuality] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 3. DissectEffectiveness — patch success by category, cascade hit/miss
# ---------------------------------------------------------------------------


class PatchLogEntry(BaseModel):
    patch_id: str = ""
    job_id: str = ""
    timestamp: str = ""
    exception_type: str = ""
    exception_message: str = ""
    error_taxonomy_category: str = ""
    taxonomy_match_method: str = ""
    repair_strategy_used: str = ""
    retrieved_similar_patches: list[dict[str, Any]] = Field(default_factory=list)
    diff_applied: str = ""
    lines_changed: int = 0
    sandbox_test_result: str = ""
    patch_outcome: str = ""
    confidence_score: float = 0.0
    attempt_number: int = 0
    resume_from_checkpoint: str | None = None


class DissectEffectiveness(BaseModel):
    total_patches_attempted: int = 0
    total_patches_successful: int = 0
    total_patches_rolled_back: int = 0
    total_patches_escalated: int = 0
    patch_success_rate: float = 0.0
    avg_confidence: float | None = None
    avg_lines_changed: float | None = None
    error_category_distribution: dict[str, int] = Field(default_factory=dict)
    error_category_success_rates: dict[str, float] = Field(default_factory=dict)
    cascade_hit_distribution: dict[str, int] = Field(default_factory=dict)
    cascade_miss_distribution: dict[str, int] = Field(default_factory=dict)
    classification_methods: dict[str, int] = Field(default_factory=dict)
    attempt_outcome_distribution: dict[str, int] = Field(default_factory=dict)
    patches_by_job: list[PatchLogEntry] = Field(default_factory=list)
    first_pass_success_rate: float = 0.0
    avg_attempts_per_job: float = 0.0
    total_first_attempts: int = 0
    first_attempt_successes: int = 0
    llm_calls_estimated: int = 0
    regex_calls: int = 0


# ---------------------------------------------------------------------------
# 4. LlmUsage — token counts, cost estimates, fallback rate
# ---------------------------------------------------------------------------


class LlmUsage(BaseModel):
    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    llm_fallback_rate: float = 0.0
    avg_tokens_per_call: float | None = None
    avg_cost_per_call_usd: float | None = None
    calls_by_agent: dict[str, int] = Field(default_factory=dict)
    tokens_by_agent: dict[str, int] = Field(default_factory=dict)
    cost_by_agent_usd: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 5. KnowledgeProgress — ChromaDB knowledge accumulation
# ---------------------------------------------------------------------------


class KnowledgeProgress(BaseModel):
    patch_memory_size: int = 0
    architecture_memory_size: int = 0
    tool_memory_size: int = 0
    unique_patches: int = 0
    unique_error_categories_seen: int = 0
    patch_memory_growth_rate: float | None = None
    patch_memory_growth_rate_per_job: float = 0.0
    oldest_patch_timestamp: str | None = None
    newest_patch_timestamp: str | None = None
    total_jobs_in_patch_log: int = 0
    patches_per_job_avg: float = 0.0
    patches_per_job_max: int = 0


# ---------------------------------------------------------------------------
# 6. PerformanceProfile — per-problem timing/overhead
# ---------------------------------------------------------------------------


class PerformanceProfile(BaseModel):
    problem_id: str = ""
    modality: str = ""
    task_type: str = ""
    total_duration_s: float = 0.0
    scout_duration_s: float | None = None
    forge_duration_s: float | None = None
    training_duration_s: float | None = None
    evaluation_duration_s: float | None = None
    patch_overhead_s: float | None = None
    status: str = ""
    val_metric: float | None = None
    crash_count: int = 0

    @property
    def breakdown(self) -> dict[str, float]:
        return {
            "scout": self.scout_duration_s or 0,
            "forge": self.forge_duration_s or 0,
            "training": self.training_duration_s or 0,
            "evaluation": self.evaluation_duration_s or 0,
            "patch_overhead": self.patch_overhead_s or 0,
        }


class PerformanceProfileSet(BaseModel):
    profiles: list[PerformanceProfile] = Field(default_factory=list)

    @property
    def avg_total_duration_s(self) -> float:
        if not self.profiles:
            return 0.0
        return sum(p.total_duration_s for p in self.profiles) / len(self.profiles)

    @property
    def median_total_duration_s(self) -> float:
        if not self.profiles:
            return 0.0
        sorted_durs = sorted(p.total_duration_s for p in self.profiles)
        n = len(sorted_durs)
        mid = n // 2
        if n % 2 == 1:
            return sorted_durs[mid]
        return (sorted_durs[mid - 1] + sorted_durs[mid]) / 2

    @property
    def modality_breakdown(self) -> dict[str, list[PerformanceProfile]]:
        result: dict[str, list[PerformanceProfile]] = {}
        for p in self.profiles:
            result.setdefault(p.modality, []).append(p)
        return result


# ---------------------------------------------------------------------------
# 7. RootCauseReport — failure root cause analysis
# ---------------------------------------------------------------------------


class RootCauseReport(BaseModel):
    total_problems: int = 0
    total_failures: int = 0
    failure_rate: float = 0.0
    failures_by_category: dict[str, int] = Field(default_factory=dict)
    failures_by_architecture: dict[str, int] = Field(default_factory=dict)
    failures_by_modality: dict[str, int] = Field(default_factory=dict)
    top_failure_errors: list[dict[str, Any]] = Field(default_factory=list)
    common_failure_patterns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 8. BenchmarkComparison — before/after deltas
# ---------------------------------------------------------------------------


class ConditionResult(BaseModel):
    problem_id: str = ""
    condition: str = ""
    status: str = ""
    best_val_metric: float | None = None
    duration_seconds: float = 0.0
    crash_count: int = 0
    human_interventions: int = 0
    architecture: str = ""


class BenchmarkComparison(BaseModel):
    version_a_label: str = "before"
    version_b_label: str = "after"
    pass_rate_delta_pp: float | None = None
    avg_metric_delta: float | None = None
    avg_duration_delta_s: float | None = None
    patch_success_rate_delta: float | None = None
    llm_cost_delta_usd: float | None = None
    template_error_rate_delta: float | None = None
    per_problem_comparisons: list[dict[str, Any]] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    condition_a: list[ConditionResult] = Field(default_factory=list)
    condition_b: list[ConditionResult] = Field(default_factory=list)
    condition_c: list[ConditionResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 9. EngineeringSummary — top-level rollup of all 8 deliverables
# ---------------------------------------------------------------------------


class BenchmarkConfig(BaseModel):
    benchmark_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    git_commit: str = ""
    git_branch: str = ""
    num_problems: int = 0
    num_conditions: int = 0
    problems_file: str = ""


# ---------------------------------------------------------------------------
# 10. FailureLifecycleEntry & FailureLifecycleReport — LLM→Template→Rule→Forge→Never
# ---------------------------------------------------------------------------


class FailureLifecycleStage(str, Enum):
    llm_only = "llm_only"
    has_template = "has_template"
    has_rule = "has_rule"
    forge_prevented = "forge_prevented"
    never_seen = "never_seen"


class FailureLifecycleEntry(BaseModel):
    category: str = ""
    total_occurrences: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    resolved_by_llm: int = 0
    resolved_by_template: int = 0
    resolved_by_rule: int = 0
    forge_prevention_applicable: bool = False
    forge_prevention_implemented: bool = False
    still_recurring: bool = True
    current_stage: FailureLifecycleStage = FailureLifecycleStage.llm_only
    next_recommendation: str = ""
    success_rate: float = 0.0
    llm_calls_saved_if_deterministic: int = 0


class FailureLifecycleReport(BaseModel):
    categories: list[FailureLifecycleEntry] = Field(default_factory=list)
    total_llm_calls_savable: int = 0
    total_occurrences_tracked: int = 0
    forge_prevention_count: int = 0
    rule_count: int = 0
    template_count: int = 0
    llm_only_count: int = 0


class EngineeringSummary(BaseModel):
    config: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    template_quality: dict[str, TemplateQuality] = Field(default_factory=dict)
    forge_reliability: ForgeReliability = Field(default_factory=ForgeReliability)
    dissect_effectiveness: DissectEffectiveness = Field(default_factory=DissectEffectiveness)
    llm_usage: LlmUsage = Field(default_factory=LlmUsage)
    knowledge_progress: KnowledgeProgress = Field(default_factory=KnowledgeProgress)
    performance_profile: PerformanceProfileSet = Field(default_factory=PerformanceProfileSet)
    root_cause_report: RootCauseReport = Field(default_factory=RootCauseReport)
    benchmark_comparison: BenchmarkComparison | None = None
    failure_lifecycle: FailureLifecycleReport = Field(default_factory=FailureLifecycleReport)

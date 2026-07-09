"""Data access layer — loads benchmark results from ExperimentSet, patch_log, problems.json,
and benchmark results directory.

This module provides pure functions that read from multiple data sources
and return EngineeringSummary model instances ready for report generation.
The pipeline is self-sufficient: even without ExperimentSets, it mines
patch_log.jsonl for LLM usage estimates, performance proxies, root cause
patterns, and knowledge compilation metrics.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.engineering.models import (
    BenchmarkComparison,
    BenchmarkConfig,
    ConditionResult,
    DissectEffectiveness,
    EngineeringSummary,
    FailureLifecycleEntry,
    FailureLifecycleReport,
    FailureLifecycleStage,
    ForgeReliability,
    KnowledgeProgress,
    LlmUsage,
    PatchLogEntry,
    PerformanceProfile,
    PerformanceProfileSet,
    RootCauseReport,
    TemplateQuality,
)
from research.validation.models import ExperimentSet, ResearchHypothesis
from research.validation.tracker import load_experiment_set, list_experiment_sets

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_EXPERIMENTS_DIR = _PROJECT_ROOT / "experiments"
_DEFAULT_BENCHMARK_DIR = _PROJECT_ROOT / "research/benchmark"
_DEFAULT_RESULTS_DIR = _DEFAULT_BENCHMARK_DIR / "results"
_DEFAULT_PROBLEMS_PATH = _DEFAULT_BENCHMARK_DIR / "problems.json"
_DEFAULT_PATCH_LOG_PATH = _PROJECT_ROOT / "research/patch_log.jsonl"

# Token/cost estimation constants for LLM calls
_EST_INPUT_TOKENS_PER_CALL = 3000
_EST_OUTPUT_TOKENS_PER_CALL = 800
_EST_INPUT_COST_PER_M = 3.0
_EST_OUTPUT_COST_PER_M = 15.0


# ---------------------------------------------------------------------------
# Problem definitions
# ---------------------------------------------------------------------------


def load_problems(path: str | Path | None = None) -> list[dict[str, Any]]:
    path = Path(path) if path else _DEFAULT_PROBLEMS_PATH
    if not path.exists():
        logger.warning(f"Problems file not found: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _resolve_problem_id(entry: dict[str, Any]) -> str:
    return entry.get("problem_id", entry.get("id", ""))


def _get_modality(problem: dict[str, Any]) -> str:
    return problem.get("modality", problem.get("modality_override", "unknown"))


# ---------------------------------------------------------------------------
# ExperimentSet loaders
# ---------------------------------------------------------------------------


def load_latest_experiment_set(
    directory: str | Path | None = None,
) -> ExperimentSet | None:
    """Load the most recent ExperimentSet from the experiments directory."""
    directory = Path(directory) if directory else _DEFAULT_EXPERIMENTS_DIR
    files = list_experiment_sets(directory)
    if not files:
        logger.warning(f"No experiment sets found in {directory}")
        return None
    return load_experiment_set(files[0])


def load_experiment_set_by_id(
    set_id: str, directory: str | Path | None = None
) -> ExperimentSet | None:
    directory = Path(directory) if directory else _DEFAULT_EXPERIMENTS_DIR
    path = directory / f"{set_id}.json"
    if not path.exists():
        logger.warning(f"Experiment set not found: {path}")
        return None
    return load_experiment_set(path)


# ---------------------------------------------------------------------------
# Patch log loader
# ---------------------------------------------------------------------------


def load_patch_log(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load patch_log.jsonl entries.

    Returns list of parsed dicts, one per line.
    Silently skips malformed JSON lines.
    """
    path = Path(path) if path else _DEFAULT_PATCH_LOG_PATH
    if not path.exists():
        logger.warning(f"Patch log not found: {path}")
        return []
    entries: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning(f"Skipping malformed patch log line: {line[:80]}")
    return entries


# ---------------------------------------------------------------------------
# Benchmark results loader (from research/benchmark/results/)
# ---------------------------------------------------------------------------


def load_benchmark_results(directory: str | Path | None = None) -> list[dict[str, Any]]:
    """Load all condition-comparison benchmark result files."""
    directory = Path(directory) if directory else _DEFAULT_RESULTS_DIR
    if not directory.exists():
        logger.warning(f"Benchmark results directory not found: {directory}")
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                results.extend(data)
            elif isinstance(data, dict):
                results.append(data)
        except Exception as exc:
            logger.warning(f"Could not load {path.name}: {exc}")
    return results


def load_condition_results(
    results: list[dict[str, Any]] | None = None,
) -> dict[str, list[ConditionResult]]:
    """Group benchmark results by condition (B_no_dissect, C_with_dissect, etc.).

    Deduplicates by problem_id within each condition (last entry wins),
    since multiple batch files may contain overlapping problem sets.
    Returns dict mapping condition label to list of ConditionResult.
    """
    if results is None:
        results = load_benchmark_results()

    grouped: dict[str, dict[str, ConditionResult]] = {}
    for r in results:
        cond = r.get("condition", "unknown")
        pid = r.get("problem_id", "")
        if cond not in grouped:
            grouped[cond] = {}
        grouped[cond][pid] = ConditionResult(
            problem_id=pid,
            condition=cond,
            status=r.get("status", ""),
            best_val_metric=r.get("best_val_metric"),
            duration_seconds=r.get("duration_seconds", 0.0),
            crash_count=r.get("crash_count", 0),
            human_interventions=r.get("human_interventions", 0),
            architecture=r.get("architecture", ""),
        )

    return {cond: list(entries.values()) for cond, entries in grouped.items()}


# ---------------------------------------------------------------------------
# Build engineering models from data sources
# ---------------------------------------------------------------------------


def _build_template_quality(
    exp_set: ExperimentSet | None,
    benchmark_results: list[dict[str, Any]] | None = None,
) -> dict[str, TemplateQuality]:
    """Aggregate template quality per architecture from ExperimentSet or benchmark results."""
    arch_map: dict[str, list[dict[str, Any]]] = {}

    if exp_set and exp_set.experiments:
        for exp in exp_set.experiments.values():
            for run in exp.runs:
                rd = run.model_dump()
                arch = rd.get("execution_outcome", {}).get(
                    "architecture", rd.get("architecture", "")
                )
                if not arch:
                    continue
                arch_map.setdefault(arch, []).append(rd)

    if (not arch_map or all(len(v) <= 1 for v in arch_map.values())) and benchmark_results:
        for r in benchmark_results:
            arch = r.get("architecture", "unknown")
            arch_map.setdefault(arch, []).append(r)

    result: dict[str, TemplateQuality] = {}
    for arch, runs in arch_map.items():
        passes = sum(1 for r in runs if r.get("decision") == "pass" or r.get("status") == "pass")
        failures = sum(
            1 for r in runs if r.get("status") in ("crash", "failed", "escalate", "error")
        )
        total = len(runs)
        metrics = [
            r.get("best_val_metric", r.get("val_metric"))
            for r in runs
            if r.get("best_val_metric") is not None
        ]
        metrics = [float(m) for m in metrics]
        errors: dict[str, int] = {}
        for r in runs:
            err = r.get("error", "")
            if err:
                etype = err.split(":")[0] if ":" in err else err[:60]
                errors[etype] = errors.get(etype, 0) + 1

        result[arch] = TemplateQuality(
            architecture=arch,
            total_generations=total,
            passes=passes,
            failures=failures,
            error_rate=failures / total if total > 0 else 0.0,
            avg_val_metric=sum(metrics) / len(metrics) if metrics else None,
            median_val_metric=sorted(metrics)[len(metrics) // 2] if metrics else None,
            error_types=errors,
        )
    return result


def _build_forge_reliability(
    exp_set: ExperimentSet | None,
    benchmark_results: list[dict[str, Any]] | None = None,
) -> ForgeReliability:
    """Extract Forge reliability metrics from ExperimentSet or benchmark results."""
    arch_selections: dict[str, int] = {}

    if exp_set and exp_set.experiments:
        for exp in exp_set.experiments.values():
            for run in exp.runs:
                rd = run.model_dump()
                arch = rd.get("execution_outcome", {}).get(
                    "architecture", rd.get("architecture", "")
                )
                if arch:
                    arch_selections[arch] = arch_selections.get(arch, 0) + 1

    if (not arch_selections) and benchmark_results:
        for r in benchmark_results:
            arch = r.get("architecture", "unknown")
            arch_selections[arch] = arch_selections.get(arch, 0) + 1

    return ForgeReliability(
        architecture_selections=arch_selections,
        prevention_rules_applied=0,
    )


# ---------------------------------------------------------------------------
# Phase 1, 4, 6: Dissect effectiveness — deep patch_log mining
# ---------------------------------------------------------------------------


def _build_dissect_effectiveness(
    patch_entries: list[dict[str, Any]],
) -> DissectEffectiveness:
    """Analyze Dissect patch log entries into effectiveness metrics (Phase 1 + 4 + 6).

    Mines patch_log for:
    - Attempt distribution, first-pass success rate (Phase 6)
    - Classification method distribution (LLM vs regex) (Phase 5)
    - Cascade level distribution (Phase 4)
    - Error category success rates (Phase 1)
    """
    total = len(patch_entries)
    if total == 0:
        return DissectEffectiveness()

    outcomes = [e.get("patch_outcome", "") for e in patch_entries]
    successes = sum(1 for o in outcomes if o == "success")
    rollbacks = sum(1 for o in outcomes if o == "rollback")
    escalations = sum(1 for o in outcomes if o == "escalated")

    category_dist: dict[str, int] = {}
    category_success: dict[str, tuple[int, int]] = {}
    cascade_hits: dict[str, int] = {}
    cascade_misses: dict[str, int] = {}
    class_methods: dict[str, int] = {}
    attempt_dist: dict[str, int] = {}
    confidences: list[float] = []
    lines_changed: list[int] = []

    # First-pass tracking (Phase 6)
    first_pass_by_job: dict[str, int] = {}
    first_pass_successes: int = 0
    first_pass_total: int = 0

    # LLM call counting (Phase 5)
    llm_count = 0
    regex_count = 0

    for e in patch_entries:
        cat = e.get("error_taxonomy_category", "unknown")
        category_dist[cat] = category_dist.get(cat, 0) + 1

        oc = e.get("patch_outcome", "")
        cs = category_success.setdefault(cat, (0, 0))
        category_success[cat] = (cs[0] + 1, cs[1] + (1 if oc == "success" else 0))

        method = e.get("taxonomy_match_method", "unknown")
        class_methods[method] = class_methods.get(method, 0) + 1
        if method == "llm" or method == "llm_classification":
            llm_count += 1
        elif method == "regex":
            regex_count += 1

        att = str(e.get("attempt_number", 0))
        attempt_dist[att] = attempt_dist.get(att, 0) + 1

        # First-pass tracking: first attempt per job
        job_id = e.get("job_id", "")
        if att == "1":
            first_pass_by_job.setdefault(job_id, 0)
            if first_pass_by_job[job_id] == 0:
                first_pass_total += 1
                first_pass_by_job[job_id] = -1 if oc != "success" else 1
            # Track multiple occurrences if this is truly the first entry for this job
            if first_pass_by_job[job_id] == 0:
                first_pass_successes += 1 if oc == "success" else 0

        conf = e.get("confidence_score")
        if conf is not None:
            confidences.append(float(conf))

        lc = e.get("lines_changed")
        if lc is not None:
            lines_changed.append(int(lc))

    category_success_rates = {
        cat: (suc / tot if tot > 0 else 0.0) for cat, (tot, suc) in category_success.items()
    }

    # Recalculate first pass properly
    first_pass_attempts_per_job: dict[str, list[dict[str, Any]]] = {}
    for e in patch_entries:
        job_id = e.get("job_id", "")
        att = e.get("attempt_number", 1)
        if att == 1:
            first_pass_attempts_per_job.setdefault(job_id, []).append(e)

    first_pass_total = len(first_pass_attempts_per_job)
    first_pass_successes = sum(
        1
        for attempts in first_pass_attempts_per_job.values()
        if any(a.get("patch_outcome") == "success" for a in attempts)
    )

    # Average attempts per job (Phase 6)
    attempts_by_job: Counter = Counter()
    jobs_with_patches: set = set()
    for e in patch_entries:
        jid = e.get("job_id", "")
        if jid:
            attempts_by_job[jid] = max(attempts_by_job[jid], e.get("attempt_number", 1))
            jobs_with_patches.add(jid)

    avg_attempts = sum(attempts_by_job.values()) / len(attempts_by_job) if attempts_by_job else 0.0

    # Cascade level estimation from error categories (Phase 4)
    # Level 0 (regex) → deterministic rules, Level 4 (llm) → LLM, Level 5 → escalation
    cascade_from_categories: dict[str, int] = {}
    for e in patch_entries:
        method = e.get("taxonomy_match_method", "")
        oc = e.get("patch_outcome", "")
        if method == "regex":
            level = "level0_rule"
        elif oc == "escalated":
            level = "level5_escalation"
        elif method in ("llm", "llm_classification"):
            if e.get("retrieved_similar_patches"):
                level = "level3_memory"
            else:
                level = "level4_llm"
        else:
            level = "unknown"
        cascade_from_categories[level] = cascade_from_categories.get(level, 0) + 1

    return DissectEffectiveness(
        total_patches_attempted=total,
        total_patches_successful=successes,
        total_patches_rolled_back=rollbacks,
        total_patches_escalated=escalations,
        patch_success_rate=successes / total if total > 0 else 0.0,
        avg_confidence=sum(confidences) / len(confidences) if confidences else None,
        avg_lines_changed=sum(lines_changed) / len(lines_changed) if lines_changed else None,
        error_category_distribution=category_dist,
        error_category_success_rates=category_success_rates,
        cascade_hit_distribution=cascade_from_categories,
        classification_methods=class_methods,
        attempt_outcome_distribution=attempt_dist,
        patches_by_job=[PatchLogEntry(**e) for e in patch_entries],
        first_pass_success_rate=(
            first_pass_successes / first_pass_total if first_pass_total > 0 else 0.0
        ),
        avg_attempts_per_job=avg_attempts,
        total_first_attempts=first_pass_total,
        first_attempt_successes=first_pass_successes,
        llm_calls_estimated=llm_count,
        regex_calls=regex_count,
    )


# ---------------------------------------------------------------------------
# Phase 5: Build LLM usage estimate from patch_log
# ---------------------------------------------------------------------------


def _build_llm_usage(
    exp_set: ExperimentSet | None,
    dissect_effectiveness: DissectEffectiveness | None = None,
) -> LlmUsage:
    """Estimate LLM usage from patch_log or ExperimentSet (Phase 5).

    Primary source: patch_log classification methods (275 llm calls detected).
    Fallback: estimate from ExperimentSet run counts.
    """
    if dissect_effectiveness and dissect_effectiveness.llm_calls_estimated > 0:
        llm_calls = dissect_effectiveness.llm_calls_estimated
        regex_calls = dissect_effectiveness.regex_calls
        total_calls = llm_calls + regex_calls

        input_tokens = llm_calls * _EST_INPUT_TOKENS_PER_CALL
        output_tokens = llm_calls * _EST_OUTPUT_TOKENS_PER_CALL
        cost = (
            input_tokens / 1_000_000 * _EST_INPUT_COST_PER_M
            + output_tokens / 1_000_000 * _EST_OUTPUT_COST_PER_M
        )

        fallback_rate = regex_calls / total_calls if total_calls > 0 else 0.0
        avg_tokens = (input_tokens + output_tokens) / total_calls if total_calls > 0 else None
        avg_cost = cost / total_calls if total_calls > 0 else None

        return LlmUsage(
            total_llm_calls=total_calls,
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
            estimated_cost_usd=round(cost, 2),
            llm_fallback_rate=round(fallback_rate, 4),
            avg_tokens_per_call=round(avg_tokens, 1) if avg_tokens else None,
            avg_cost_per_call_usd=round(avg_cost, 6) if avg_cost else None,
            calls_by_agent={"dissect": llm_calls},
            tokens_by_agent={"dissect": input_tokens + output_tokens},
            cost_by_agent_usd={"dissect": round(cost, 2)},
        )

    if exp_set and exp_set.experiments:
        total_runs = sum(len(exp.runs) for exp in exp_set.experiments.values())
        if total_runs == 0:
            return LlmUsage()
        calls_by_agent: dict[str, int] = {}
        if "H1" in exp_set.experiments:
            calls_by_agent["scout"] = len(exp_set.experiments["H1"].runs)
            calls_by_agent["forge"] = len(exp_set.experiments["H1"].runs)
        estimated_input_tokens = (
            calls_by_agent.get("scout", 0) * 2000 + calls_by_agent.get("forge", 0) * 1500
        )
        estimated_output_tokens = (
            calls_by_agent.get("scout", 0) * 500 + calls_by_agent.get("forge", 0) * 800
        )
        total_calls = sum(calls_by_agent.values())
        return LlmUsage(
            total_llm_calls=total_calls,
            total_input_tokens=estimated_input_tokens,
            total_output_tokens=estimated_output_tokens,
            estimated_cost_usd=round(
                estimated_input_tokens / 1_000_000 * _EST_INPUT_COST_PER_M
                + estimated_output_tokens / 1_000_000 * _EST_OUTPUT_COST_PER_M,
                2,
            ),
            calls_by_agent=calls_by_agent,
        )

    return LlmUsage()


# ---------------------------------------------------------------------------
# Phase 7: Knowledge compilation metrics
# ---------------------------------------------------------------------------


def _build_knowledge_progress(
    patch_entries: list[dict[str, Any]],
    dissect_effectiveness: DissectEffectiveness | None = None,
) -> KnowledgeProgress:
    """Assess ChromaDB knowledge from patch log data (Phase 7).

    Tracks:
    - Patch memory size and unique entries
    - Per-job patch density (patches per job)
    - Growth rate over time
    """
    if not patch_entries:
        return KnowledgeProgress()

    unique_patches = len(set(e.get("patch_id", "") for e in patch_entries if e.get("patch_id")))
    unique_categories = len(
        set(
            e.get("error_taxonomy_category", "")
            for e in patch_entries
            if e.get("error_taxonomy_category")
        )
    )

    timestamps = [e.get("timestamp", "") for e in patch_entries if e.get("timestamp")]
    timestamps.sort()

    # Compute per-job metrics
    jobs: Counter = Counter()
    for e in patch_entries:
        jid = e.get("job_id", "")
        if jid:
            jobs[jid] += 1

    patches_per_job = list(jobs.values())
    avg_ppj = sum(patches_per_job) / len(patches_per_job) if patches_per_job else 0.0
    max_ppj = max(patches_per_job) if patches_per_job else 0

    # Growth rate: patches per hour over the time span
    growth_rate = None
    if len(timestamps) >= 2:
        try:
            oldest = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            newest = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            hours = max((newest - oldest).total_seconds() / 3600, 0.01)
            growth_rate = len(patch_entries) / hours
        except Exception:
            pass

    return KnowledgeProgress(
        patch_memory_size=len(patch_entries),
        unique_patches=unique_patches,
        unique_error_categories_seen=unique_categories,
        patch_memory_growth_rate=round(growth_rate, 2) if growth_rate else None,
        patch_memory_growth_rate_per_job=round(avg_ppj, 2),
        oldest_patch_timestamp=timestamps[0] if timestamps else None,
        newest_patch_timestamp=timestamps[-1] if timestamps else None,
        total_jobs_in_patch_log=len(jobs),
        patches_per_job_avg=round(avg_ppj, 2),
        patches_per_job_max=max_ppj,
    )


# ---------------------------------------------------------------------------
# Phase 8: Performance profiling from patch_log timing approximation
# ---------------------------------------------------------------------------


def _build_performance_profile(
    exp_set: ExperimentSet | None,
    benchmark_results: list[dict[str, Any]] | None = None,
    patch_entries: list[dict[str, Any]] | None = None,
) -> PerformanceProfileSet:
    """Build per-problem performance profiles from ExperimentSet or benchmark results (Phase 8).

    When experiment sets are empty, mines patch_log timestamps for
    approximate timing data and benchmark results for real timing.
    """
    seen: dict[str, PerformanceProfile] = {}

    # Source 1: ExperimentSet (richest data)
    if exp_set and exp_set.experiments:
        for h_key in ("H1", "H2", "H3"):
            exp = exp_set.experiments.get(h_key)
            if not exp:
                continue
            for run in exp.runs:
                pid = run.problem_id
                if pid not in seen:
                    seen[pid] = PerformanceProfile(problem_id=pid)
                p = seen[pid]
                p.total_duration_s = max(p.total_duration_s, run.system_metrics.duration_seconds)
                p.training_duration_s = max(
                    p.training_duration_s or 0, run.system_metrics.wall_clock_time_s
                )
                if run.system_metrics.crashes:
                    p.crash_count = max(p.crash_count, run.system_metrics.crashes)
                rd = run.model_dump()
                status = rd.get("execution_outcome", {}).get("status", rd.get("status", ""))
                if status in ("pass", "success"):
                    p.status = "pass"
                elif p.status != "pass":
                    p.status = status
                metric = rd.get("research_metrics", {}).get(
                    "final_metric", rd.get("best_val_metric")
                )
                if metric is not None:
                    p.val_metric = max(p.val_metric or 0, float(metric))

    # Source 2: benchmark results (condition comparison runs)
    if benchmark_results:
        for r in benchmark_results:
            pid = r.get("problem_id", "")
            if pid not in seen:
                seen[pid] = PerformanceProfile(problem_id=pid)
            p = seen[pid]
            dur = r.get("duration_seconds", 0)
            p.total_duration_s = max(p.total_duration_s, dur)
            if r.get("status") == "pass":
                p.status = "pass"
            metric = r.get("best_val_metric")
            if metric is not None:
                p.val_metric = max(p.val_metric or 0, float(metric))
            p.crash_count = max(p.crash_count, r.get("crash_count", 0))

    # Source 3: patch_log timing approximation (extract from timestamps)
    # Groups patches by job_id and estimates duration from timestamp range
    if patch_entries and not seen:
        job_times: dict[str, list[str]] = {}
        for e in patch_entries:
            jid = e.get("job_id", "")
            ts = e.get("timestamp", "")
            if jid and ts:
                job_times.setdefault(jid, []).append(ts)

        for jid, tss in job_times.items():
            pid = jid.split("-bench-")[-1] if "-bench-" in jid else jid[:15]
            if pid not in seen:
                seen[pid] = PerformanceProfile(problem_id=pid)
            p = seen[pid]
            if len(tss) >= 2:
                try:
                    t0 = datetime.fromisoformat(tss[0].replace("Z", "+00:00"))
                    t1 = datetime.fromisoformat(tss[-1].replace("Z", "+00:00"))
                    p.total_duration_s = max(p.total_duration_s, (t1 - t0).total_seconds())
                except Exception:
                    pass
            if p.status == "":
                p.status = "patched"

    return PerformanceProfileSet(profiles=list(seen.values()))


# ---------------------------------------------------------------------------
# Phase 2: Root cause analysis — from patch_log and benchmark failures
# ---------------------------------------------------------------------------


def _build_root_cause_report(
    exp_set: ExperimentSet | None,
    benchmark_results: list[dict[str, Any]] | None = None,
    patch_entries: list[dict[str, Any]] | None = None,
) -> RootCauseReport:
    """Analyze failure root causes from available data sources (Phase 2).

    Mines:
    - Patch log rollbacks/escalations for error pattern extraction
    - Benchmark results for per-problem failures
    - Experiment sets for per-architecture failure rates
    """
    failures_by_cat: dict[str, int] = {}
    failures_by_arch: dict[str, int] = {}
    failures_by_modality: dict[str, int] = {}
    top_errors: list[dict[str, Any]] = []
    failure_patterns: Counter = Counter()

    # Track unique problems to avoid double-counting across sources
    seen_problems: set = set()
    seen_failures: set = set()

    # Source 1: ExperimentSet
    if exp_set and exp_set.experiments:
        for exp in exp_set.experiments.values():
            for run in exp.runs:
                pid = run.problem_id
                seen_problems.add(pid)
                rd = run.model_dump()
                status = rd.get("execution_outcome", {}).get("status", rd.get("status", ""))
                if status in ("crash", "failed", "escalate", "error"):
                    seen_failures.add(pid)
                    arch = rd.get("execution_outcome", {}).get(
                        "architecture", rd.get("architecture", "unknown")
                    )
                    failures_by_arch[arch] = failures_by_arch.get(arch, 0) + 1
                    err = rd.get("execution_outcome", {}).get("error", rd.get("error", ""))
                    if err:
                        top_errors.append(
                            {
                                "problem_id": pid,
                                "architecture": arch,
                                "error": err[:200],
                            }
                        )

    # Source 2: Benchmark results
    if benchmark_results:
        for r in benchmark_results:
            pid = r.get("problem_id", "")
            seen_problems.add(pid)
            if r.get("status") in ("crash", "failed", "escalate", "error"):
                seen_failures.add(pid)
                arch = r.get("architecture", "unknown")
                failures_by_arch[arch] = failures_by_arch.get(arch, 0) + 1
                err = r.get("error", "")
                if err:
                    top_errors.append(
                        {
                            "problem_id": pid,
                            "architecture": arch,
                            "error": err[:200],
                        }
                    )
                    etype = err.split(":")[0].strip() if ":" in err else err[:40].strip()
                    failure_patterns[etype] += 1

    # Source 3: Patch log failure analysis (richest source)
    if patch_entries:
        for e in patch_entries:
            oc = e.get("patch_outcome", "")
            if oc in ("rollback", "escalated"):
                cat = e.get("error_taxonomy_category", "unknown")
                failures_by_cat[cat] = failures_by_cat.get(cat, 0) + 1
                err_type = e.get("exception_type", "")
                if err_type:
                    failure_patterns[err_type] += 1
                if oc == "escalated":
                    top_errors.append(
                        {
                            "problem_id": e.get("job_id", "")[:20],
                            "architecture": e.get("error_taxonomy_category", "unknown"),
                            "error": f"{err_type}: {e.get('exception_message', '')[:150]}",
                            "attempt_number": e.get("attempt_number", 3),
                        }
                    )

    top_errors = top_errors[:10]
    total_problems = max(len(seen_problems), 1)
    failure_count = len(seen_failures)
    if not seen_problems and failures_by_cat:
        failure_count = sum(failures_by_cat.values())

    # Generate common failure patterns
    common_patterns = [f"{pattern}: {count}x" for pattern, count in failure_patterns.most_common(5)]

    recommendations = _generate_recommendations_patch(
        failures_by_arch, failures_by_cat, failure_patterns
    )

    return RootCauseReport(
        total_problems=(
            total_problems
            if total_problems > 0
            else (len(failure_patterns) if failure_patterns else 1)
        ),
        total_failures=failure_count,
        failure_rate=failure_count / max(total_problems, 1),
        failures_by_category=failures_by_cat,
        failures_by_architecture=failures_by_arch,
        failures_by_modality=failures_by_modality,
        top_failure_errors=top_errors,
        common_failure_patterns=common_patterns,
        recommendations=recommendations,
    )


def _generate_recommendations_patch(
    failures_by_arch: dict[str, int],
    failures_by_cat: dict[str, int],
    failure_patterns: Counter,
) -> list[str]:
    """Generate actionable recommendations from failure data."""
    recs: list[str] = []

    if failures_by_arch:
        worst_arch = max(failures_by_arch, key=failures_by_arch.get)
        recs.append(
            f"Prioritize fixing {worst_arch} templates ({failures_by_arch[worst_arch]} failures)"
        )

    if failures_by_cat:
        worst_cat = max(failures_by_cat, key=failures_by_cat.get)
        recs.append(
            f"Focus Dissect training on {worst_cat} category ({failures_by_cat[worst_cat]} unresolved failures)"
        )

    if failure_patterns:
        top_type = failure_patterns.most_common(1)[0]
        recs.append(f"Add static prevention rule for '{top_type[0]}' ({top_type[1]} occurrences)")

    if not recs:
        recs.append("No failure data available — run the benchmark to generate recommendations")

    return recs


def _extract_job_modality(job_id: str, problems: list[dict[str, Any]] | None) -> str:
    """Extract modality from problem_id prefix."""
    if not problems:
        return "unknown"
    prefix = job_id.split("-")[0] if "-" in job_id else job_id[:4]
    for p in problems or []:
        pid = p.get("problem_id", "").lower()
        if pid == prefix.lower():
            return p.get("modality", "unknown")
    # Fallback: guess from prefix
    if prefix.startswith("tc"):
        return "tabular"
    elif prefix.startswith("tx"):
        return "text"
    elif prefix.startswith("ic"):
        return "image"
    return "unknown"


# ---------------------------------------------------------------------------
# Phase 9: Build benchmark condition comparison
# ---------------------------------------------------------------------------


def _build_benchmark_comparison(
    benchmark_results: list[dict[str, Any]] | None = None,
) -> BenchmarkComparison | None:
    """Compare conditions B (no Dissect) vs C (with Dissect) from benchmark results (Phase 9)."""
    if not benchmark_results:
        return None

    conditions = load_condition_results(benchmark_results)
    cond_b = conditions.get("B_no_dissect", [])
    cond_c = conditions.get("C_with_dissect", [])

    if not cond_b or not cond_c:
        return None

    # Compute deltas
    b_passes = sum(1 for r in cond_b if r.status in ("pass", "success"))
    c_passes = sum(1 for r in cond_c if r.status in ("pass", "success"))
    b_pass_rate = b_passes / len(cond_b) if cond_b else 0
    c_pass_rate = c_passes / len(cond_c) if cond_c else 0

    b_metrics = [
        r.best_val_metric for r in cond_b if r.best_val_metric is not None and r.best_val_metric > 0
    ]
    c_metrics = [
        r.best_val_metric for r in cond_c if r.best_val_metric is not None and r.best_val_metric > 0
    ]
    b_avg_metric = sum(b_metrics) / len(b_metrics) if b_metrics else None
    c_avg_metric = sum(c_metrics) / len(c_metrics) if c_metrics else None

    b_durations = [r.duration_seconds for r in cond_b]
    c_durations = [r.duration_seconds for r in cond_c]
    b_avg_dur = sum(b_durations) / len(b_durations) if b_durations else 0
    c_avg_dur = sum(c_durations) / len(c_durations) if c_durations else 0

    b_interventions = sum(r.human_interventions for r in cond_b)
    c_interventions = sum(r.human_interventions for r in cond_c)

    per_problem: list[dict[str, Any]] = []
    for r_b in cond_b:
        matching = [r_c for r_c in cond_c if r_c.problem_id == r_b.problem_id]
        if matching:
            r_c = matching[0]
            per_problem.append(
                {
                    "problem_id": r_b.problem_id,
                    "B_status": r_b.status,
                    "C_status": r_c.status,
                    "B_metric": r_b.best_val_metric,
                    "C_metric": r_c.best_val_metric,
                    "B_duration": r_b.duration_seconds,
                    "C_duration": r_c.duration_seconds,
                    "delta_metric": (
                        (r_c.best_val_metric or 0) - (r_b.best_val_metric or 0)
                        if r_c.best_val_metric and r_b.best_val_metric
                        else None
                    ),
                }
            )

    pass_rate_delta = c_pass_rate - b_pass_rate
    metric_delta = (c_avg_metric - b_avg_metric) if c_avg_metric and b_avg_metric else None
    dur_delta = c_avg_dur - b_avg_dur

    improvements: list[str] = []
    regressions: list[str] = []

    if pass_rate_delta > 0:
        improvements.append(f"Pass rate improved by {pass_rate_delta:.1%} with Dissect")
    elif pass_rate_delta < 0:
        regressions.append(f"Pass rate decreased by {abs(pass_rate_delta):.1%} with Dissect")

    if c_interventions < b_interventions:
        improvements.append(f"Human interventions reduced: {b_interventions} → {c_interventions}")
    elif c_interventions > b_interventions:
        regressions.append(f"Human interventions increased: {b_interventions} → {c_interventions}")

    if metric_delta and metric_delta > 0:
        improvements.append(f"Average validation metric improved by {metric_delta:.4f}")
    elif metric_delta and metric_delta < 0:
        regressions.append(f"Average validation metric decreased by {abs(metric_delta):.4f}")

    # Check for specific per-problem changes
    for pp in per_problem:
        if pp.get("B_status") in ("crash", "failed") and pp.get("C_status") in ("pass", "success"):
            improvements.append(f"{pp['problem_id']}: recovered from crash to pass with Dissect")
        elif pp.get("B_status") in ("pass", "success") and pp.get("C_status") in (
            "crash",
            "failed",
        ):
            regressions.append(f"{pp['problem_id']}: regressed from pass to crash with Dissect")

    return BenchmarkComparison(
        version_a_label="B: without Dissect",
        version_b_label="C: with Dissect",
        pass_rate_delta_pp=round(pass_rate_delta * 100, 1),
        avg_metric_delta=round(metric_delta, 4) if metric_delta is not None else None,
        avg_duration_delta_s=round(dur_delta, 2),
        per_problem_comparisons=per_problem,
        improvements=improvements,
        regressions=regressions,
        condition_a=[],
        condition_b=cond_b,
        condition_c=cond_c,
    )


# ---------------------------------------------------------------------------
# Phase 10a: Build failure_lifecycle report — LLM→Template→Rule→Forge→Never pipeline
# ---------------------------------------------------------------------------


def _get_stage_for_category(category: str) -> tuple[FailureLifecycleStage, bool, bool, bool]:
    """Determine current failure lifecycle stage for a category.

    Returns (stage, has_rule, has_template, forge_prevention_implemented).
    """
    from agents.dissect.taxonomy import TAXONOMY

    for entry in TAXONOMY:
        if entry.category == category:
            forge_prevention = category in (
                "encoding_error",  # utf-8 read added to Forge scripts
                "empty_dataset",  # empty check added to Forge scripts
                "dtype_mismatch",  # numeric coercion added to Forge scripts
            )

            if forge_prevention and entry.has_rule:
                return FailureLifecycleStage.forge_prevented, True, entry.has_template, True
            if entry.has_rule:
                return FailureLifecycleStage.has_rule, True, entry.has_template, False
            if entry.has_template:
                return FailureLifecycleStage.has_template, entry.has_rule, True, False
            return FailureLifecycleStage.llm_only, entry.has_rule, entry.has_template, False

    return FailureLifecycleStage.llm_only, False, False, False


def _build_failure_lifecycle(
    patch_entries: list[dict[str, Any]],
) -> FailureLifecycleReport:
    """Build failure_lifecycle report tracking each error category's maturity.

    For every error category, determines:
    - First/last seen timestamps
    - How many were resolved by LLM vs template vs rule
    - Whether forge prevention is applicable/implemented
    - How many LLM calls could be saved by moving to deterministic repair
    """
    from collections import defaultdict
    from datetime import datetime

    if not patch_entries:
        return FailureLifecycleReport()

    # Group by category
    cat_data: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "entries": [],
            "first_seen": None,
            "last_seen": None,
            "resolved_by_llm": 0,
            "resolved_by_template": 0,
            "resolved_by_rule": 0,
            "successful": 0,
            "total": 0,
        }
    )

    for e in patch_entries:
        cat = e.get("error_taxonomy_category", "unknown")
        ts = e.get("timestamp", "")
        method = e.get("taxonomy_match_method", "")
        outcome = e.get("patch_outcome", "")
        repair_strategy = e.get("repair_strategy_used", "")

        cd = cat_data[cat]
        cd["entries"].append(e)
        cd["total"] += 1

        if ts:
            if cd["first_seen"] is None or ts < cd["first_seen"]:
                cd["first_seen"] = ts
            if cd["last_seen"] is None or ts > cd["last_seen"]:
                cd["last_seen"] = ts

        if outcome == "success":
            cd["successful"] += 1

        # Track resolution method — these correspond to cascade levels
        if method == "llm":
            cd["resolved_by_llm"] += 1
        elif repair_strategy and (
            "rule" in repair_strategy.lower() or "template" in repair_strategy.lower()
        ):
            cd["resolved_by_template"] += 1
        else:
            cd["resolved_by_llm"] += 1  # default to LLM

    categories: list[FailureLifecycleEntry] = []
    total_llm_savable = 0

    for cat_name, cd in sorted(cat_data.items(), key=lambda x: -x[1]["total"]):
        stage, has_rule, has_template, forge_implemented = _get_stage_for_category(cat_name)
        success_rate = cd["successful"] / max(cd["total"], 1)
        current_still_recurring = True
        if cd["last_seen"] and cd["first_seen"]:
            try:
                last = datetime.fromisoformat(cd["last_seen"].replace("Z", "+00:00"))
                first = datetime.fromisoformat(cd["first_seen"].replace("Z", "+00:00"))
                span_hours = (last - first).total_seconds() / 3600
                # If category hasn't been seen in the last 25% of its active span, consider not recurring
                current_still_recurring = span_hours > 0.5
            except Exception:
                pass

        # Determine how many LLM calls could be saved
        llm_savable = (
            cd["resolved_by_llm"] if (has_rule or has_template or forge_implemented) else 0
        )
        total_llm_savable += llm_savable

        # Recommendation
        if forge_implemented and has_rule:
            next_rec = "Forge prevention active — monitor for regression"
        elif forge_implemented:
            next_rec = "Add deterministic rule to taxonomy for full closure"
        elif has_rule:
            next_rec = "Add forge-level prevention to eliminate LLM calls entirely"
        elif has_template:
            next_rec = "Convert template to deterministic rule; then add forge prevention"
        else:
            next_rec = "Add to taxonomy as deterministic rule; classify patterns from patch_log"

        categories.append(
            FailureLifecycleEntry(
                category=cat_name,
                total_occurrences=cd["total"],
                first_seen=cd["first_seen"],
                last_seen=cd["last_seen"],
                resolved_by_llm=cd["resolved_by_llm"],
                resolved_by_template=cd.get("resolved_by_template", 0),
                resolved_by_rule=cd.get("resolved_by_rule", 0),
                forge_prevention_applicable=has_rule or has_template,
                forge_prevention_implemented=forge_implemented,
                still_recurring=current_still_recurring,
                current_stage=stage,
                next_recommendation=next_rec,
                success_rate=round(success_rate, 3),
                llm_calls_saved_if_deterministic=llm_savable,
            )
        )

    forge_count = sum(1 for c in categories if c.forge_prevention_implemented)
    rule_count = sum(1 for c in categories if c.current_stage == FailureLifecycleStage.has_rule)
    template_count = sum(
        1 for c in categories if c.current_stage == FailureLifecycleStage.has_template
    )
    llm_only_count = sum(1 for c in categories if c.current_stage == FailureLifecycleStage.llm_only)

    return FailureLifecycleReport(
        categories=categories,
        total_llm_calls_savable=total_llm_savable,
        total_occurrences_tracked=sum(c.total_occurrences for c in categories),
        forge_prevention_count=forge_count,
        rule_count=rule_count,
        template_count=template_count,
        llm_only_count=llm_only_count,
    )


# ---------------------------------------------------------------------------
# Phase 10: Build complete EngineeringSummary
# ---------------------------------------------------------------------------


def build_engineering_summary(
    exp_set: ExperimentSet | None = None,
    patch_entries: list[dict[str, Any]] | None = None,
    problems: list[dict[str, Any]] | None = None,
    git_commit: str = "",
    git_branch: str = "",
) -> EngineeringSummary:
    """Build a complete EngineeringSummary from all available data sources (Phases 1-10).

    Data source priority:
    1. patch_log.jsonl — always loaded, provides Dissect, LLM, knowledge, root cause data
    2. benchmark results (research/benchmark/results/) — condition comparison
    3. ExperimentSet (experiments/) — if available, adds template quality + forge reliability

    If data sources are not provided, they are loaded from default paths.
    """
    if exp_set is None:
        exp_set = load_latest_experiment_set()
    if patch_entries is None:
        patch_entries = load_patch_log()
    if problems is None:
        problems = load_problems()

    benchmark_results = load_benchmark_results()

    null_set = ExperimentSet(name="empty")
    exp_set = exp_set or null_set

    num_conditions = (
        len(set(r.get("condition", "") for r in benchmark_results))
        if benchmark_results
        else max(len([k for k in ("H1", "H2", "H3") if k in (exp_set.experiments or {})]), 1)
    )

    config = BenchmarkConfig(
        git_commit=git_commit or exp_set.git_commit,
        git_branch=git_branch or exp_set.git_branch,
        num_problems=len(problems),
        num_conditions=max(num_conditions, 1),
        problems_file=str(_DEFAULT_PROBLEMS_PATH),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

    # Phase 1: Template quality (from exp_set or benchmark results)
    template_quality = _build_template_quality(exp_set, benchmark_results)

    # Phase 3: Forge reliability (prevention rules tracking is manual for now)
    forge_reliability = _build_forge_reliability(exp_set, benchmark_results)

    # Phase 1, 4, 6: Dissect effectiveness with deep patch_log analysis
    dissect_effectiveness = _build_dissect_effectiveness(patch_entries)

    # Phase 5: LLM usage from patch_log
    llm_usage = _build_llm_usage(exp_set, dissect_effectiveness)

    # Phase 7: Knowledge compilation from patch_log
    knowledge_progress = _build_knowledge_progress(patch_entries, dissect_effectiveness)

    # Phase 8: Performance profiling from all sources
    performance_profile = _build_performance_profile(exp_set, benchmark_results, patch_entries)

    # Phase 2: Root cause from patch_log + benchmark results
    root_cause_report = _build_root_cause_report(exp_set, benchmark_results, patch_entries)

    # Phase 9: Benchmark condition comparison
    benchmark_comparison = _build_benchmark_comparison(benchmark_results)

    # Phase 10: Failure lifecycle tracking
    failure_lifecycle = _build_failure_lifecycle(patch_entries)

    return EngineeringSummary(
        config=config,
        template_quality=template_quality,
        forge_reliability=forge_reliability,
        dissect_effectiveness=dissect_effectiveness,
        llm_usage=llm_usage,
        knowledge_progress=knowledge_progress,
        performance_profile=performance_profile,
        root_cause_report=root_cause_report,
        benchmark_comparison=benchmark_comparison,
        failure_lifecycle=failure_lifecycle,
    )

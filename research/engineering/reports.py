"""Report generators — produces all 9 engineering dashboard deliverables.

Each function writes one output file to research/engineering/output/.
All functions accept an EngineeringSummary and return the path written.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.engineering.data import (
    build_engineering_summary,
    load_latest_experiment_set,
    load_patch_log,
    load_problems,
)
from research.engineering.models import (
    EngineeringSummary,
    FailureLifecycleReport,
    PerformanceProfileSet,
    RootCauseReport,
)

logger = logging.getLogger(__name__)

_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _ensure_output_dir() -> Path:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUTPUT_DIR


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _git_branch() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


def _write_json(data: Any, filename: str) -> Path:
    out = _ensure_output_dir() / filename
    out.write_text(
        json.dumps(data, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"Written: {out}")
    return out


def _write_md(content: str, filename: str) -> Path:
    out = _ensure_output_dir() / filename
    out.write_text(content, encoding="utf-8")
    logger.info(f"Written: {out}")
    return out


def _model_to_dict(m: Any) -> dict[str, Any]:
    if hasattr(m, "model_dump"):
        return m.model_dump()
    return dict(m)


# ===========================================================================
# 1. engineering_summary.json — comprehensive results JSON
# ===========================================================================


def write_engineering_summary_json(summary: EngineeringSummary) -> Path:
    data = _model_to_dict(summary)
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    return _write_json(data, "engineering_summary.json")


# ===========================================================================
# 2. engineering_summary.md — Markdown report
# ===========================================================================


def write_engineering_summary_md(summary: EngineeringSummary) -> Path:
    lines = [
        "# Engineering Improvement Dashboard",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"**Git:** `{summary.config.git_commit or 'unknown'}` on `{summary.config.git_branch or 'unknown'}`",
        f"**Problems:** {summary.config.num_problems} | **Conditions:** {summary.config.num_conditions}",
        "",
    ]

    # Overview table
    lines.extend(
        [
            "## Overview",
            "",
            "| Metric | Value |",
            "|---|---|",
        ]
    )
    ds = summary.dissect_effectiveness
    lines.append(f"| Patch success rate | {ds.patch_success_rate:.1%} |")
    lines.append(f"| Total patches attempted | {ds.total_patches_attempted} |")
    lines.append(f"| Successful patches | {ds.total_patches_successful} |")
    lines.append(f"| Rolled back | {ds.total_patches_rolled_back} |")
    lines.append(f"| Escalated | {ds.total_patches_escalated} |")
    if ds.avg_confidence is not None:
        lines.append(f"| Avg confidence score | {ds.avg_confidence:.2f} |")
    if ds.avg_lines_changed is not None:
        lines.append(f"| Avg lines changed per patch | {ds.avg_lines_changed:.1f} |")
    lines.append(f"| LLM estimated cost | ${summary.llm_usage.estimated_cost_usd:.2f} |")
    lines.append(f"| LLM total calls | {summary.llm_usage.total_llm_calls} |")
    lines.append(f"| Patch memory size | {summary.knowledge_progress.patch_memory_size} |")
    lines.append(
        f"| Unique error categories | {summary.knowledge_progress.unique_error_categories_seen} |"
    )
    rc = summary.root_cause_report
    lines.append(f"| Failure rate | {rc.failure_rate:.1%} |")
    pp = summary.performance_profile
    lines.append(f"| Avg duration | {pp.avg_total_duration_s:.1f}s |")

    # Phase 6: First-pass success
    lines.append(f"| First-pass success rate | {ds.first_pass_success_rate:.1%} |")
    lines.append(f"| Avg attempts per job | {ds.avg_attempts_per_job:.2f} |")
    lines.append("")

    # Phase 4: Cascade level distribution
    if ds.cascade_hit_distribution:
        lines.extend(
            [
                "## Cascade Level Distribution (Phase 4)",
                "",
                "| Level | Hits | Description |",
                "|---|---|---|",
            ]
        )
        level_desc = {
            "level0_rule": "Deterministic rules (regex)",
            "level3_memory": "Patch memory hit",
            "level4_llm": "LLM classification",
            "level5_escalation": "Escalated to human",
        }
        for level, count in sorted(ds.cascade_hit_distribution.items()):
            desc = level_desc.get(level, level)
            lines.append(f"| {level} | {count} | {desc} |")
        lines.append("")

    # Template quality per architecture
    if summary.template_quality:
        lines.extend(
            [
                "## Template Quality by Architecture",
                "",
                "| Architecture | Generations | Passes | Failures | Error Rate | Avg Metric |",
                "|---|---|---|---|---|---|",
            ]
        )
        for arch, tq in sorted(summary.template_quality.items()):
            metric_str = f"{tq.avg_val_metric:.4f}" if tq.avg_val_metric is not None else "--"
            lines.append(
                f"| {arch} | {tq.total_generations} | {tq.passes} | {tq.failures} | "
                f"{tq.error_rate:.1%} | {metric_str} |"
            )
        lines.append("")

    # Forge reliability
    fr = summary.forge_reliability
    if fr.architecture_selections:
        lines.extend(
            [
                "## Forge Reliability",
                "",
                "| Architecture | Selections |",
                "|---|---|",
            ]
        )
        for arch, count in sorted(fr.architecture_selections.items()):
            lines.append(f"| {arch} | {count} |")
        lines.append("")

    # Dissect effectiveness by error category (Phase 1)
    ds = summary.dissect_effectiveness
    if ds.error_category_distribution:
        lines.extend(
            [
                "## Dissect Effectiveness by Error Category",
                "",
                "| Category | Occurrences | Success Rate |",
                "|---|---|---|",
            ]
        )
        for cat, count in sorted(ds.error_category_distribution.items()):
            sr = ds.error_category_success_rates.get(cat, 0.0)
            lines.append(f"| {cat} | {count} | {sr:.1%} |")
        lines.append("")

    # Phase 6: Attempt outcome distribution
    if ds.attempt_outcome_distribution:
        lines.extend(
            [
                "## Patch Attempt Distribution (Phase 6)",
                "",
                "| Attempt Number | Count |",
                "|---|---|",
            ]
        )
        for att, count in sorted(ds.attempt_outcome_distribution.items()):
            lines.append(f"| {att} | {count} |")
        lines.append("")

    # Phase 5: LLM usage
    llm = summary.llm_usage
    lines.extend(
        [
            "## LLM Usage (Phase 5)",
            "",
            f"- **Total calls:** {llm.total_llm_calls}",
            f"- **Input tokens:** {llm.total_input_tokens:,}",
            f"- **Output tokens:** {llm.total_output_tokens:,}",
            f"- **Estimated cost:** ${llm.estimated_cost_usd:.2f}",
        ]
    )
    if llm.llm_fallback_rate > 0:
        lines.append(f"- **Regex fallback rate:** {llm.llm_fallback_rate:.1%}")
    if llm.avg_cost_per_call_usd:
        lines.append(f"- **Avg cost per call:** ${llm.avg_cost_per_call_usd:.6f}")
    if llm.calls_by_agent:
        lines.append("")
        lines.append("| Agent | Calls |")
        lines.append("|---|---|")
        for agent, count in sorted(llm.calls_by_agent.items()):
            lines.append(f"| {agent} | {count} |")
    lines.append("")

    # Phase 7: Knowledge progress
    kp = summary.knowledge_progress
    lines.extend(
        [
            "## Knowledge Progress (Phase 7)",
            "",
            f"- **Patch memory entries:** {kp.patch_memory_size}",
            f"- **Unique patches:** {kp.unique_patches}",
            f"- **Unique error categories:** {kp.unique_error_categories_seen}",
            f"- **Total jobs in patch log:** {kp.total_jobs_in_patch_log}",
            f"- **Avg patches per job:** {kp.patches_per_job_avg:.1f}",
            f"- **Max patches per job:** {kp.patches_per_job_max}",
        ]
    )
    if kp.patch_memory_growth_rate:
        lines.append(f"- **Growth rate:** {kp.patch_memory_growth_rate:.1f} patches/hour")
    if kp.oldest_patch_timestamp:
        lines.append(f"- **Oldest entry:** {kp.oldest_patch_timestamp}")
    if kp.newest_patch_timestamp:
        lines.append(f"- **Newest entry:** {kp.newest_patch_timestamp}")
    lines.append("")

    # Phase 8: Performance profile
    lines.extend(
        [
            "## Performance Summary (Phase 8)",
            "",
            f"- **Average total duration:** {pp.avg_total_duration_s:.1f}s",
            f"- **Median total duration:** {pp.median_total_duration_s:.1f}s",
            f"- **Total problems profiled:** {len(pp.profiles)}",
            "",
        ]
    )

    # Phase 2: Root cause
    lines.extend(
        [
            "## Root Cause Analysis (Phase 2)",
            "",
            f"- **Total failures:** {rc.total_failures}/{rc.total_problems} ({rc.failure_rate:.1%})",
        ]
    )
    if rc.failures_by_category:
        lines.append("")
        lines.append("| Error Category | Failures |")
        lines.append("|---|---|")
        for cat, count in sorted(rc.failures_by_category.items()):
            lines.append(f"| {cat} | {count} |")
    if rc.failures_by_architecture:
        lines.append("")
        lines.append("| Architecture | Failures |")
        lines.append("|---|---|")
        for arch, count in sorted(rc.failures_by_architecture.items()):
            lines.append(f"| {arch} | {count} |")
    if rc.common_failure_patterns:
        lines.append("")
        lines.append("### Common Failure Patterns")
        for pat in rc.common_failure_patterns:
            lines.append(f"- {pat}")
    if rc.recommendations:
        lines.append("")
        lines.append("### Recommendations")
        for rec in rc.recommendations:
            lines.append(f"- {rec}")
    lines.append("")

    # Phase 9: Benchmark comparison
    bc = summary.benchmark_comparison
    if bc:
        lines.extend(
            [
                "## Benchmark Comparison (Phase 9)",
                "",
                f"- **Condition B (no Dissect):** {len(bc.condition_b)} problems",
                f"- **Condition C (with Dissect):** {len(bc.condition_c)} problems",
            ]
        )
        if bc.pass_rate_delta_pp is not None:
            lines.append(f"- **Pass rate delta:** {bc.pass_rate_delta_pp:+.1f}pp")
        if bc.avg_metric_delta is not None:
            lines.append(f"- **Avg metric delta:** {bc.avg_metric_delta:+.4f}")
        if bc.avg_duration_delta_s is not None:
            lines.append(f"- **Avg duration delta:** {bc.avg_duration_delta_s:+.2f}s")

        # Per-problem comparison table
        if bc.per_problem_comparisons:
            lines.append("")
            lines.append("### Per-Problem Comparison")
            lines.append("")
            lines.append("| Problem | B Status | C Status | B Metric | C Metric | Delta |")
            lines.append("|---|---|---|---|---|---|")
            for ppc in bc.per_problem_comparisons:
                b_s = ppc.get("B_status", "")
                c_s = ppc.get("C_status", "")
                b_m = f"{ppc['B_metric']:.4f}" if ppc.get("B_metric") else "--"
                c_m = f"{ppc['C_metric']:.4f}" if ppc.get("C_metric") else "--"
                delta = (
                    f"{ppc['delta_metric']:+.4f}" if ppc.get("delta_metric") is not None else "--"
                )
                icon = (
                    "✓" if c_s == "pass" else "✗" if c_s in ("crash", "failed", "escalate") else "?"
                )
                lines.append(
                    f"| {ppc['problem_id']} | {b_s} | {c_s} {icon} | {b_m} | {c_m} | {delta} |"
                )
            lines.append("")

        if bc.improvements:
            lines.append("### Improvements with Dissect")
            for imp in bc.improvements:
                lines.append(f"- {imp}")
            lines.append("")
        if bc.regressions:
            lines.append("### Regressions with Dissect")
            for reg in bc.regressions:
                lines.append(f"- {reg}")
            lines.append("")

    # Phase 10: Failure lifecycle
    fl = summary.failure_lifecycle
    if fl.categories:
        lines.extend(
            [
                "## Failure Lifecycle — LLM Elimination Pipeline (Phase 10)",
                "",
                "| Category | Occurrences | Stage | LLM Calls | Savable | Success Rate | Recommendation |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for c in fl.categories:
            lines.append(
                f"| {c.category} | {c.total_occurrences} | {c.current_stage} | "
                f"{c.resolved_by_llm} | {c.llm_calls_saved_if_deterministic} | "
                f"{c.success_rate:.0%} | {c.next_recommendation} |"
            )
        lines.append("")
        lines.extend(
            [
                "### Summary",
                "",
                f"- **Total LLM calls that could be saved if deterministic:** {fl.total_llm_calls_savable}",
                f"- **Categories with forge prevention:** {fl.forge_prevention_count}",
                f"- **Categories with deterministic rules:** {fl.rule_count}",
                f"- **Categories with templates:** {fl.template_count}",
                f"- **Categories still LLM-only:** {fl.llm_only_count}",
                "",
            ]
        )

    lines.append("---")
    lines.append("*Report generated by Prometheus Swarm Engineering Dashboard (Phases 1-10)*")

    return _write_md("\n".join(lines), "engineering_summary.md")


# ===========================================================================
# 3. root_cause_report.json — failure root cause analysis
# ===========================================================================


def write_root_cause_report(root_cause: RootCauseReport) -> Path:
    return _write_json(_model_to_dict(root_cause), "root_cause_report.json")


# ===========================================================================
# 4. forge_improvements.md — Forge reliability metrics
# ===========================================================================


def write_forge_improvements(summary: EngineeringSummary) -> Path:
    fr = summary.forge_reliability
    lines = [
        "# Forge Reliability Metrics",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Architecture Selection Distribution",
        "",
        "| Architecture | Selections |",
        "|---|---|",
    ]
    for arch, count in sorted(fr.architecture_selections.items()):
        lines.append(f"| {arch} | {count} |")
    lines.append("")

    if summary.template_quality:
        lines.extend(
            [
                "",
                "## Template Quality Metrics",
                "",
                "| Architecture | Generations | Passes | Failures | Error Rate | Avg Metric | Median Metric |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for arch, tq in sorted(summary.template_quality.items()):
            avg_str = f"{tq.avg_val_metric:.4f}" if tq.avg_val_metric is not None else "--"
            med_str = f"{tq.median_val_metric:.4f}" if tq.median_val_metric is not None else "--"
            lines.append(
                f"| {arch} | {tq.total_generations} | {tq.passes} | {tq.failures} | "
                f"{tq.error_rate:.1%} | {avg_str} | {med_str} |"
            )
        lines.append("")

    if fr.cascade_hits:
        lines.extend(
            [
                "",
                "## Cascade Level Hit Distribution",
                "",
                "| Level | Hits |",
                "|---|---|",
            ]
        )
        for level, count in sorted(fr.cascade_hits.items()):
            lines.append(f"| {level} | {count} |")
        lines.append("")

    lines.extend(
        [
            "",
            "## Strategy Distribution",
            "",
            "| Strategy | Count |",
            "|---|---|",
        ]
    )
    for strategy, count in sorted(fr.strategy_distribution.items()):
        lines.append(f"| {strategy} | {count} |")
    lines.append("")

    lines.append("---")
    lines.append("*Generated by Prometheus Swarm Engineering Dashboard*")

    return _write_md("\n".join(lines), "forge_improvements.md")


# ===========================================================================
# 5. dissect_improvements.md — Dissect effectiveness metrics
# ===========================================================================


def write_dissect_improvements(summary: EngineeringSummary) -> Path:
    ds = summary.dissect_effectiveness
    lines = [
        "# Dissect Effectiveness Metrics",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "",
        "## Overall Statistics",
        "",
        f"- **Patches attempted:** {ds.total_patches_attempted}",
        f"- **Successful patches:** {ds.total_patches_successful}",
        f"- **Rolled back:** {ds.total_patches_rolled_back}",
        f"- **Escalated:** {ds.total_patches_escalated}",
        f"- **Success rate:** {ds.patch_success_rate:.1%}",
    ]
    if ds.avg_confidence is not None:
        lines.append(f"- **Avg confidence:** {ds.avg_confidence:.2f}")
    if ds.avg_lines_changed is not None:
        lines.append(f"- **Avg lines changed:** {ds.avg_lines_changed:.1f}")
    lines.append("")

    # Phase 6: First-pass success
    lines.extend(
        [
            "",
            "## First-Pass Success (Phase 6)",
            "",
            f"- **First-pass success rate:** {ds.first_pass_success_rate:.1%}",
            f"- **First attempts:** {ds.total_first_attempts}",
            f"- **First attempt successes:** {ds.first_attempt_successes}",
            f"- **Avg attempts per job:** {ds.avg_attempts_per_job:.2f}",
        ]
    )
    lines.append("")

    if ds.error_category_distribution:
        lines.extend(
            [
                "",
                "## Error Category Distribution",
                "",
                "| Category | Occurrences | Success Rate |",
                "|---|---|---|",
            ]
        )
        for cat, count in sorted(ds.error_category_distribution.items()):
            sr = ds.error_category_success_rates.get(cat, 0.0)
            lines.append(f"| {cat} | {count} | {sr:.1%} |")
        lines.append("")

    if ds.classification_methods:
        lines.extend(
            [
                "",
                "## Classification Methods (Phase 5)",
                "",
                "| Method | Count | Estimated Cost |",
                "|---|---|---|",
            ]
        )
        for method, count in sorted(ds.classification_methods.items()):
            if method in ("llm", "llm_classification"):
                cost_est = f"${count * 3000 * 3 / 1_000_000 + count * 800 * 15 / 1_000_000:.2f}"
            else:
                cost_est = "$0.00 (deterministic)"
            lines.append(f"| {method} | {count} | {cost_est} |")
        lines.append("")

    # Phase 4: Cascade level distribution
    if ds.cascade_hit_distribution:
        lines.extend(
            [
                "",
                "## Cascade Level Distribution (Phase 4)",
                "",
                "| Level | Hits | Description |",
                "|---|---|---|",
            ]
        )
        level_desc = {
            "level0_rule": "Deterministic rule (regex match)",
            "level3_memory": "Patch memory query hit (K=3)",
            "level4_llm": "LLM classification (fallback)",
            "level5_escalation": "Escalated to human (3 attempts failed)",
        }
        for level, count in sorted(ds.cascade_hit_distribution.items()):
            desc = level_desc.get(level, level)
            lines.append(f"| {level} | {count} | {desc} |")
        lines.append("")

    if ds.attempt_outcome_distribution:
        lines.extend(
            [
                "",
                "## Outcome by Attempt Number (Phase 6)",
                "",
                "| Attempt | Count | Outcome |",
                "|---|---|---|",
            ]
        )
        for attempt, count in sorted(ds.attempt_outcome_distribution.items()):
            outcome_desc = (
                "First attempt"
                if attempt == "1"
                else "Second attempt" if attempt == "2" else "Final attempt"
            )
            lines.append(f"| {attempt} | {count} | {outcome_desc} |")
        lines.append("")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by Prometheus Swarm Engineering Dashboard*")

    return _write_md("\n".join(lines), "dissect_improvements.md")


# ===========================================================================
# 6. llm_usage_report.json — LLM cost/token/quality tracking
# ===========================================================================


def write_llm_usage_report(summary: EngineeringSummary) -> Path:
    return _write_json(_model_to_dict(summary.llm_usage), "llm_usage_report.json")


# ===========================================================================
# 7. knowledge_progress.json — ChromaDB knowledge accumulation
# ===========================================================================


def write_knowledge_progress(summary: EngineeringSummary) -> Path:
    return _write_json(_model_to_dict(summary.knowledge_progress), "knowledge_progress.json")


# ===========================================================================
# 8. performance_profile.json — per-problem timing/overhead
# ===========================================================================


def write_performance_profile(profiles: PerformanceProfileSet) -> Path:
    data = {
        "profiles": [_model_to_dict(p) for p in profiles.profiles],
        "summary": {
            "avg_total_duration_s": profiles.avg_total_duration_s,
            "median_total_duration_s": profiles.median_total_duration_s,
            "num_profiles": len(profiles.profiles),
        },
    }
    return _write_json(data, "performance_profile.json")


# ===========================================================================
# 9. benchmark_comparison.json — before/after deltas
# ===========================================================================


def write_benchmark_comparison(summary: EngineeringSummary) -> Path:
    bc = summary.benchmark_comparison
    if bc is None:
        bc_data = {"message": "No comparison data available. Run two benchmarks and rebuild."}
    else:
        bc_data = _model_to_dict(bc)
    return _write_json(bc_data, "benchmark_comparison.json")


# ===========================================================================
# Generate all reports
# ===========================================================================


OUTPUT_FILES = [
    "engineering_summary.json",
    "engineering_summary.md",
    "root_cause_report.json",
    "forge_improvements.md",
    "dissect_improvements.md",
    "llm_usage_report.json",
    "knowledge_progress.json",
    "performance_profile.json",
    "benchmark_comparison.json",
    "failure_lifecycle.json",
]


def write_failure_lifecycle(report: FailureLifecycleReport) -> Path:
    """Write failure_lifecycle.json — per-category LLM→deterministic tracking."""
    data = _model_to_dict(report)
    return _write_json(data, "failure_lifecycle.json")


def generate_all_reports(
    exp_set_path: str | None = None,
    patch_log_path: str | None = None,
    git_commit: str | None = None,
    git_branch: str | None = None,
) -> dict[str, Path]:
    """Generate all 10 engineering dashboard deliverable files.

    Args:
        exp_set_path: Path to a specific ExperimentSet JSON file (uses latest if None).
        patch_log_path: Path to patch_log.jsonl (uses default if None).
        git_commit: Git commit hash (auto-detected if None).
        git_branch: Git branch name (auto-detected if None).

    Returns:
        Dict mapping deliverable name to Path of written file.
    """
    commit = git_commit or _git_commit()
    branch = git_branch or _git_branch()

    if exp_set_path:
        from research.engineering.data import load_experiment_set_by_id

        exp_set_id = Path(exp_set_path).stem
        exp_set = load_experiment_set_by_id(exp_set_id)
    else:
        exp_set = load_latest_experiment_set()

    patch_entries = load_patch_log(patch_log_path)
    problems = load_problems()

    summary = build_engineering_summary(
        exp_set=exp_set,
        patch_entries=patch_entries,
        problems=problems,
        git_commit=commit,
        git_branch=branch,
    )

    return {
        "engineering_summary.json": write_engineering_summary_json(summary),
        "engineering_summary.md": write_engineering_summary_md(summary),
        "root_cause_report.json": write_root_cause_report(summary.root_cause_report),
        "forge_improvements.md": write_forge_improvements(summary),
        "dissect_improvements.md": write_dissect_improvements(summary),
        "llm_usage_report.json": write_llm_usage_report(summary),
        "knowledge_progress.json": write_knowledge_progress(summary),
        "performance_profile.json": write_performance_profile(summary.performance_profile),
        "benchmark_comparison.json": write_benchmark_comparison(summary),
        "failure_lifecycle.json": write_failure_lifecycle(summary.failure_lifecycle),
    }

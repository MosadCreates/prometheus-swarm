"""Evaluation report generation — Markdown + JSON summaries."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.validation.models import (
    ComparisonResult,
    Experiment,
    ExperimentRun,
    ExperimentSet,
    FailureReport,
    ResearchHypothesis,
)
from research.validation.metrics import (
    aggregate_research_metrics,
    aggregate_system_metrics,
    summarize_experiment,
    summarize_set,
)
from research.validation.statistics import compare_all

logger = logging.getLogger(__name__)

_REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "reports"


def _ensure_dir() -> Path:
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    return _REPORT_DIR


# ---------------------------------------------------------------------------
# Summary JSON
# ---------------------------------------------------------------------------


def generate_summary_json(
    exp_set: ExperimentSet,
    figure_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Generate the summary JSON for an experiment set."""
    summary = summarize_set(exp_set)
    if figure_paths:
        summary["figures"] = [str(p) for p in figure_paths]
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    return summary


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _h(value: str) -> str:
    """Format hypothesis label."""
    label_map = {
        ResearchHypothesis.H1.value: "H1 — Static Planner",
        ResearchHypothesis.H2.value: "H2 — Adaptive Planner",
        ResearchHypothesis.H3.value: "H3 — Adaptive + Patch Memory",
    }
    return label_map.get(value, value)


def _metric_table_row(prefix: str, summary: dict[str, Any]) -> str:
    cells: list[str] = []
    for key in ("mean", "median", "min", "max", "std"):
        val = summary.get(prefix, {}).get(key, "--")
        if isinstance(val, (int, float)):
            cells.append(f"{val:.2f}")
        else:
            cells.append(str(val))
    return "| " + " | ".join(cells) + " |"


def _comparison_result_row(label: str, cr: ComparisonResult) -> str:
    def _fmt(val, precision: int = 3) -> str:
        if val is None:
            return "--"
        return f"{val:.{precision}f}"

    return (
        f"| {label} | {_fmt(cr.mean_a)} | {_fmt(cr.mean_b)} | "
        f"{_fmt(cr.p_value, 4)} | {_fmt(cr.effect_size)} | "
        f"{cr.effect_size_name} | "
        f"{'Yes' if cr.significant else 'No'} | "
        f"[{_fmt(cr.ci_lower)}, {_fmt(cr.ci_upper)}] |"
    )


def _failure_report_section(report: FailureReport) -> str:
    lines = [
        "### Failure Analysis\n",
        f"**Total failed runs:** {report.total_failed}\n",
        "\n| Category | Count | Percentage |",
        "|---|---|---|",
    ]
    for cat, count in sorted(report.categories.items()):
        pct = report.category_percentages.get(cat, 0)
        lines.append(f"| {cat} | {count} | {pct}% |")

    if report.representative_examples:
        lines.append("\n**Representative examples:**\n")
        lines.append("| Run ID | Problem | Hypothesis | Category | Error |")
        lines.append("|---|---|---|---|---|")
        for ex in report.representative_examples[:3]:
            lines.append(
                f"| {ex['run_id']} | {ex['problem_id']} | {ex['hypothesis']} | "
                f"{ex['failure_category']} | {ex['error'][:60]} |"
            )

    lines.append("")
    return "\n".join(lines)


def generate_report(
    exp_set: ExperimentSet,
    figure_paths: list[Path] | None = None,
    failure_report: FailureReport | None = None,
    title: str | None = None,
) -> str:
    """Generate the full Markdown evaluation report."""
    lines: list[str] = []
    h = "##"

    # Title
    lines.append(f"# {title or 'Research Validation Report'}\n")
    lines.append(f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}*\n")
    lines.append(f"**Experiment Set:** `{exp_set.set_id}` — {exp_set.name}\n")

    # Reproducibility info
    if exp_set.git_commit:
        lines.append("### Reproducibility Context\n")
        lines.append(f"- **Git commit:** `{exp_set.git_commit[:12]}` on `{exp_set.git_branch}`")
        lines.append(f"- **Python:** {exp_set.python_version}")
        lines.append(f"- **Config hash:** `{exp_set.configuration_hash[:16]}`")
        lines.append(f"- **Planner version:** {exp_set.planner_version}")
        lines.append(f"- **Mission spec version:** {exp_set.mission_spec_version}")
        lines.append("")

    # Overview table
    lines.append(f"{h} Overview\n")
    lines.append("| Hypothesis | Runs | Mean Duration (s) | Success Rate | Mean Metric |")
    lines.append("|---|---|---|---|---|")

    for h_val in ("H1", "H2", "H3"):
        exp = exp_set.experiments.get(h_val)
        if not exp:
            continue
        sm = aggregate_system_metrics(exp.runs)
        rm = aggregate_research_metrics(exp.runs)
        dur = sm.get("duration", {}).get("mean", 0)
        success_rate = rm.get("deployment_success_rate", 0) * 100
        final_metric = rm.get("final_metric", {}).get("mean", 0)
        final_str = f"{final_metric:.4f}" if final_metric else "--"
        lines.append(
            f"| {_h(h_val)} | {sm.get('count', 0)} | {dur:.1f} | "
            f"{success_rate:.1f}% | {final_str} |"
        )
    lines.append("")

    # RQ results
    lines.append(f"{h} Research Questions\n")

    rq_labels = {
        "RQ1": "**RQ1:** Does adaptive planning reduce execution cost?",
        "RQ2": "**RQ2:** Does adaptive planning improve prediction accuracy?",
        "RQ3": "**RQ3:** Does adaptive planning reduce recovery time?",
        "RQ4": "**RQ4:** Does adaptive planning increase successful deployments?",
        "RQ5": "**RQ5:** How many historical executions before planning stabilizes?",
    }

    for rq_val, rq_label in rq_labels.items():
        lines.append(f"\n#### {rq_label}\n")
        matching = {k: v for k, v in exp_set.comparisons.items() if k.startswith(rq_val)}
        if matching:
            lines.append(
                "| Comparison | Mean A | Mean B | p-value | Effect Size | ES Label | Significant | 95% CI |"
            )
            lines.append("|---|---|---|---|---|---|---|---|")
            for k, cr in sorted(matching.items()):
                label = k.replace(f"{rq_val}_", "").replace("_", " ")[:30]
                lines.append(_comparison_result_row(label, cr))
        else:
            lines.append("*No comparisons available for this RQ.*\n")

    lines.append("")

    # Figures
    if figure_paths:
        lines.append(f"{h} Figures\n")
        for fp in figure_paths:
            rel = fp.relative_to(fp.parents[1]) if fp.parents else fp.name
            lines.append(f"![{fp.stem}]({rel.as_posix()})")
            lines.append("")
        lines.append("")

    # System metrics per hypothesis
    lines.append(f"{h} System Metrics Details\n")
    for h_val in ("H1", "H2", "H3"):
        exp = exp_set.experiments.get(h_val)
        if not exp:
            continue
        sm = aggregate_system_metrics(exp.runs)
        lines.append(f"**{_h(h_val)}** ({sm.get('count', 0)} runs)\n")
        lines.append("| Metric | Mean | Median | Min | Max | Std |")
        lines.append("|---|---|---|---|---|---|")
        for metric_key in (
            "duration",
            "retries",
            "crashes",
            "wall_clock_time_s",
            "orchestration_overhead_s",
        ):
            vals = sm.get(metric_key, {})
            if isinstance(vals, dict):
                lines.append(
                    f"| {metric_key} | {vals.get('mean', 0):.2f} | {vals.get('median', 0):.2f} | "
                    f"{vals.get('min', 0):.2f} | {vals.get('max', 0):.2f} | {vals.get('std', 0):.2f} |"
                )
        lines.append("")

    # Research metrics
    lines.append(f"{h} Research Metrics Details\n")
    for h_val in ("H1", "H2", "H3"):
        exp = exp_set.experiments.get(h_val)
        if not exp:
            continue
        rm = aggregate_research_metrics(exp.runs)
        lines.append(f"**{_h(h_val)}**\n")
        lines.append(
            f"- Deployment success rate: {rm.get('deployment_success_rate', 0) * 100:.1f}%"
        )
        final_m = rm.get("final_metric", {})
        if final_m.get("mean"):
            lines.append(f"- Mean final metric: {final_m['mean']:.4f}")
        pred_dur = rm.get("prediction_error_duration_pct", {})
        if pred_dur.get("mean"):
            lines.append(f"- Mean prediction error (duration): {pred_dur['mean']:.1f}%")
        arch_gap = rm.get("architecture_gap", {})
        if arch_gap.get("mean"):
            lines.append(f"- Mean architecture gap: {arch_gap['mean']:.4f}")
        conf = rm.get("planner_confidence", {})
        if conf.get("mean"):
            lines.append(f"- Mean planner confidence: {conf['mean']:.2f}")
        lines.append("")

    # Failure section
    if failure_report:
        lines.append(_failure_report_section(failure_report))

    # Conclusion
    lines.append(f"{h} Conclusions\n")
    significant_found = any(cr.significant for cr in exp_set.comparisons.values())
    if significant_found:
        lines.append(
            "Statistically significant differences were found between planning strategies.\n"
        )
        sig_details = [
            f"- **{k}**: p={cr.p_value:.4f}, {cr.effect_size_name}"
            for k, cr in sorted(exp_set.comparisons.items())
            if cr.significant
        ]
        lines.extend(sig_details)
    else:
        lines.append("No statistically significant differences detected.\n")

    lines.append("")
    lines.append("---")
    lines.append("*Report generated by Prometheus Swarm Research Validation Framework*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persist report
# ---------------------------------------------------------------------------


def save_report_to_disk(
    exp_set: ExperimentSet,
    figure_paths: list[Path] | None = None,
    failure_report: FailureReport | None = None,
    title: str | None = None,
) -> tuple[Path, Path]:
    """Save both the Markdown report and summary JSON to disk.

    Returns (md_path, json_path).
    """
    dir_path = _ensure_dir()

    # Markdown
    md_content = generate_report(exp_set, figure_paths, failure_report, title)
    md_path = dir_path / f"evaluation_report_{exp_set.set_id}.md"
    md_path.write_text(md_content, encoding="utf-8")
    logger.info(f"Report saved: {md_path}")

    # JSON summary
    summary = generate_summary_json(exp_set, figure_paths)
    json_path = dir_path / f"evaluation_summary_{exp_set.set_id}.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    logger.info(f"Summary saved: {json_path}")

    return md_path, json_path

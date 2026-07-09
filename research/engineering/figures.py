"""Engineering-specific figures — template quality, patch success trends, cost over time.

Uses matplotlib with the same style conventions as research/validation/figures.py
but focuses on engineering metrics rather than research hypothesis comparisons.
"""

from __future__ import annotations

import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from research.engineering.data import load_patch_log
from research.engineering.models import EngineeringSummary

logger = logging.getLogger(__name__)

_FIGURE_DIR = Path(__file__).resolve().parent.parent.parent / "figures"
_FIGURE_COUNTER: dict[str, int] = {}

COLORS_DARK = ["#4477AA", "#EE6677", "#228833", "#CC3311", "#AA3377", "#BBBBBB"]

matplotlib.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.labelsize": 11,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "legend.fontsize": 9,
        "figure.dpi": 120,
        "savefig.dpi": 200,
        "savefig.bbox": "tight",
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)


def _next_fig_id(prefix: str) -> str:
    _FIGURE_COUNTER[prefix] = _FIGURE_COUNTER.get(prefix, 0) + 1
    return f"eng_{prefix}_{_FIGURE_COUNTER[prefix]:02d}"


def _ensure_dir() -> Path:
    _FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    return _FIGURE_DIR


def _save_figure(fig: matplotlib.figure.Figure, fig_id: str) -> Path:
    dir_path = _ensure_dir()
    png_path = dir_path / f"{fig_id}.png"
    fig.savefig(png_path)
    plt.close(fig)
    logger.info(f"Figure saved: {png_path}")
    return png_path


# ---------------------------------------------------------------------------
# 1. Template quality — bar chart: pass/fail per architecture
# ---------------------------------------------------------------------------


def fig_template_quality(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    arches = list(summary.template_quality.keys())
    if not arches:
        ax.text(0.5, 0.5, "No template data", ha="center", va="center", transform=ax.transAxes)
        return _save_figure(fig, _next_fig_id("template_quality"))

    x = np.arange(len(arches))
    width = 0.35

    passes = [summary.template_quality[a].passes for a in arches]
    failures = [summary.template_quality[a].failures for a in arches]

    ax.bar(x - width / 2, passes, width, label="Pass", color="#228833", alpha=0.85)
    ax.bar(x + width / 2, failures, width, label="Fail", color="#CC3311", alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(arches, rotation=25, ha="right")
    ax.set_ylabel("Count")
    ax.set_title("Template Quality by Architecture")
    ax.legend()

    return _save_figure(fig, _next_fig_id("template_quality"))


# ---------------------------------------------------------------------------
# 2. Patch success trend — running success rate over patch log entries
# ---------------------------------------------------------------------------


def fig_patch_success_trend(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    patches = summary.dissect_effectiveness.patches_by_job
    if len(patches) < 3:
        ax.text(
            0.5,
            0.5,
            "Not enough patch data (need >=3)",
            ha="center",
            va="center",
            transform=ax.transAxes,
        )
        return _save_figure(fig, _next_fig_id("patch_trend"))

    outcomes = [1 if p.patch_outcome == "success" else 0 for p in patches]
    window = max(1, len(outcomes) // 10)
    running_avg = np.convolve(outcomes, np.ones(window) / window, mode="valid")

    ax.plot(range(len(running_avg)), running_avg, color="#4477AA", linewidth=2)
    ax.axhline(y=0.5, color="#CC3311", linestyle="--", alpha=0.5, label="50% threshold")
    ax.set_xlabel("Patch attempt sequence")
    ax.set_ylabel("Running success rate")
    ax.set_title("Dissect Patch Success Rate Over Time")
    ax.set_ylim(0, 1.05)
    ax.legend()

    return _save_figure(fig, _next_fig_id("patch_trend"))


# ---------------------------------------------------------------------------
# 3. Error category distribution — horizontal bar
# ---------------------------------------------------------------------------


def fig_error_category_distribution(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    dist = summary.dissect_effectiveness.error_category_distribution
    if not dist:
        ax.text(
            0.5, 0.5, "No error category data", ha="center", va="center", transform=ax.transAxes
        )
        return _save_figure(fig, _next_fig_id("error_categories"))

    cats = sorted(dist, key=dist.get)
    vals = [dist[c] for c in cats]
    colors = COLORS_DARK[: len(cats)] if len(cats) <= len(COLORS_DARK) else None

    ax.barh(cats, vals, color=colors, alpha=0.8)
    ax.set_xlabel("Occurrences")
    ax.set_title("Error Category Distribution")

    return _save_figure(fig, _next_fig_id("error_categories"))


# ---------------------------------------------------------------------------
# 4. Performance breakdown — stacked bar per problem
# ---------------------------------------------------------------------------


def fig_performance_breakdown(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    profiles = summary.performance_profile.profiles[:20]
    if not profiles:
        ax.text(0.5, 0.5, "No performance data", ha="center", va="center", transform=ax.transAxes)
        return _save_figure(fig, _next_fig_id("performance"))

    pids = [p.problem_id for p in profiles]
    x = np.arange(len(pids))
    bottom = np.zeros(len(pids))
    colors = ["#4477AA", "#EE6677", "#228833", "#CC3311", "#AA3377"]
    labels = ["scout", "forge", "training", "evaluation", "patch_overhead"]

    has_any = False
    for i, label in enumerate(labels):
        vals = [p.breakdown.get(label, 0) for p in profiles]
        if any(v > 0 for v in vals):
            has_any = True
            ax.bar(x, vals, bottom=bottom, label=label, color=colors[i], alpha=0.85)
            for j in range(len(vals)):
                bottom[j] += vals[j]

    ax.set_xticks(x)
    ax.set_xticklabels(pids, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("Duration (s)")
    ax.set_title("Performance Breakdown by Problem")
    if has_any:
        ax.legend()

    return _save_figure(fig, _next_fig_id("performance"))


# ---------------------------------------------------------------------------
# 5. LLM cost by agent — pie chart
# ---------------------------------------------------------------------------


def fig_llm_cost_breakdown(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(6, 6))
    cost_by_agent = summary.llm_usage.cost_by_agent_usd
    if not cost_by_agent:
        ax.text(0.5, 0.5, "No LLM cost data", ha="center", va="center", transform=ax.transAxes)
        return _save_figure(fig, _next_fig_id("llm_cost"))

    labels = list(cost_by_agent.keys())
    values = list(cost_by_agent.values())
    colors = COLORS_DARK[: len(labels)]
    ax.pie(values, labels=labels, autopct="%1.1f%%", colors=colors, startangle=90)
    ax.set_title("LLM Cost by Agent")

    return _save_figure(fig, _next_fig_id("llm_cost"))


# ---------------------------------------------------------------------------
# 6. Knowledge growth — cumulative patches over time
# ---------------------------------------------------------------------------


def fig_knowledge_growth(summary: EngineeringSummary) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    patches = summary.dissect_effectiveness.patches_by_job
    if len(patches) < 2:
        ax.text(0.5, 0.5, "Not enough patch data", ha="center", va="center", transform=ax.transAxes)
        return _save_figure(fig, _next_fig_id("knowledge_growth"))

    has_timestamps = all(p.timestamp for p in patches)
    if has_timestamps:
        try:
            from datetime import datetime

            timestamps = [
                datetime.fromisoformat(p.timestamp.replace("Z", "+00:00"))
                for p in patches
                if p.timestamp
            ]
            timestamps.sort()
            cumulative = list(range(1, len(timestamps) + 1))
            ax.plot(timestamps, cumulative, color="#228833", linewidth=2)
            ax.set_xlabel("Time")
        except Exception:
            ax.plot(
                range(len(patches)), list(range(1, len(patches) + 1)), color="#228833", linewidth=2
            )
            ax.set_xlabel("Patch sequence")
    else:
        ax.plot(range(len(patches)), list(range(1, len(patches) + 1)), color="#228833", linewidth=2)
        ax.set_xlabel("Patch sequence")

    ax.set_ylabel("Cumulative patches")
    ax.set_title("Knowledge Growth: Patch Memory Over Time")

    ax.legend(["Cumulative patches"])

    return _save_figure(fig, _next_fig_id("knowledge_growth"))


# ---------------------------------------------------------------------------
# Generate all figures
# ---------------------------------------------------------------------------


def generate_all_figures(summary: EngineeringSummary) -> list[Path]:
    paths: list[Path] = []
    paths.append(fig_template_quality(summary))
    paths.append(fig_patch_success_trend(summary))
    paths.append(fig_error_category_distribution(summary))
    paths.append(fig_performance_breakdown(summary))
    paths.append(fig_llm_cost_breakdown(summary))
    paths.append(fig_knowledge_growth(summary))
    return paths

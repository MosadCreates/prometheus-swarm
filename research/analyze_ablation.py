"""Ablation campaign analysis — statistics, hypothesis tests, and paper figures.

Reads research/reports/ablation_results.json and produces:
  - research/reports/ablation_analysis.json  (per-config stats + hypothesis tests)
  - research/figures/fig_*.png / fig_*.svg   (publication-quality figures)
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from scipy import stats as scipy_stats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("analyze_ablation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "research" / "reports"
FIGURES_DIR = PROJECT_ROOT / "research" / "figures"
ABLATION_PATH = REPORTS_DIR / "ablation_results.json"
ANALYSIS_OUT = REPORTS_DIR / "ablation_analysis.json"

# -- Style ----------------------------------------------------------------

ABLATION_PALETTE = {
    1: "#BBBBBB",
    2: "#4477AA",
    3: "#AA3377",
    4: "#EE6677",
    5: "#DDCC77",
    6: "#228833",
    7: "#0077BB",
}

ABLATION_LABELS = {
    1: "OFF/OFF/OFF",
    2: "ON/OFF/OFF",
    3: "OFF/ON/OFF",
    4: "OFF/OFF/ON",
    5: "ON/ON/OFF",
    6: "ON/OFF/ON",
    7: "ON/ON/ON (full)",
}

ABLATION_SHORT = {
    1: "C1: Raw",
    2: "C2: Planner",
    3: "C3: Memory",
    4: "C4: Dissect",
    5: "C5: Planner+Mem",
    6: "C6: Planner+Dissect",
    7: "C7: Full",
}

CONFIG_GROUPS = {
    "no_dissect": [1, 2, 3, 5],
    "with_dissect": [4, 6, 7],
}

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
        "savefig.dpi": 600,
        "savefig.format": "png",
        "savefig.bbox": "tight",
        "axes.grid": False,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)

_FIGURE_COUNTER: dict[str, int] = {}


def _next_fid(prefix: str) -> str:
    _FIGURE_COUNTER[prefix] = _FIGURE_COUNTER.get(prefix, 0) + 1
    return f"{prefix}_{_FIGURE_COUNTER[prefix]:02d}"


def _save_fig(fig: matplotlib.figure.Figure, fid: str) -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    png = FIGURES_DIR / f"{fid}.png"
    svg = FIGURES_DIR / f"{fid}.svg"
    fig.savefig(png, dpi=600)
    fig.savefig(svg, format="svg")
    plt.close(fig)
    logger.info(f"  Saved {png.name}")
    return png


# -- Data loading ---------------------------------------------------------


def load_ablation(path: Path = ABLATION_PATH) -> dict:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def config_runs(data: dict, config_id: int) -> list[dict]:
    return [r for r in data["runs"] if r["config_id"] == config_id]


# -- Statistics ------------------------------------------------------------


def cohens_d(a: list[float], b: list[float]) -> float:
    if len(a) < 2 or len(b) < 2:
        return 0.0
    na, nb = len(a), len(b)
    mua, mub = np.mean(a), np.mean(b)
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return 0.0 if pooled == 0 else (mub - mua) / pooled


def effect_size_label(d: float) -> str:
    ad = abs(d)
    if ad < 0.2:
        return "negligible"
    if ad < 0.5:
        return "small"
    if ad < 0.8:
        return "medium"
    return "large"


def bootstrap_ci(a: list[float], b: list[float], n: int = 10_000) -> tuple[float, float]:
    if len(a) < 2 or len(b) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(42)
    diffs = np.zeros(n)
    for i in range(n):
        ba = rng.choice(a, size=len(a), replace=True)
        bb = rng.choice(b, size=len(b), replace=True)
        diffs[i] = np.mean(bb) - np.mean(ba)
    return (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))


def compare_configs(
    runs_a: list[dict], runs_b: list[dict], metric: str = "duration_seconds"
) -> dict:
    vals_a = [r[metric] for r in runs_a if r.get(metric) is not None and r[metric] > 0]
    vals_b = [r[metric] for r in runs_b if r.get(metric) is not None and r[metric] > 0]
    result = {"metric": metric, "n_a": len(vals_a), "n_b": len(vals_b)}

    if not vals_a or not vals_b:
        result.update({"p_value": None, "effect_size": None, "significant": False})
        return result

    stat, p_val = scipy_stats.mannwhitneyu(vals_a, vals_b, alternative="two-sided")
    cd = cohens_d(vals_a, vals_b)
    ci_low, ci_high = bootstrap_ci(vals_a, vals_b)

    result.update(
        {
            "mean_a": float(np.mean(vals_a)),
            "mean_b": float(np.mean(vals_b)),
            "median_a": float(np.median(vals_a)),
            "median_b": float(np.median(vals_b)),
            "p_value": float(p_val),
            "effect_size": float(cd),
            "effect_size_label": effect_size_label(cd),
            "ci_lower": ci_low,
            "ci_upper": ci_high,
            "significant": bool(p_val < 0.05),
            "test_used": "Mann-Whitney U",
        }
    )
    return result


def compute_per_config_stats(data: dict) -> dict:
    stats = {}
    for cid in data["configs"]:
        runs = config_runs(data, cid)
        label = data["config_labels"].get(str(cid), f"Config {cid}")
        total = len(runs)
        successes = sum(1 for r in runs if r["status"] in ("pass", "retry"))
        crashes = sum(1 for r in runs if r["status"] == "crash")
        escalations = sum(1 for r in runs if r["status"] in ("escalate", "error"))
        skips = sum(1 for r in runs if r["status"] == "skipped")
        durations = [r["duration_seconds"] for r in runs if r["duration_seconds"] > 0]
        crash_counts = [r["crash_count"] for r in runs]
        metrics = [r["best_val_metric"] for r in runs if r["best_val_metric"] > 0]
        patches = [r["patch_successes"] for r in runs if r.get("patch_successes", 0) > 0]
        errors = [r.get("error", "") for r in runs if r.get("error")]

        stats[str(cid)] = {
            "config": cid,
            "label": label,
            "total": total,
            "successes": successes,
            "crashes": crashes,
            "escalations": escalations,
            "skipped": skips,
            "success_rate": round(successes / max(total, 1) * 100, 1),
            "crash_rate": round(crashes / max(total, 1) * 100, 1),
            "mean_duration_s": round(float(np.mean(durations)), 1) if durations else 0,
            "median_duration_s": round(float(np.median(durations)), 1) if durations else 0,
            "min_duration_s": round(float(np.min(durations)), 1) if durations else 0,
            "max_duration_s": round(float(np.max(durations)), 1) if durations else 0,
            "mean_crashes": round(float(np.mean(crash_counts)), 2),
            "total_crashes": int(sum(crash_counts)),
            "mean_metric": round(float(np.mean(metrics)), 4) if metrics else 0.0,
            "median_metric": round(float(np.median(metrics)), 4) if metrics else 0.0,
            "total_patches": int(sum(patches)),
            "errors": errors[:5],
        }
    return stats


def compute_hypothesis_tests(data: dict) -> dict:
    """Test hypotheses H1-H5 using ablation config pairs."""
    # Hypothesis mapping from ablation configs
    # H1: Planner reduces prediction error (C2 vs C1)
    # H2: Patch memory improves recovery (C3 vs C1)
    # H3: Dissect improves deployment success (C4 vs C1)
    # H4: Planner + memory reduces retries (C5 vs C1)
    # H5: Full system outperforms all (C7 vs C1)

    hypotheses = {
        "H1": {
            "name": "Planner reduces prediction error",
            "a": 1,
            "b": 2,
            "metric": "duration_seconds",
        },
        "H2": {
            "name": "Patch memory improves recovery",
            "a": 1,
            "b": 3,
            "metric": "crash_count",
        },
        "H3": {
            "name": "Dissect improves deployment success",
            "a": 1,
            "b": 4,
            "metric": "duration_seconds",
        },
        "H4": {
            "name": "Planner+Memory reduces retries",
            "a": 1,
            "b": 5,
            "metric": "crash_count",
        },
        "H5": {
            "name": "Full system outperforms all",
            "a": 1,
            "b": 7,
            "metric": "duration_seconds",
        },
    }

    results = {}
    for hid, hinfo in hypotheses.items():
        runs_a = config_runs(data, hinfo["a"])
        runs_b = config_runs(data, hinfo["b"])
        cr = compare_configs(runs_a, runs_b, hinfo["metric"])
        cr["config_a"] = hinfo["a"]
        cr["config_b"] = hinfo["b"]
        cr["config_a_label"] = data["config_labels"].get(str(hinfo["a"]), "")
        cr["config_b_label"] = data["config_labels"].get(str(hinfo["b"]), "")
        results[hid] = cr
    return results


# -- Figures ----------------------------------------------------------------


def fig_deployment_success_rate(data: dict) -> Path:
    fig, ax = plt.subplots(figsize=(7, 5))
    stats = compute_per_config_stats(data)
    cids = sorted(data["configs"])
    rates = [stats[str(c)]["success_rate"] for c in cids]
    colors = [ABLATION_PALETTE[c] for c in cids]
    labels = [ABLATION_SHORT[c] for c in cids]

    bars = ax.bar(range(len(cids)), rates, width=0.6, color=colors, alpha=0.85, edgecolor="white")
    ax.bar_label(bars, fmt="%.1f%%", padding=2, fontsize=8)
    ax.set_xticks(range(len(cids)))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Deployment success rate (%)")
    ax.set_ylim(0, 100)
    ax.set_title("Deployment Success Rate Across 7 Ablation Configurations")

    # Horizontal line at 0 for reference
    ax.axhline(0, color="black", linewidth=0.5)

    return _save_fig(fig, _next_fid("fig_ablation_deployment"))


def fig_duration_boxplot(data: dict) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    cids = sorted(data["configs"])
    all_data = []
    labels = []
    colors = []

    for c in cids:
        runs = config_runs(data, c)
        vals = [r["duration_seconds"] for r in runs if r["duration_seconds"] > 0]
        if vals:
            all_data.append(vals)
            labels.append(ABLATION_SHORT[c])
            colors.append(ABLATION_PALETTE[c])

    bp = ax.boxplot(all_data, patch_artist=True, widths=0.5)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    for i, vals in enumerate(all_data):
        jitter = np.random.default_rng(42).uniform(-0.15, 0.15, len(vals))
        ax.scatter(np.full(len(vals), i + 1) + jitter, vals, alpha=0.3, s=12, c=colors[i])

    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Duration (s)")
    ax.set_title("Execution Duration per Ablation Configuration")

    return _save_fig(fig, _next_fid("fig_ablation_duration"))


def fig_crash_heatmap(data: dict) -> Path:
    fig, ax = plt.subplots(figsize=(8, 4))
    cids = sorted(data["configs"])
    problems = data["problems"]

    matrix = np.zeros((len(problems), len(cids)))
    for i, pid in enumerate(problems):
        for j, c in enumerate(cids):
            runs = [r for r in data["runs"] if r["problem_id"] == pid and r["config_id"] == c]
            if runs:
                matrix[i, j] = runs[0]["crash_count"]

    im = ax.imshow(matrix, cmap="YlOrRd", aspect="auto", vmin=0)
    ax.set_xticks(range(len(cids)))
    ax.set_xticklabels([ABLATION_SHORT[c] for c in cids], rotation=20, ha="right", fontsize=7)
    ax.set_yticks(range(len(problems)))
    ax.set_yticklabels(problems, fontsize=8)
    ax.set_xlabel("Configuration")
    ax.set_ylabel("Problem")
    ax.set_title("Crash Counts: Problem × Configuration")

    cbar = fig.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label("Crash count")

    for i in range(len(problems)):
        for j in range(len(cids)):
            val = int(matrix[i, j])
            color = "white" if val > 1 else "black"
            ax.text(j, i, str(val), ha="center", va="center", fontsize=8, color=color)

    return _save_fig(fig, _next_fid("fig_ablation_crashes"))


def fig_metric_comparison(data: dict) -> Path:
    fig, ax = plt.subplots(figsize=(8, 5))
    cids = sorted(data["configs"])

    for c in cids:
        runs = config_runs(data, c)
        metrics = [r["best_val_metric"] for r in runs if r["best_val_metric"] > 0]
        if not metrics:
            continue
        ax.scatter(
            [c] * len(metrics),
            metrics,
            color=ABLATION_PALETTE[c],
            alpha=0.6,
            s=30,
            edgecolor="white",
            linewidth=0.5,
            label=ABLATION_SHORT[c],
        )
        ax.scatter(
            c, np.mean(metrics), color=ABLATION_PALETTE[c], s=120, marker="_", linewidth=3, zorder=5
        )

    ax.set_xticks(cids)
    ax.set_xticklabels([ABLATION_SHORT[c] for c in cids], rotation=20, ha="right", fontsize=8)
    ax.set_ylabel("Best validation metric")
    ax.set_title("Best Validation Metric per Configuration")
    ax.legend(fontsize=7, loc="lower right")

    return _save_fig(fig, _next_fid("fig_ablation_metrics"))


def fig_radar_comparison(data: dict) -> Path:
    """Radar chart comparing configs across multiple dimensions."""
    stats = compute_per_config_stats(data)
    cids = sorted(data["configs"])

    dimensions = ["Success Rate", "Duration (inv)", "Crash Count (inv)", "Metric Score"]
    dim_values = {
        str(c): [
            s["success_rate"],
            max(0, 100 - s["mean_duration_s"] / 2),
            max(0, 100 - s["mean_crashes"] * 30),
            s["mean_metric"] * 100 if s["mean_metric"] > 0 else 0,
        ]
        for c in cids
        if (s := stats.get(str(c)))
    }

    n_dim = len(dimensions)
    angles = np.linspace(0, 2 * np.pi, n_dim, endpoint=False).tolist()
    angles += angles[:1]

    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(polar=True))

    for c in cids:
        key = str(c)
        if key not in dim_values:
            continue
        values = dim_values[key] + dim_values[key][:1]
        ax.plot(
            angles,
            values,
            "o-",
            color=ABLATION_PALETTE[c],
            linewidth=2,
            label=ABLATION_SHORT[c],
            alpha=0.8,
        )
        ax.fill(angles, values, color=ABLATION_PALETTE[c], alpha=0.05)

    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(dimensions, fontsize=9)
    ax.set_ylim(0, 100)
    ax.set_title("Multi-Dimensional Comparison", pad=25)
    ax.legend(loc="upper right", bbox_to_anchor=(1.3, 1.1), fontsize=8)

    return _save_fig(fig, _next_fid("fig_ablation_radar"))


def generate_all_figures(data: dict) -> list[Path]:
    paths = []
    paths.append(fig_deployment_success_rate(data))
    paths.append(fig_duration_boxplot(data))
    paths.append(fig_crash_heatmap(data))
    paths.append(fig_metric_comparison(data))
    paths.append(fig_radar_comparison(data))
    return paths


# -- Main ------------------------------------------------------------------


def main():
    data = load_ablation()
    print(f"\n  {'='*60}")
    print(f"  Ablation Analysis - {len(data['runs'])} runs across {len(data['problems'])} problems")
    print(f"  {'='*60}\n")

    # Per-config stats
    stats = compute_per_config_stats(data)
    print(
        f"  {'Config':<20} {'Success':>8} {'Crash':>8} {'Esc':>8} {'Rate':>8} {'Avg(s)':>8} {'Metric':>8}"
    )
    print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for cid in sorted(data["configs"]):
        s = stats[str(cid)]
        print(
            f"  {s['label']:<20} {s['successes']:>8} {s['crashes']:>8} {s['escalations']:>8} {s['success_rate']:>7.1f}% {s['mean_duration_s']:>7.1f} {s['mean_metric']:>7.4f}"
        )

    # Group comparisons
    print(f"\n  {'-'*60}")
    print("  Group Comparison: Dissect vs No-Dissect")
    print(f"  {'-'*60}")

    no_dissect = [r for c in CONFIG_GROUPS["no_dissect"] for r in config_runs(data, c)]
    with_dissect = [r for c in CONFIG_GROUPS["with_dissect"] for r in config_runs(data, c)]

    nd_success = sum(1 for r in no_dissect if r["status"] in ("pass", "retry"))
    wd_success = sum(1 for r in with_dissect if r["status"] in ("pass", "retry"))
    nd_rate = nd_success / max(len(no_dissect), 1) * 100
    wd_rate = wd_success / max(len(with_dissect), 1) * 100
    print(f"  No Dissect:     {nd_rate:.1f}% ({nd_success}/{len(no_dissect)})")
    print(f"  With Dissect:   {wd_rate:.1f}% ({wd_success}/{len(with_dissect)})")

    # Hypothesis tests
    print(f"\n  {'-'*60}")
    print("  Hypothesis Tests (Mann-Whitney U)")
    print(f"  {'-'*60}")
    hyp_tests = compute_hypothesis_tests(data)
    hyp_defs = {
        "H1": "Planner reduces prediction error (C2 vs C1)",
        "H2": "Patch memory improves recovery (C3 vs C1)",
        "H3": "Dissect improves deployment success (C4 vs C1)",
        "H4": "Planner+Memory reduces retries (C5 vs C1)",
        "H5": "Full system outperforms all (C7 vs C1)",
    }
    for hid, cr in sorted(hyp_tests.items()):
        sig = " OK" if cr.get("significant") else " XX"
        print(f"  {hid}: {hyp_defs.get(hid, '?')}")
        print(f"       {cr['config_a_label']} vs {cr['config_b_label']}")
        print(
            f"       metric={cr['metric']} p={cr['p_value']:.4f} d={cr['effect_size']:.3f}"
            f" ({cr['effect_size_label']}) [{cr['ci_lower']:.3f}, {cr['ci_upper']:.3f}]{sig}"
        )

    # Figures
    print(f"\n  {'-'*60}")
    print("  Generating Figures")
    print(f"  {'-'*60}")
    fig_paths = generate_all_figures(data)

    # Save analysis report
    report = {
        "timestamp": __import__("time").time(),
        "total_runs": len(data["runs"]),
        "total_problems": len(data["problems"]),
        "per_config_stats": stats,
        "hypothesis_tests": hyp_tests,
        "dissect_vs_no_dissect": {
            "no_dissect_rate_pct": round(nd_rate, 1),
            "with_dissect_rate_pct": round(wd_rate, 1),
            "no_dissect_successes": nd_success,
            "no_dissect_total": len(no_dissect),
            "with_dissect_successes": wd_success,
            "with_dissect_total": len(with_dissect),
        },
        "figures": [p.name for p in fig_paths],
    }
    ANALYSIS_OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(ANALYSIS_OUT, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n  Analysis saved: {ANALYSIS_OUT}")
    print(f"  Figures: {len(fig_paths)} saved to {FIGURES_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

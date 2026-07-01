"""
Statistical analysis for the 50-problem benchmark.
Compares Condition B (no Dissect) vs Condition C (with Dissect).

Outputs: research/benchmark/results/statistical_analysis_v1.json
"""

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import mannwhitneyu, chi2

BASELINE_PATH = Path("research/benchmark/baseline_v1.json")
OUTPUT_PATH = Path("research/benchmark/results/statistical_analysis_v1.json")

with open(BASELINE_PATH) as f:
    baseline = json.load(f)

b_results = baseline["condition_b"]["results"]
c_results = baseline["condition_c"]["results"]


def is_pass(r):
    return r["status"] == "pass"


b_metrics = np.array([r["best_val_metric"] for r in b_results])
c_metrics = np.array([r["best_val_metric"] for r in c_results])

b_pass = np.array([1 if is_pass(r) else 0 for r in b_results])
c_pass = np.array([1 if is_pass(r) else 0 for r in c_results])

b_metrics_nonzero = b_metrics[b_metrics > 0]


def desc_stats(arr):
    return {
        "n": int(len(arr)),
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(np.std(arr, ddof=1)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
    }


desc_b = desc_stats(b_metrics)
desc_c = desc_stats(c_metrics)

u_stat, u_pval = mannwhitneyu(b_metrics, c_metrics, alternative="two-sided")

paired = sorted(set(r["problem_id"] for r in b_results) & set(r["problem_id"] for r in c_results))
b_lookup = {r["problem_id"]: r for r in b_results}
c_lookup = {r["problem_id"]: r for r in c_results}

n00 = n01 = n10 = n11 = 0
for pid in paired:
    bp = is_pass(b_lookup[pid])
    cp = is_pass(c_lookup[pid])
    if not bp and not cp:
        n00 += 1
    elif not bp and cp:
        n01 += 1
    elif bp and not cp:
        n10 += 1
    else:
        n11 += 1

b_discordant = n01
c_discordant = n10
total_discordant = b_discordant + c_discordant

if total_discordant > 0:
    mcnemar_stat = (abs(b_discordant - c_discordant) - 1) ** 2 / total_discordant
    mcnemar_pval = 1.0 - chi2.cdf(mcnemar_stat, df=1)
else:
    mcnemar_stat = 0.0
    mcnemar_pval = 1.0

pass_rate_b = baseline["comparison"]["pass_rate_b"]
pass_rate_c = baseline["comparison"]["pass_rate_c"]


def cohens_h(p1, p2):
    return abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


effect_size_h = round(cohens_h(pass_rate_b, pass_rate_c), 4)


def get_git_commit() -> str:
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


b_interventions = np.array([r.get("human_interventions", 1) for r in b_results])
c_interventions = np.array([r.get("human_interventions", 1) for r in c_results])

int_u_stat, int_u_pval = mannwhitneyu(b_interventions, c_interventions, alternative="greater")

# Rank-biserial correlation for effect size on interventions
n_b = len(b_interventions)
n_c = len(c_interventions)
rank_biserial_r = (
    1 - (2 * int_u_stat) / (n_b * len(c_interventions)) if n_b * len(c_interventions) > 0 else 0.0
)

results = {
    "baseline": "baseline_v1.json",
    "metadata": {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
    },
    "descriptive_statistics": {
        "condition_b": desc_b,
        "condition_c": desc_c,
    },
    "pass_rates": {
        "condition_b": pass_rate_b,
        "condition_c": pass_rate_c,
        "improvement_pp": baseline["comparison"]["improvement_pp"],
    },
    "mann_whitney_u_metrics": {
        "statistic": round(float(u_stat), 4),
        "p_value": round(float(u_pval), 6),
        "significant": bool(u_pval < 0.05),
        "alpha": 0.05,
    },
    "mcnemar_test": {
        "contingency_table": {
            "b_fail_c_fail": n00,
            "b_fail_c_pass": n01,
            "b_pass_c_fail": n10,
            "b_pass_c_pass": n11,
        },
        "statistic": round(float(mcnemar_stat), 4),
        "p_value": round(float(mcnemar_pval), 6),
        "significant": bool(mcnemar_pval < 0.05),
        "alpha": 0.05,
    },
    "cohens_h": {
        "effect_size": effect_size_h,
        "interpretation": (
            "negligible"
            if effect_size_h < 0.2
            else "small"
            if effect_size_h < 0.5
            else "medium"
            if effect_size_h < 0.8
            else "large"
        ),
    },
    "interventions_analysis": {
        "condition_b": {
            "mean": round(float(np.mean(b_interventions)), 4),
            "median": round(float(np.median(b_interventions)), 4),
            "total": int(np.sum(b_interventions)),
            "n": int(len(b_interventions)),
        },
        "condition_c": {
            "mean": round(float(np.mean(c_interventions)), 4),
            "median": round(float(np.median(c_interventions)), 4),
            "total": int(np.sum(c_interventions)),
            "n": int(len(c_interventions)),
        },
        "mann_whitney_u": {
            "statistic": round(float(int_u_stat), 4),
            "p_value": round(float(int_u_pval), 6),
            "significant": bool(int_u_pval < 0.05),
            "alpha": 0.05,
            "alternative": "greater",
        },
        "rank_biserial_r": round(float(rank_biserial_r), 4),
        "reduction": round(float(np.mean(b_interventions) - np.mean(c_interventions)), 4),
    },
}

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUTPUT_PATH, "w") as f:
    json.dump(results, f, indent=2)

print("=" * 60)
print("STATISTICAL ANALYSIS: 50-Problem Benchmark (Baseline v1)")
print("=" * 60)

print(f"\n{'Metric':<30} {'Condition B':>15} {'Condition C':>15}")
print("-" * 60)
print(f"{'n':<30} {desc_b['n']:>15} {desc_c['n']:>15}")
print(f"{'Mean':<30} {desc_b['mean']:>15} {desc_c['mean']:>15}")
print(f"{'Median':<30} {desc_b['median']:>15} {desc_c['median']:>15}")
print(f"{'Std Dev':<30} {desc_b['std']:>15} {desc_c['std']:>15}")
print(f"{'Min':<30} {desc_b['min']:>15} {desc_c['min']:>15}")
print(f"{'Max':<30} {desc_b['max']:>15} {desc_c['max']:>15}")

print(f"\n{'Pass Rate':<30} {pass_rate_b:>15.4f} {pass_rate_c:>15.4f}")
print(f"{'Improvement (pp)':<30} {baseline['comparison']['improvement_pp']:>15.4f}")

print("\n--- Mann-Whitney U Test (metrics) ---")
print(f"  U statistic: {u_stat:.4f}")
print(f"  p-value:     {u_pval:.6f}")
print(f"  Significant: {'Yes' if u_pval < 0.05 else 'No'} (alpha=0.05)")

print("\n--- McNemar's Test (pass/fail paired) ---")
print("  Contingency table:")
print(f"    B fail, C fail:  {n00:>3}")
print(f"    B fail, C pass:  {n01:>3}  (improvement cells)")
print(f"    B pass, C fail:  {n10:>3}  (regression cells)")
print(f"    B pass, C pass:  {n11:>3}")
print(f"  Statistic: {mcnemar_stat:.4f}")
print(f"  p-value:   {mcnemar_pval:.6f}")
print(f"  Significant: {'Yes' if mcnemar_pval < 0.05 else 'No'} (alpha=0.05)")

print("\n--- Cohen's h Effect Size (pass rates) ---")
print(f"  h = {effect_size_h:.4f}")
if effect_size_h < 0.2:
    print("  Interpretation: negligible")
elif effect_size_h < 0.5:
    print("  Interpretation: small")
elif effect_size_h < 0.8:
    print("  Interpretation: medium")
else:
    print("  Interpretation: large")

print("\n--- Interventions Analysis ---")
print(f"  B total interventions: {int(np.sum(b_interventions))}")
print(f"  C total interventions: {int(np.sum(c_interventions))}")
print(f"  Reduction: {float(np.mean(b_interventions) - np.mean(c_interventions)):.1f}")
print(f"  MWU (one-sided greater): U={int_u_stat:.1f}, p={int_u_pval:.6f}")
print(f"  Rank-biserial r: {rank_biserial_r:.4f}")

print(f"\nResults saved to: {OUTPUT_PATH}")

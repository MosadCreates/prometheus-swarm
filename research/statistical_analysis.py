"""
Statistical analysis for the Prometheus Swarm benchmark.
Compares Condition B (no Dissect) vs Condition C (with Dissect),
optionally Condition A (human baseline) vs B/C.

Integrity rules (why this script is written the way it is):
  1. best_val_metric is NOT scale-comparable across task types — AUC sits in
     [0,1] while RMSE lives in the hundreds. Mann-Whitney U on metrics is
     therefore computed PER TASK TYPE (auc_roc / f1 classification, rmse
     regression), never pooled.
  2. Failed/crashed problems must not be coerced to metric 0.0 — metric tests
     run only on rows where BOTH conditions produced a real metric.
  3. McNemar's test on pass/fail is scale-free and paired by problem_id, so an
     overall McNemar across all problems remains valid.

Usage:
    python -m research.statistical_analysis [--baseline path/to/baseline.json]
                                             [--output path/to/analysis.json]
"""

import argparse
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import chi2, mannwhitneyu

ALPHA = 0.05
DEFAULT_BASELINE = Path("research/benchmark/results/baseline_v2.json")
DEFAULT_OUTPUT = Path("research/benchmark/results/statistical_analysis_v2.json")

# task families that share a comparable metric scale
TASK_FAMILY = {
    "auc_roc": "classification_auc",
    "f1": "classification_f1",
    "accuracy": "classification_auc",
    "rmse": "regression_rmse",
    "mae": "regression_rmse",
}


def is_pass(r: dict) -> bool:
    return r["status"] == "pass"


def metric_family(problem: dict, row: dict) -> str:
    metric = problem.get("evaluation_metric") or row.get("evaluation_metric") or "auc_roc"
    return TASK_FAMILY.get(metric, f"other_{metric}")


def desc_stats(arr: np.ndarray) -> dict:
    return {
        "n": int(len(arr)),
        "mean": round(float(np.mean(arr)), 6),
        "median": round(float(np.median(arr)), 6),
        "std": round(float(np.std(arr, ddof=1)), 6),
        "min": round(float(np.min(arr)), 6),
        "max": round(float(np.max(arr)), 6),
    }


def cohens_h(p1: float, p2: float) -> float:
    return abs(2 * math.asin(math.sqrt(p1)) - 2 * math.asin(math.sqrt(p2)))


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


def mcnemar(pairs_b: dict[str, bool], pairs_c: dict[str, bool]) -> dict:
    common = sorted(set(pairs_b) & set(pairs_c))
    n00 = n01 = n10 = n11 = 0
    for pid in common:
        bp, cp = pairs_b[pid], pairs_c[pid]
        if not bp and not cp:
            n00 += 1
        elif not bp and cp:
            n01 += 1
        elif bp and not cp:
            n10 += 1
        else:
            n11 += 1
    discordant = n01 + n10
    if discordant > 0:
        stat = (abs(n01 - n10) - 1) ** 2 / discordant
        pval = float(1.0 - chi2.cdf(stat, df=1))
    else:
        stat, pval = 0.0, 1.0
    return {
        "n_paired": len(common),
        "contingency_table": {
            "b_fail_c_fail": n00,
            "b_fail_c_pass": n01,
            "b_pass_c_fail": n10,
            "b_pass_c_pass": n11,
        },
        "statistic": round(float(stat), 4),
        "p_value": round(pval, 6),
        "significant": bool(pval < ALPHA),
        "alpha": ALPHA,
    }


def analyze_family(b_rows: list[dict], c_rows: list[dict]) -> dict | None:
    """MWU on metrics for one task family, using only paired real metrics.

    Only rows where the job actually TRAINED and was evaluated (status
    pass/escalate/retry) contribute metrics; crash/timeout rows carry a
    0.0 placeholder which is not a measurement and would corrupt the test.
    """
    measurable = ("pass", "escalate", "retry")
    b_idx = {r["problem_id"]: r for r in b_rows if r.get("status") in measurable}
    c_idx = {r["problem_id"]: r for r in c_rows if r.get("status") in measurable}
    common = sorted(set(b_idx) & set(c_idx))
    if len(common) < 3:
        return None
    bm = np.array([b_idx[p]["best_val_metric"] for p in common])
    cm = np.array([c_idx[p]["best_val_metric"] for p in common])
    u_stat, u_pval = mannwhitneyu(bm, cm, alternative="two-sided")
    n_b = len(bm)
    n_c = len(cm)
    rank_biserial = 1 - (2 * u_stat) / (n_b * n_c) if n_b * n_c else 0.0
    return {
        "n": len(common),
        "condition_b": desc_stats(bm),
        "condition_c": desc_stats(cm),
        "mann_whitney_u": {
            "statistic": round(float(u_stat), 4),
            "p_value": round(float(u_pval), 6),
            "significant": bool(u_pval < ALPHA),
            "alpha": ALPHA,
            "alternative": "two-sided",
        },
        "rank_biserial_r": round(float(rank_biserial), 4),
    }


def analyze(baseline: dict) -> dict:
    for key in ("condition_b", "condition_c"):
        if not baseline.get(key) or "results" not in baseline[key]:
            raise SystemExit(
                f"Baseline file has no '{key}.results' — pass a COMBINED baseline "
                "(produced by run_benchmark --output, e.g. baseline_v2_rerun_*.json), "
                "not the campaign-style v2 summary."
            )
    b_results = baseline["condition_b"]["results"]
    c_results = baseline["condition_c"]["results"]
    problems_meta = {p["id"]: p for p in baseline.get("problems", [])}  # optional embedded metadata
    if not problems_meta:
        # Fallback: read benchmark problem definitions from disk so baseline
        # files without embedded metadata still map problems to metric families.
        pf = Path("research/benchmark/problems.json")
        if pf.exists():
            with open(pf, encoding="utf-8") as f:
                pdata = json.load(f)
            plist = pdata.get("problems", pdata if isinstance(pdata, list) else [])
            problems_meta = {p["id"]: p for p in plist}

    def family_of(row: dict) -> str:
        meta = problems_meta.get(row.get("problem_id", ""), {})
        return metric_family(meta, row)

    b_by_family: dict[str, list[dict]] = {}
    c_by_family: dict[str, list[dict]] = {}
    for r in b_results:
        b_by_family.setdefault(family_of(r), []).append(r)
    for r in c_results:
        c_by_family.setdefault(family_of(r), []).append(r)

    per_family = {}
    for fam in sorted(set(b_by_family) | set(c_by_family)):
        analysis = analyze_family(b_by_family.get(fam, []), c_by_family.get(fam, []))
        if analysis:
            per_family[fam] = analysis

    # Overall pass/fail — scale-free and paired
    b_pass_map = {r["problem_id"]: is_pass(r) for r in b_results}
    c_pass_map = {r["problem_id"]: is_pass(r) for r in c_results}
    overall_mcnemar = mcnemar(b_pass_map, c_pass_map)

    pass_rate_b = sum(b_pass_map.values()) / max(len(b_pass_map), 1)
    pass_rate_c = sum(c_pass_map.values()) / max(len(c_pass_map), 1)
    effect_h = round(cohens_h(pass_rate_b, pass_rate_c), 4)

    # Interventions (count data — comparable across problems)
    b_int = np.array([r.get("human_interventions", 1) for r in b_results])
    c_int = np.array([r.get("human_interventions", 1) for r in c_results])
    int_u_stat, int_u_pval = mannwhitneyu(b_int, c_int, alternative="greater")
    n_b, n_c = len(b_int), len(c_int)
    rank_biserial_r = 1 - (2 * int_u_stat) / (n_b * n_c) if n_b * n_c else 0.0

    # Optional Condition A (human baseline) comparisons — pass/fail only, plus
    # per-family metrics vs B (the swarm-without-repair) and vs C.
    a_block = None
    a_condition = baseline.get("condition_a")
    if a_condition and a_condition.get("results"):
        a_results = a_condition["results"]
        a_pass_map = {r["problem_id"]: is_pass(r) for r in a_results}
        a_by_family: dict[str, list[dict]] = {}
        for r in a_results:
            a_by_family.setdefault(family_of(r), []).append(r)
        a_families = {}
        for fam, rows in a_by_family.items():
            analysis = analyze_family(rows, c_by_family.get(fam, []))
            if analysis:
                a_families[fam] = analysis
        a_block = {
            "n": len(a_results),
            "pass_rate": round(sum(a_pass_map.values()) / max(len(a_pass_map), 1), 4),
            "mcnemar_a_vs_c": mcnemar(a_pass_map, c_pass_map),
            "mcnemar_a_vs_b": mcnemar(a_pass_map, b_pass_map),
            "metric_analysis_a_vs_c_per_family": a_families,
        }

    return {
        "baseline": {
            "execution_method": baseline.get("metadata", {}).get("execution_method", "unknown"),
            "git_commit_baseline": baseline.get("metadata", {}).get("git_commit", "unknown"),
            "date_baseline": baseline.get("metadata", {}).get("created_at", "unknown"),
        },
        "metadata": {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": get_git_commit(),
            "alpha": ALPHA,
            "note": (
                "Metric Mann-Whitney U computed per task family (AUC-classification, RMSE-regression); "
                "never pooled across scales. McNemar overall is paired pass/fail (scale-free)."
            ),
        },
        "pass_rates": {
            "condition_b": round(pass_rate_b, 4),
            "condition_c": round(pass_rate_c, 4),
            "improvement_pp": round(pass_rate_c - pass_rate_b, 4),
        },
        "mcnemar_overall": overall_mcnemar,
        "cohens_h": {
            "effect_size": effect_h,
            "interpretation": (
                "negligible"
                if effect_h < 0.2
                else "small"
                if effect_h < 0.5
                else "medium"
                if effect_h < 0.8
                else "large"
            ),
        },
        "metric_analysis_per_family": per_family,
        "interventions_analysis": {
            "condition_b": {
                "mean": round(float(np.mean(b_int)), 4),
                "median": round(float(np.median(b_int)), 4),
                "total": int(np.sum(b_int)),
                "n": int(n_b),
            },
            "condition_c": {
                "mean": round(float(np.mean(c_int)), 4),
                "median": round(float(np.median(c_int)), 4),
                "total": int(np.sum(c_int)),
                "n": int(n_c),
            },
            "mann_whitney_u": {
                "statistic": round(float(int_u_stat), 4),
                "p_value": round(float(int_u_pval), 6),
                "significant": bool(int_u_pval < ALPHA),
                "alpha": ALPHA,
                "alternative": "greater",
            },
            "rank_biserial_r": round(float(rank_biserial_r), 4),
            "reduction": round(float(np.mean(b_int) - np.mean(c_int)), 4),
        },
        "condition_a": a_block,
    }


def print_report(results: dict) -> None:
    print("=" * 66)
    print("STATISTICAL ANALYSIS — B (no Dissect) vs C (with Dissect)")
    print("=" * 66)
    pr = results["pass_rates"]
    print(
        f"\nPass rates:  B={pr['condition_b']:.2f}  C={pr['condition_c']:.2f}"
        f"  (+{pr['improvement_pp'] * 100:.1f} pp)"
    )

    m = results["mcnemar_overall"]
    print("\n--- McNemar's Test (paired pass/fail, all problems) ---")
    ct = m["contingency_table"]
    print(
        f"  paired n={m['n_paired']}  fail/fail={ct['b_fail_c_fail']} "
        f"fail/pass={ct['b_fail_c_pass']}  pass/fail={ct['b_pass_c_fail']} "
        f"pass/pass={ct['b_pass_c_pass']}"
    )
    print(
        f"  chi2={m['statistic']:.4f}  p={m['p_value']:.6f}  "
        f"significant={'Yes' if m['significant'] else 'No'}"
    )
    print(
        f"  Cohen's h = {results['cohens_h']['effect_size']:.4f} "
        f"({results['cohens_h']['interpretation']})"
    )

    print("\n--- Mann-Whitney U on metrics, PER TASK FAMILY (never pooled) ---")
    fams = results["metric_analysis_per_family"]
    if not fams:
        print("  (no family had >=3 paired metric rows — insufficient data)")
    for fam, a in fams.items():
        print(
            f"  {fam}: n={a['n']}  "
            f"B median={a['condition_b']['median']:.4f}  "
            f"C median={a['condition_c']['median']:.4f}  "
            f"U={a['mann_whitney_u']['statistic']:.1f}  "
            f"p={a['mann_whitney_u']['p_value']:.4f}  "
            f"{'SIG' if a['mann_whitney_u']['significant'] else 'ns'}"
        )

    iv = results["interventions_analysis"]
    print("\n--- Human interventions ---")
    print(
        f"  B mean={iv['condition_b']['mean']}  C mean={iv['condition_c']['mean']}  "
        f"MWU p={iv['mann_whitney_u']['p_value']:.4f}  "
        f"{'SIG' if iv['mann_whitney_u']['significant'] else 'ns'}"
    )

    if results.get("condition_a"):
        a = results["condition_a"]
        print(f"\n--- Condition A (human baseline), n={a['n']} ---")
        print(f"  A pass rate: {a['pass_rate']:.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark statistical analysis")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE), help="combined baseline JSON")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="analysis JSON output path")
    args = parser.parse_args()

    with open(args.baseline, encoding="utf-8") as f:
        baseline = json.load(f)

    if baseline.get("deprecated"):
        raise SystemExit(
            f"{args.baseline} is marked deprecated — point --baseline at the "
            "authoritative (v2/rerun) baseline file."
        )

    results = analyze(baseline)
    results["source_baseline"] = args.baseline

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print_report(results)
    print(f"\nResults saved to: {out}")


if __name__ == "__main__":
    main()

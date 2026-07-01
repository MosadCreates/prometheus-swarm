"""
Compare two baseline files and report improvements / regressions.

Usage:
    python research/compare_baselines.py --baseline research/benchmark/baseline_v1.json --current research/benchmark/baseline_v2.json
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def load_baseline(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        print(f"Error: Baseline file not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def format_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def format_delta(old: float, new: float) -> str:
    diff = new - old
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.4f}"


def compare(old: dict, new: dict) -> dict:
    ob = old.get("condition_b", {})
    oc = old.get("condition_c", {})
    nb = new.get("condition_b", {})
    nc = new.get("condition_c", {})
    od = old.get("dissect_metrics", {})
    nd = new.get("dissect_metrics", {})

    report = {
        "old_baseline": {
            "pass_rate": ob.get("passed", 0) / max(ob.get("total_problems", 1), 1),
            "avg_metric": ob.get("avg_metric", 0),
            "avg_duration": ob.get("avg_duration_seconds", 0),
            "interventions": ob.get("total_human_interventions", 0),
        },
        "new_baseline": {
            "pass_rate": nb.get("passed", 0) / max(nb.get("total_problems", 1), 1),
            "avg_metric": nb.get("avg_metric", 0),
            "avg_duration": nb.get("avg_duration_seconds", 0),
            "interventions": nb.get("total_human_interventions", 0),
        },
        "delta": {
            "pass_rate_b": format_delta(
                ob.get("passed", 0) / max(ob.get("total_problems", 1), 1),
                nb.get("passed", 0) / max(nb.get("total_problems", 1), 1),
            ),
            "pass_rate_c": format_delta(
                oc.get("passed", 0) / max(oc.get("total_problems", 1), 1),
                nc.get("passed", 0) / max(nc.get("total_problems", 1), 1),
            ),
            "avg_metric_b": format_delta(ob.get("avg_metric", 0), nb.get("avg_metric", 0)),
            "avg_metric_c": format_delta(oc.get("avg_metric", 0), nc.get("avg_metric", 0)),
            "dissect_save_rate": format_delta(
                od.get("save_rate", 0),
                nd.get("save_rate", 0),
            ),
        },
    }

    return report


def print_report(report: dict) -> None:
    print("=" * 60)
    print("  BASELINE COMPARISON REPORT")
    print("=" * 60)

    old = report["old_baseline"]
    new = report["new_baseline"]
    delta = report["delta"]

    for label in ["Condition B (No Dissect)", "Condition C (With Dissect)"]:
        key = "pass_rate_b" if "B" in label else "pass_rate_c"
        metric_key = "avg_metric_b" if "B" in label else "avg_metric_c"
        print(f"\n  {label}:")
        print(f"    Old pass rate: {format_pct(old['pass_rate'] if 'No Dissect' in label else 0)}")
        print(f"    New pass rate: {format_pct(new['pass_rate'] if 'No Dissect' in label else 0)}")
        print(f"    Delta: {delta[key]}")
        print(f"    Old avg metric: {old['avg_metric']:.4f}")
        print(f"    New avg metric: {new['avg_metric']:.4f}")
        print(f"    Metric delta: {delta[metric_key]}")

    print("\n  Dissect:")
    print(f"    Old save rate: {format_pct(report['old_baseline'].get('save_rate', 0))}")
    print(f"    New save rate: {format_pct(report['new_baseline'].get('save_rate', 0))}")
    print(f"    Save rate delta: {delta['dissect_save_rate']}")

    print("\n  Interventions:")
    print(f"    Old: {old['interventions']} -> New: {new['interventions']}")

    print("\n" + "=" * 60)


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


def main():
    parser = argparse.ArgumentParser(description="Compare two baseline files")
    parser.add_argument("--baseline", required=True, help="Path to old baseline JSON")
    parser.add_argument("--current", required=True, help="Path to new baseline JSON")
    parser.add_argument("--output", help="Path to write comparison report JSON")
    args = parser.parse_args()

    old = load_baseline(args.baseline)
    new = load_baseline(args.current)
    report = compare(old, new)

    report["metadata"] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": get_git_commit(),
        "baseline_path": args.baseline,
        "current_path": args.current,
    }

    print_report(report)

    if args.output:
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()

"""Compose the authoritative rerun baseline from the per-batch result files.

The 2026-09-15 re-run executed in two invocations (full batch then the
memory-interrupted tail). This script merges their batch JSONs into one
combined baseline_v2.json-shaped file (condition_a/b/c + problems), which
research/statistical_analysis.py consumes.

Usage:
    python research/compose_rerun_baseline.py \
        --inputs research/benchmark/results/rerun_20260915/*.json \
        --output research/benchmark/results/baseline_v2_rerun_2026-09-15.json
"""

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True, help="batch JSON files (glob ok)")
    parser.add_argument("--output", required=True)
    parser.add_argument("--problems-file", default="research/benchmark/problems.json")
    args = parser.parse_args()

    rows: list[dict] = []
    for pattern in args.inputs:
        for path in sorted(glob.glob(pattern) or [pattern]):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                rows.extend(data)
            elif "results" in data:
                rows.extend(data["results"])

    b = [r for r in rows if r.get("condition") == "B_no_dissect"]
    c = [r for r in rows if r.get("condition") == "C_with_dissect"]
    a = [r for r in rows if r.get("condition") == "A_human_baseline"]

    # Deduplicate per problem_id, keeping the FIRST (freshest) occurrence
    def dedupe(rows_in: list[dict]) -> list[dict]:
        seen: set[str] = set()
        out = []
        for r in rows_in:
            if r["problem_id"] not in seen:
                seen.add(r["problem_id"])
                out.append(r)
        return out

    b, c, a = dedupe(b), dedupe(c), dedupe(a)

    with open(args.problems_file, encoding="utf-8") as f:
        pdata = json.load(f)
    problems = pdata.get("problems", pdata if isinstance(pdata, list) else [])

    def agg(results: list[dict]) -> dict:
        passed = sum(1 for r in results if r["status"] == "pass")
        return {
            "total_problems": len(results),
            "passed": passed,
            "crashed": sum(1 for r in results if r["status"] == "crash"),
            "escalated": sum(1 for r in results if r["status"] == "escalate"),
            "timeout": sum(1 for r in results if r["status"] == "timeout"),
            "avg_metric_pass_only": round(
                sum(r["best_val_metric"] for r in results if r["status"] == "pass")
                / max(passed, 1),
                6,
            ),
            "avg_duration_seconds": round(
                sum(r["duration_seconds"] for r in results) / max(len(results), 1), 2
            ),
            "total_human_interventions": sum(r.get("human_interventions", 0) for r in results),
            "total_api_cost_usd": round(sum(r.get("api_cost_usd", 0) for r in results), 6),
            "results": results,
        }

    pass_b = sum(1 for r in b if r["status"] == "pass")
    pass_c = sum(1 for r in c if r["status"] == "pass")

    output = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "git_commit": _git(),
            "platform": __import__("platform").system(),
            "problems_file": args.problems_file,
            "execution_method": "real_orchestrator_docker",
            "note": "2026-09-15 authoritative re-run via orchestrator/job_runner after Week-1/2 fixes",
            "anthropic_model": __import__("os").getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            "training_image": __import__("os").getenv(
                "TRAINING_IMAGE_NAME", "prometheus-training-base"
            ),
            "known_limitations": [
                "TC12 (telco churn) dataset requires manual Kaggle download; excluded.",
                "Text/image timeouts enforced at job_runner level may overshoot due to "
                "Docker training not being cancelled promptly (tracked as Furnace hardening).",
            ],
        },
        "condition_b": agg(b),
        "condition_c": agg(c),
        "condition_a": agg(a) if a else {},
        "problems": problems,
        "comparison": {
            "pass_rate_b": round(pass_b / max(len(b), 1), 4),
            "pass_rate_c": round(pass_c / max(len(c), 1), 4),
            "improvement_pp": round(pass_c / max(len(c), 1) - pass_b / max(len(b), 1), 4),
        },
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(
        f"Wrote {args.output}: B n={len(b)} (pass {pass_b}), C n={len(c)} (pass {pass_c})"
        + (f", A n={len(a)}" if a else "")
    )


def _git() -> str:
    import subprocess

    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


if __name__ == "__main__":
    main()

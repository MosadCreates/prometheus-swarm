import json
import os
import glob
from datetime import datetime

RESULTS_DIR = "research/benchmark/results"
BASELINE_PATH = "research/benchmark/baseline_v1.json"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def compute_aggregates(results):
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "pass")
    crashed = sum(1 for r in results if r["status"] == "crash")
    escalated = sum(1 for r in results if r["status"] == "escalate")
    retried = sum(1 for r in results if r["status"] == "retry")

    metrics = [
        r["best_val_metric"]
        for r in results
        if r["best_val_metric"] is not None and r["status"] == "pass"
    ]
    avg_metric = sum(metrics) / len(metrics) if metrics else 0.0

    durations = [r["duration_seconds"] for r in results]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    total_interventions = sum(r.get("human_interventions", 0) for r in results)
    total_patches = sum(
        r.get("crash_count", 0) for r in results if r["condition"] == "C_with_dissect"
    )

    return {
        "total_problems": total,
        "passed": passed,
        "crashed": crashed,
        "escalated": escalated,
        "retried": retried,
        "avg_metric": round(avg_metric, 6),
        "avg_duration_seconds": round(avg_duration, 2),
        "total_human_interventions": total_interventions,
        "total_patches": total_patches if results[0]["condition"] == "C_with_dissect" else None,
    }


def compute_dissect_metrics(condition_c_results):
    attempted = sum(1 for r in condition_c_results if r.get("crash_count", 0) > 0)
    saved = sum(
        1 for r in condition_c_results if r["status"] == "pass" and r.get("crash_count", 0) > 0
    )
    failures = sum(
        1 for r in condition_c_results if r["status"] != "pass" and r.get("crash_count", 0) > 0
    )
    return {
        "problems_attempted": attempted,
        "patches_saved": saved,
        "confirmed_failures": failures,
        "save_rate": round(saved / attempted, 4) if attempted > 0 else 0.0,
    }


def main():
    # Load existing baseline
    baseline = load_json(BASELINE_PATH)

    # Load all batch files
    batch_pattern = os.path.join(RESULTS_DIR, "batch_*.json")
    batch_files = glob.glob(batch_pattern)

    all_b_results = []
    all_c_results = []

    batch_files.sort(key=lambda p: int(os.path.basename(p).split("_")[1]))
    for bf in batch_files:
        data = load_json(bf)
        for entry in data:
            if entry["condition"] == "B_no_dissect":
                all_b_results.append(entry)
            elif entry["condition"] == "C_with_dissect":
                all_c_results.append(entry)

    # Build lookup from batch results
    b_by_id = {r["problem_id"]: r for r in all_b_results}
    c_by_id = {r["problem_id"]: r for r in all_c_results}

    # Merge: batch files take priority, baseline fills gaps
    merged_b = list(b_by_id.values())
    merged_c = list(c_by_id.values())

    for r in baseline["condition_b"]["results"]:
        if r["problem_id"] not in b_by_id:
            merged_b.append(r)

    for r in baseline["condition_c"]["results"]:
        if r["problem_id"] not in c_by_id:
            merged_c.append(r)

    # Sort by problem_id for consistent ordering
    merged_b.sort(key=lambda r: r["problem_id"])
    merged_c.sort(key=lambda r: r["problem_id"])

    # Compute aggregates
    agg_b = compute_aggregates(merged_b)
    agg_c = compute_aggregates(merged_c)

    # Clean up None fields from condition B (no patches field)
    del agg_b["retried"]
    del agg_b["total_patches"]
    del agg_c["retried"]
    agg_b_clean = {k: v for k, v in agg_b.items() if v is not None}
    agg_c_clean = {k: v for k, v in agg_c.items() if v is not None}

    # Dissect metrics
    dissect = compute_dissect_metrics(merged_c)

    # Comparison
    pass_rate_b = (
        agg_b_clean["passed"] / agg_b_clean["total_problems"]
        if agg_b_clean["total_problems"] > 0
        else 0.0
    )
    pass_rate_c = (
        agg_c_clean["passed"] / agg_c_clean["total_problems"]
        if agg_c_clean["total_problems"] > 0
        else 0.0
    )

    comparison = {
        "pass_rate_b": round(pass_rate_b, 4),
        "pass_rate_c": round(pass_rate_c, 4),
        "improvement_pp": round(pass_rate_c - pass_rate_b, 4),
        "avg_metric_b": agg_b_clean["avg_metric"],
        "avg_metric_c": agg_c_clean["avg_metric"],
    }

    # Build final baseline
    output = {
        "schema_version": "1.0",
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "condition_b": {
            **agg_b_clean,
            "results": merged_b,
        },
        "condition_c": {
            **agg_c_clean,
            "results": merged_c,
        },
        "dissect_metrics": dissect,
        "comparison": comparison,
    }

    # Write
    with open(BASELINE_PATH, "w") as f:
        json.dump(output, f, indent=2)

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

"""Reproducibility checker — runs the same problems N times and measures variance.

Used before the experimental campaign to verify that results are stable.
If variance exceeds the threshold, investigation is required before proceeding.
"""

import asyncio
import json
import logging
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VARIANCE_THRESHOLD = 0.05  # 5%


async def run_reproducibility_check(
    problem_ids: list[str] | None = None,
    n_runs: int = 3,
    condition: str = "B",
) -> dict[str, Any]:
    """Run N repetitions of selected problems under the given condition.

    Args:
        problem_ids: List of problem IDs (default: TC01-TC05).
        n_runs: Number of repetitions per problem (default: 3).
        condition: Benchmark condition (A, B, C) (default: B).

    Returns:
        Report dict with per-problem variance stats and pass/fail verdict.
    """
    if problem_ids is None:
        problem_ids = ["TC01", "TC02", "TC03", "TC04", "TC05"]

    from research.run_benchmark import (
        load_problems,
        make_job_id,
        run_scout_phase,
        run_forge_phase,
        run_training_script,
        evaluate,
        resolve_dataset_path,
    )

    all_problems = load_problems()
    selected = [p for p in all_problems if p["id"] in problem_ids]

    if not selected:
        msg = f"No problems found for IDs: {problem_ids}"
        logger.error(msg)
        return {"passed": False, "error": msg}

    per_problem: dict[str, list[dict[str, Any]]] = {pid: [] for pid in problem_ids}

    for problem in selected:
        pid = problem["id"]
        logger.info(f"Reproducibility: {pid} x{n_runs}")

        for run_idx in range(n_runs):
            job_id = make_job_id(f"{pid}-repro-{run_idx}")
            t0 = time.time()

            try:
                dataset_path = resolve_dataset_path(problem)
                brief = await run_scout_phase(job_id, problem)
                if brief is None:
                    per_problem[pid].append(
                        {
                            "run": run_idx,
                            "status": "crash",
                            "error": "Scout failed",
                        }
                    )
                    continue

                script_path = await run_forge_phase(job_id, brief)
                if script_path is None:
                    per_problem[pid].append(
                        {
                            "run": run_idx,
                            "status": "crash",
                            "error": "Forge failed",
                        }
                    )
                    continue

                ok, stdout, stderr = await run_training_script(script_path, job_id, timeout=120)
                if not ok:
                    per_problem[pid].append(
                        {
                            "run": run_idx,
                            "status": "crash",
                            "duration": time.time() - t0,
                            "error": stderr[:200],
                        }
                    )
                    continue

                eval_result = await evaluate(job_id, problem)
                status = eval_result["decision"] if eval_result else "crash"
                metric = (
                    eval_result["metrics"].get(problem.get("evaluation_metric", "auc_roc"), 0.0)
                    if eval_result
                    else 0.0
                )

                per_problem[pid].append(
                    {
                        "run": run_idx,
                        "status": status,
                        "duration": time.time() - t0,
                        "metric": metric,
                    }
                )
            except Exception as e:
                per_problem[pid].append(
                    {
                        "run": run_idx,
                        "status": "crash",
                        "error": str(e),
                    }
                )

    # Compute variance
    results: list[dict[str, Any]] = []
    all_passed = True

    for pid, runs in per_problem.items():
        metrics = [r.get("metric", 0.0) for r in runs if "metric" in r]
        durations = [r["duration"] for r in runs if "duration" in r]
        statuses = [r["status"] for r in runs]

        result: dict[str, Any] = {
            "problem_id": pid,
            "n_runs": len(runs),
            "statuses": statuses,
            "all_same_status": len(set(statuses)) == 1,
        }

        if metrics:
            mean_m = statistics.mean(metrics)
            stdev_m = statistics.stdev(metrics) if len(metrics) > 1 else 0.0
            cv_m = stdev_m / mean_m if mean_m else 0.0
            result["metric_mean"] = round(mean_m, 4)
            result["metric_stdev"] = round(stdev_m, 4)
            result["metric_cv"] = round(cv_m, 4)
            result["metric_passed"] = cv_m < VARIANCE_THRESHOLD
            if not result["metric_passed"]:
                all_passed = False
        else:
            result["metric_passed"] = False
            all_passed = False

        if durations:
            mean_d = statistics.mean(durations)
            stdev_d = statistics.stdev(durations) if len(durations) > 1 else 0.0
            cv_d = stdev_d / mean_d if mean_d else 0.0
            result["duration_mean"] = round(mean_d, 2)
            result["duration_stdev"] = round(stdev_d, 2)
            result["duration_cv"] = round(cv_d, 4)
            result["duration_passed"] = cv_d < VARIANCE_THRESHOLD
            if not result["duration_passed"]:
                all_passed = False

        results.append(result)

    return {
        "schema_version": "1.0",
        "condition": condition,
        "n_runs": n_runs,
        "variance_threshold": VARIANCE_THRESHOLD,
        "passed": all_passed,
        "results": results,
    }

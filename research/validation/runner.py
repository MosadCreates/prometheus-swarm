"""Benchmark runner wrapper — executes benchmark conditions and captures results as ExperimentRun objects."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.validation.models import (
    Experiment,
    ExperimentRun,
    ExperimentSet,
    ResearchHypothesis,
    ResearchMetrics,
    SystemMetrics,
)
from research.validation.loader import runtime_run_from_dict
from research.validation.tracker import save_experiment_set

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _make_job_id(problem_id: str) -> str:
    short = uuid.uuid4().hex[:6]
    return f"eval-{problem_id.lower()}-{short}"


async def run_benchmark_batch(
    problems: list[dict],
    start: int = 0,
    conditions: str = "all",
    timeout_per_problem: int = 300,
    experiment_name: str = "Benchmark run",
) -> ExperimentSet:
    """Run a benchmark batch and return an ExperimentSet with all results.

    This wraps the existing benchmark functions from run_benchmark.py
    with result tracking into the Research Validation Framework.

    Args:
        problems: List of problem definitions from problems.json
        start: Index offset for display
        conditions: "A", "B", "C", "both", or "all"
        timeout_per_problem: Timeout per training script run (seconds)
        experiment_name: Name for the ExperimentSet

    Returns:
        Populated ExperimentSet with ExperimentRun objects.
    """
    from research.run_benchmark import (
        ensure_dataset_available,
        make_job_id as bench_make_job_id,
        print_problem_header,
        print_result,
        resolve_dataset_path,
        run_condition_a,
        run_condition_b,
        run_condition_c,
        run_forge_phase,
        run_scout_phase,
    )

    exp_set = ExperimentSet(name=experiment_name)

    # Determine which conditions to run
    if conditions == "all":
        conds = {"A": ResearchHypothesis.H1, "B": ResearchHypothesis.H2, "C": ResearchHypothesis.H3}
    elif conditions == "A":
        conds = {"A": ResearchHypothesis.H1}
    elif conditions == "B":
        conds = {"B": ResearchHypothesis.H2}
    elif conditions == "C":
        conds = {"C": ResearchHypothesis.H3}
    elif conditions == "both":
        conds = {"B": ResearchHypothesis.H2, "C": ResearchHypothesis.H3}
    else:
        conds = {}

    # Initialise experiments
    for cond_label, hypothesis in conds.items():
        exp = Experiment(
            name=f"{experiment_name} - {cond_label} ({hypothesis.value})",
            hypothesis=hypothesis,
        )
        exp_set.experiments[hypothesis.value] = exp

    batch = problems[start:]
    total = len(batch)
    logger.info(f"Benchmark run: {total} problems, conditions: {conditions}")

    for i, problem in enumerate(batch):
        pid = problem["id"]
        job_id = bench_make_job_id(pid)

        print_problem_header(problem, i, total)

        # Ensure dataset is available
        dataset_ok = await _ensure_dataset(problem)
        if not dataset_ok:
            _add_skip_result(exp_set, problem, job_id, conds.values())
            continue

        # Run Scout + Forge (shared across conditions)
        brief = await run_scout_phase(job_id, problem)
        if brief is None:
            _add_fail_result(exp_set, problem, job_id, conds.values(), "Scout failed")
            continue

        script_path = await run_forge_phase(job_id, brief)
        if script_path is None:
            _add_fail_result(exp_set, problem, job_id, conds.values(), "Forge failed")
            continue

        # Determine timeout
        n_rows = problem.get("num_rows_expected", 1000)
        if problem.get("modality") in ("image", "text"):
            timeout = 600
        elif n_rows > 50000:
            timeout = 600
        elif n_rows > 10000:
            timeout = 300
        else:
            timeout = 120

        # Run each condition
        for cond_label, hypothesis in conds.items():
            t0 = time.time()
            try:
                if cond_label == "A":
                    raw_result = await run_condition_a(problem, job_id, timeout)
                elif cond_label == "B":
                    raw_result = await run_condition_b(problem, script_path, job_id, timeout)
                elif cond_label == "C":
                    raw_result = await run_condition_c(problem, script_path, job_id, timeout)
                else:
                    continue

                run = _raw_to_run(problem, job_id, hypothesis, raw_result, t0)
                exp_set.experiments[hypothesis.value].runs.append(run)
                print_result(raw_result)

            except Exception as exc:
                logger.error(f"[{job_id}] Condition {cond_label} failed: {exc}")
                run = _make_failed_run(problem, job_id, hypothesis, str(exc), t0)
                exp_set.experiments[hypothesis.value].runs.append(run)

        # Cleanup
        _cleanup(script_path, job_id)

    # Save results
    save_experiment_set(exp_set)
    logger.info(
        "Benchmark complete: "
        + ", ".join(f"{h}={len(e.runs)} runs" for h, e in exp_set.experiments.items())
    )
    return exp_set


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


async def _ensure_dataset(problem: dict) -> bool:
    try:
        local_path = await ensure_dataset_available(problem)
        return local_path is not None and Path(local_path).exists()
    except Exception:
        return False


def _raw_to_run(
    problem: dict,
    job_id: str,
    hypothesis: ResearchHypothesis,
    raw_result: dict,
    t0: float,
) -> ExperimentRun:
    duration = time.time() - t0
    status = raw_result.get("status", "unknown")
    decision = raw_result.get("decision", "")
    deployment_success = decision == "pass"

    run = ExperimentRun(
        job_id=job_id,
        problem_id=problem["id"],
        hypothesis=hypothesis,
        system_metrics=SystemMetrics(
            duration_seconds=raw_result.get("duration_seconds", duration),
            crashes=raw_result.get("crash_count", 0),
            crashes_recovered=(
                raw_result.get("patch_successes", 0) if hypothesis == ResearchHypothesis.H3 else 0
            ),
            wall_clock_time_s=duration,
        ),
        research_metrics=ResearchMetrics(
            deployment_success=deployment_success,
            actual_success=deployment_success,
            final_metric=raw_result.get("best_val_metric"),
            patch_success_rate=(
                raw_result.get("patch_successes", 0) / max(raw_result.get("crash_count", 1), 1)
                if raw_result.get("crash_count", 0) > 0 and hypothesis == ResearchHypothesis.H3
                else None
            ),
        ),
        execution_outcome={
            "status": status,
            "decision": decision,
            "architecture": raw_result.get("architecture", ""),
            "error": raw_result.get("error"),
        },
    )
    return run


def _make_failed_run(
    problem: dict,
    job_id: str,
    hypothesis: ResearchHypothesis,
    error: str,
    t0: float,
) -> ExperimentRun:
    return ExperimentRun(
        job_id=job_id,
        problem_id=problem["id"],
        hypothesis=hypothesis,
        system_metrics=SystemMetrics(wall_clock_time_s=time.time() - t0),
        execution_outcome={"status": "failed", "error": error},
    )


def _add_skip_result(
    exp_set: ExperimentSet,
    problem: dict,
    job_id: str,
    hypotheses: list[ResearchHypothesis],
) -> None:
    for h in hypotheses:
        run = ExperimentRun(
            job_id=job_id,
            problem_id=problem["id"],
            hypothesis=h,
            execution_outcome={"status": "skipped", "error": "Dataset unavailable"},
        )
        exp_set.experiments[h.value].runs.append(run)


def _add_fail_result(
    exp_set: ExperimentSet,
    problem: dict,
    job_id: str,
    hypotheses: list[ResearchHypothesis],
    error: str,
) -> None:
    for h in hypotheses:
        run = ExperimentRun(
            job_id=job_id,
            problem_id=problem["id"],
            hypothesis=h,
            execution_outcome={"status": "failed", "error": error},
        )
        exp_set.experiments[h.value].runs.append(run)


def _cleanup(script_path: str, job_id: str) -> None:
    import shutil

    try:
        Path(script_path).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        ckpt_dir = Path(f"outputs/{job_id}")
        if ckpt_dir.exists():
            shutil.rmtree(str(ckpt_dir))
    except Exception:
        pass

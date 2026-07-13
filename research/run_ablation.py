"""
Ablation campaign runner — runs all 7 configurations across 50 benchmark problems.

Usage:
    python research/run_ablation.py --start 0 --count 5
    python research/run_ablation.py --start 0 --count 50 --output research/reports/ablation_results.json

Each config sets DISABLE_PLANNER, DISABLE_PATCH_MEMORY, DISABLE_DISSECT environment
variables (read by evaluation/config.py) to produce a different ablation slice:
  Config 1: OFF/OFF/OFF  — raw pipeline (no intelligence)
  Config 2: ON/OFF/OFF   — Planner only
  Config 3: OFF/ON/OFF   — Patch memory only
  Config 4: OFF/OFF/ON   — Dissect only (no planner, no memory)
  Config 5: ON/ON/OFF    — Planner + memory, no runtime repair
  Config 6: ON/OFF/ON    — Planner + Dissect, no memory
  Config 7: ON/ON/ON     — Full system
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("ablation")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATH = PROJECT_ROOT / "research" / "benchmark" / "problems.json"

ABLATION_CONFIGS = [
    {
        "id": 1,
        "label": "OFF/OFF/OFF",
        "planner": "1",
        "patch_memory": "1",
        "dissect": "1",
        "uses_dissect": False,
    },
    {
        "id": 2,
        "label": "ON/OFF/OFF",
        "planner": "0",
        "patch_memory": "1",
        "dissect": "1",
        "uses_dissect": False,
    },
    {
        "id": 3,
        "label": "OFF/ON/OFF",
        "planner": "1",
        "patch_memory": "0",
        "dissect": "1",
        "uses_dissect": False,
    },
    {
        "id": 4,
        "label": "OFF/OFF/ON",
        "planner": "1",
        "patch_memory": "1",
        "dissect": "0",
        "uses_dissect": True,
    },
    {
        "id": 5,
        "label": "ON/ON/OFF",
        "planner": "0",
        "patch_memory": "0",
        "dissect": "1",
        "uses_dissect": False,
    },
    {
        "id": 6,
        "label": "ON/OFF/ON",
        "planner": "0",
        "patch_memory": "1",
        "dissect": "0",
        "uses_dissect": True,
    },
    {
        "id": 7,
        "label": "ON/ON/ON",
        "planner": "0",
        "patch_memory": "0",
        "dissect": "0",
        "uses_dissect": True,
    },
]


def load_problems() -> list[dict]:
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def set_ablation_env(config: dict) -> dict:
    old = {
        "DISABLE_PLANNER": os.environ.get("DISABLE_PLANNER", ""),
        "DISABLE_PATCH_MEMORY": os.environ.get("DISABLE_PATCH_MEMORY", ""),
        "DISABLE_DISSECT": os.environ.get("DISABLE_DISSECT", ""),
    }
    os.environ["DISABLE_PLANNER"] = config["planner"]
    os.environ["DISABLE_PATCH_MEMORY"] = config["patch_memory"]
    os.environ["DISABLE_DISSECT"] = config["dissect"]
    return old


def restore_env(old: dict) -> None:
    for k, v in old.items():
        if v:
            os.environ[k] = v
        else:
            os.environ.pop(k, None)


def make_result(
    problem: dict,
    config_id: int,
    config_label: str,
    status: str,
    job_id: str = "",
    duration: float = 0.0,
    metrics: dict | None = None,
    error: str | None = None,
    decision: str = "",
    crash_count: int = 0,
    patch_successes: int = 0,
    uses_dissect: bool = False,
    llm_calls_used: int = 0,
    llm_cost: float = 0.0,
    cascade_level_used: int = -1,
) -> dict:
    metric_name = problem.get("evaluation_metric", "auc_roc")
    best_val = 0.0
    if metrics:
        best_val = metrics.get(metric_name, metrics.get("auc_roc", metrics.get("rmse", 0.0)))
    return {
        "config_id": config_id,
        "config_label": config_label,
        "problem_id": problem["id"],
        "job_id": job_id,
        "status": status,
        "decision": decision,
        "best_val_metric": best_val,
        "duration_seconds": round(duration, 2),
        "crash_count": crash_count,
        "patch_successes": patch_successes,
        "architecture": problem.get("expected_architecture", "unknown"),
        "error": error[:500] if error else None,
        "modality": problem.get("modality", ""),
        "task_type": problem.get("task_type", ""),
        "uses_dissect": uses_dissect,
        "llm_calls_used": llm_calls_used,
        "llm_cost": round(llm_cost, 6),
        "cascade_level_used": cascade_level_used,
    }


async def run_single_problem(
    problem: dict,
    config: dict,
    job_id: str,
    timeout: int,
) -> dict:
    """Run one problem under one ablation config."""
    from research.run_benchmark import (
        ensure_dataset_available,
        evaluate,
        run_training_script,
        run_scout_phase,
        run_forge_phase,
    )

    t0 = time.time()

    # Ensure dataset
    try:
        local_path = await ensure_dataset_available(problem)
        if local_path is None or not Path(local_path).exists():
            return make_result(
                problem,
                config["id"],
                config["label"],
                "skipped",
                job_id,
                error="Dataset unavailable",
            )
    except Exception as e:
        return make_result(
            problem, config["id"], config["label"], "skipped", job_id, error=f"Dataset error: {e}"
        )

    # Scout phase
    try:
        brief = await run_scout_phase(job_id, problem)
        if brief is None:
            return make_result(
                problem, config["id"], config["label"], "failed", job_id, error="Scout failed"
            )
    except Exception as e:
        return make_result(
            problem, config["id"], config["label"], "failed", job_id, error=f"Scout exception: {e}"
        )

    # Forge phase
    try:
        script_path = await run_forge_phase(job_id, brief)
        if script_path is None:
            return make_result(
                problem, config["id"], config["label"], "failed", job_id, error="Forge failed"
            )
    except Exception as e:
        return make_result(
            problem, config["id"], config["label"], "failed", job_id, error=f"Forge exception: {e}"
        )

    # Determine timeout
    n_rows = problem.get("num_rows_expected", 1000)
    if problem.get("modality") in ("image", "text"):
        effective_timeout = max(timeout, 600)
    elif n_rows > 50000:
        effective_timeout = max(timeout, 600)
    elif n_rows > 10000:
        effective_timeout = max(timeout, 300)
    else:
        effective_timeout = max(timeout, 120)

    total_crash_count = 0
    total_patch_successes = 0
    last_error = None

    if config["uses_dissect"]:
        # Condition C flow: training with Dissect recovery loop (up to 3 attempts)
        from agents.dissect.agent import DissectAgent
        from memory.redis_client import RedisClient

        for attempt in range(1, 4):
            ok, stdout, stderr = await run_training_script(
                script_path, job_id, timeout=effective_timeout
            )
            if ok:
                llm_calls = 0
                llm_cost = 0.0
                eval_result = await evaluate(job_id, problem)
                if eval_result is None:
                    return make_result(
                        problem,
                        config["id"],
                        config["label"],
                        "crash",
                        job_id,
                        duration=time.time() - t0,
                        error="No predictions found",
                        crash_count=total_crash_count,
                        patch_successes=total_patch_successes,
                        uses_dissect=True,
                        llm_calls_used=llm_calls,
                        llm_cost=llm_cost,
                    )
                return make_result(
                    problem,
                    config["id"],
                    config["label"],
                    eval_result["decision"],
                    job_id,
                    duration=time.time() - t0,
                    metrics=eval_result["metrics"],
                    decision=eval_result["decision"],
                    crash_count=total_crash_count,
                    patch_successes=total_patch_successes,
                    uses_dissect=True,
                    llm_calls_used=llm_calls,
                    llm_cost=llm_cost,
                )

            logger.info(
                f"[{job_id}] Config {config['id']} crash attempt {attempt}: activating Dissect"
            )
            from research.run_benchmark import _parse_exception

            exc_type, exc_msg = _parse_exception(stderr)
            last_error = f"{exc_type}: {exc_msg}"
            total_crash_count += 1

            dissect = DissectAgent(job_id=job_id)
            dissect.redis = RedisClient()
            await dissect.redis.connect()

            crash_event = {
                "job_id": job_id,
                "exception_type": exc_type,
                "exception_message": exc_msg[:500],
                "traceback": stderr,
                "script_path": script_path,
                "last_checkpoint_path": "",
                "epoch_at_crash": 0,
                "crash_attempt_number": attempt,
            }

            try:
                await dissect.handle_crash(crash_event)
                from research.run_benchmark import drain_patch_log_queue

                await drain_patch_log_queue(dissect.redis)
            except Exception as e:
                logger.error(f"[{job_id}] Dissect handle_crash raised: {e}")
                llm_calls = dissect._budget.llm_calls_used if dissect._budget else 0
                llm_cost = dissect._budget.total_cost if dissect._budget else 0.0
                await dissect.redis.close()
                return make_result(
                    problem,
                    config["id"],
                    config["label"],
                    "escalate",
                    job_id,
                    duration=time.time() - t0,
                    error=f"Dissect exception: {e}",
                    crash_count=total_crash_count,
                    patch_successes=total_patch_successes,
                    uses_dissect=True,
                    llm_calls_used=llm_calls,
                    llm_cost=llm_cost,
                )
            finally:
                try:
                    await dissect.redis.close()
                except Exception:
                    pass

            llm_calls = dissect._budget.llm_calls_used if dissect._budget else 0
            llm_cost = dissect._budget.total_cost if dissect._budget else 0.0

            bak_path = script_path + ".bak"
            if os.path.exists(bak_path):
                total_patch_successes += 1
                try:
                    os.remove(bak_path)
                except Exception:
                    pass
                continue
            else:
                return make_result(
                    problem,
                    config["id"],
                    config["label"],
                    "escalate",
                    job_id,
                    duration=time.time() - t0,
                    error=last_error,
                    crash_count=total_crash_count,
                    patch_successes=total_patch_successes,
                    uses_dissect=True,
                    llm_calls_used=llm_calls,
                    llm_cost=llm_cost,
                )

        llm_calls = dissect._budget.llm_calls_used if dissect._budget else 0
        llm_cost = dissect._budget.total_cost if dissect._budget else 0.0
        return make_result(
            problem,
            config["id"],
            config["label"],
            "escalate",
            job_id,
            duration=time.time() - t0,
            error=last_error,
            crash_count=total_crash_count,
            patch_successes=total_patch_successes,
            uses_dissect=True,
            llm_calls_used=llm_calls,
            llm_cost=llm_cost,
        )
    else:
        # Condition B flow: single training run, no crash recovery
        ok, stdout, stderr = await run_training_script(
            script_path, job_id, timeout=effective_timeout
        )
        if not ok:
            from research.run_benchmark import _parse_exception

            exc_type, exc_msg = _parse_exception(stderr)
            return make_result(
                problem,
                config["id"],
                config["label"],
                "crash",
                job_id,
                duration=time.time() - t0,
                error=f"{exc_type}: {exc_msg}",
                crash_count=1,
            )

        eval_result = await evaluate(job_id, problem)
        if eval_result is None:
            return make_result(
                problem,
                config["id"],
                config["label"],
                "crash",
                job_id,
                duration=time.time() - t0,
                error="No predictions found",
            )

        return make_result(
            problem,
            config["id"],
            config["label"],
            eval_result["decision"],
            job_id,
            duration=time.time() - t0,
            metrics=eval_result["metrics"],
            decision=eval_result["decision"],
        )


async def run_ablation(
    problems: list[dict],
    start: int = 0,
    count: int = 5,
    timeout: int = 300,
) -> dict:
    """Run all 7 ablation configs on a batch of problems."""
    batch = problems[start : start + count]
    total = len(batch)

    results = {
        "configs": [c["id"] for c in ABLATION_CONFIGS],
        "config_labels": {c["id"]: c["label"] for c in ABLATION_CONFIGS},
        "config_env": {
            c["id"]: {
                "planner": c["planner"],
                "patch_memory": c["patch_memory"],
                "dissect": c["dissect"],
            }
            for c in ABLATION_CONFIGS
        },
        "problems": [p["id"] for p in batch],
        "runs": [],
        "start_index": start,
        "count": count,
        "total_problems": len(batch),
        "timestamp": time.time(),
    }

    for i, problem in enumerate(batch):
        pid = problem["id"]
        job_id = f"abl-{pid.lower()}-{uuid.uuid4().hex[:6]}"
        logger.info(f"[{i+1}/{total}] Problem {pid} — running 7 configs")

        for config in ABLATION_CONFIGS:
            logger.info(f"  Config {config['id']} ({config['label']})")
            old_env = set_ablation_env(config)

            try:
                result = await run_single_problem(problem, config, job_id, timeout)
                results["runs"].append(result)
                status_icon = "✓" if result["status"] in ("pass", "retry") else "✗"
                logger.info(
                    f"    {status_icon} {result['status']} ({result['duration_seconds']:.1f}s)"
                )
            except Exception as e:
                logger.error(f"    ✗ Exception: {e}")
                results["runs"].append(
                    make_result(
                        problem, config["id"], config["label"], "error", job_id, error=str(e)
                    )
                )
            finally:
                restore_env(old_env)

    # Compute summaries per config
    summaries = {}
    for cid in [c["id"] for c in ABLATION_CONFIGS]:
        config_runs = [r for r in results["runs"] if r["config_id"] == cid]
        total_runs = len(config_runs)
        successes = sum(1 for r in config_runs if r["status"] in ("pass", "retry"))
        crashes = sum(1 for r in config_runs if r["status"] == "crash")
        escalations = sum(1 for r in config_runs if r["status"] in ("escalate", "error"))
        skipped = sum(1 for r in config_runs if r["status"] == "skipped")
        avg_duration = sum(r["duration_seconds"] for r in config_runs) / max(total_runs, 1)
        summaries[str(cid)] = {
            "config_label": results["config_labels"][cid],
            "total": total_runs,
            "successes": successes,
            "crashes": crashes,
            "escalations": escalations,
            "skipped": skipped,
            "success_rate": round(successes / max(total_runs, 1) * 100, 1),
            "avg_duration_seconds": round(avg_duration, 1),
        }

    results["summaries"] = summaries

    # Convergence tracking for Milestone 8
    results["convergence"] = {
        "total_llm_calls": sum(r.get("llm_calls_used", 0) for r in results["runs"]),
        "total_token_cost": sum(r.get("llm_cost", 0.0) for r in results["runs"]),
        "cascade_level_counts": {},
        "dissect_problems": 0,
        "dissect_successes": 0,
    }
    for r in results["runs"]:
        cl = r.get("cascade_level_used", -1)
        if cl >= 0:
            key = str(cl)
            results["convergence"]["cascade_level_counts"][key] = (
                results["convergence"]["cascade_level_counts"].get(key, 0) + 1
            )
    dissect_runs = [r for r in results["runs"] if r.get("uses_dissect", False)]
    results["convergence"]["dissect_problems"] = len(dissect_runs)
    results["convergence"]["dissect_successes"] = sum(
        1 for r in dissect_runs if r["status"] in ("pass", "retry")
    )

    return results


def main():
    parser = argparse.ArgumentParser(description="Run ablation campaign")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=300, help="Timeout per training script (s)")
    parser.add_argument(
        "--output", default=str(PROJECT_ROOT / "research" / "reports" / "ablation_results.json")
    )
    args = parser.parse_args()

    problems = load_problems()
    logger.info(
        f"Loaded {len(problems)} problems, running configs {[c['id'] for c in ABLATION_CONFIGS]}"
    )

    results = asyncio.run(
        run_ablation(problems, start=args.start, count=args.count, timeout=args.timeout)
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print("  Ablation Campaign Complete")
    print(
        f"  Problems: {args.start}..{args.start+args.count-1} ({len(results['runs'])} total runs)"
    )
    print(f"  Configs: {len(results['configs'])}")
    print(f"  Output: {out_path}")
    print(f"{'='*60}")
    print(
        f"\n{'Config':<12} {'Success':>8} {'Crash':>8} {'Esc':>8} {'Skip':>8} {'Rate':>8} {'Avg(s)':>8}"
    )
    print(f"{'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8}")
    for cid, s in sorted(results["summaries"].items(), key=lambda x: int(x[0])):
        print(
            f"  {s['config_label']:<10} {s['successes']:>8} {s['crashes']:>8} {s['escalations']:>8} {s['skipped']:>8} {s['success_rate']:>7}% {s['avg_duration_seconds']:>7.1f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())

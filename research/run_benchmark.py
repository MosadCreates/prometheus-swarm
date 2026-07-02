"""
Benchmark runner — runs problems.json through Conditions B and C.

Usage:
    python research/run_benchmark.py --start 0 --count 3 --condition B
    python research/run_benchmark.py --start 0 --count 10 --condition both
    python research/run_benchmark.py --start 20 --count 10 --condition C --output my_results.json
"""

import argparse
import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import numpy as np

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("benchmark")

RESULTS_DIR = Path("research/benchmark/results")
SCRIPTS_DIR = Path("scripts")
BENCHMARK_PATH = Path("research/benchmark/problems.json")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_problems():
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def resolve_dataset_path(problem: dict) -> str:
    raw = problem["dataset"]["path"]
    p = Path(raw)
    if p.is_absolute():
        return str(p.resolve())
    return str((PROJECT_ROOT / raw).resolve())


def ensure_csv(dataset_path: str) -> str:
    p = Path(dataset_path)
    if p.suffix.lower() in {".csv", ".data", ".txt"}:
        return dataset_path
    if p.suffix.lower() == ".xls":
        # Some XLS files have row 0 as an empty merged cell; detect and skip it
        df = pd.read_excel(dataset_path, header=0)
        if "Unnamed: 0" in df.columns or df.columns[0] in ("", None, 0, "0", "X1"):
            df = pd.read_excel(dataset_path, header=1)
        csv_path = p.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        logger.info(f"Converted {p.name} -> {csv_path.name}")
        return str(csv_path)
    return dataset_path


def make_job_id(problem_id: str) -> str:
    short = uuid.uuid4().hex[:6]
    return f"bench-{problem_id.lower()}-{short}"


def make_result(
    problem: dict,
    condition: str,
    status: str,
    job_id: str = "",
    duration: float = 0.0,
    metrics: dict | None = None,
    error: str | None = None,
    decision: str = "",
    patches: int = 0,
) -> dict:
    return {
        "problem_id": problem["id"],
        "condition": condition,
        "status": status,
        "job_id": job_id,
        "best_val_metric": _best_metric(metrics, problem),
        "decision": decision,
        "duration_seconds": round(duration, 2),
        "crash_count": patches,
        "human_interventions": 0 if status == "pass" else 1,
        "architecture": problem.get("expected_architecture", "unknown"),
        "error": error[:500] if error else None,
    }


def _best_metric(metrics: dict | None, problem: dict) -> float:
    if not metrics:
        return 0.0
    metric_name = problem.get("evaluation_metric", "auc_roc")
    return metrics.get(metric_name, metrics.get("auc_roc", metrics.get("rmse", 0.0)))


def _parse_exception(stderr: str) -> tuple[str, str]:
    lines = stderr.strip().split("\n")
    exc_type = "RuntimeError"
    exc_msg = stderr[:200]
    for line in lines:
        if "Error:" in line or "Exception:" in line:
            exc_msg = line.strip()
            parts = line.split(":", 1)
            if len(parts) >= 2:
                exc_type = parts[0].strip()
                exc_msg = ":".join(parts[1:]).strip()
            break
    return exc_type, exc_msg


async def _run_subprocess(
    cmd: list[str], timeout: int, env: dict | None = None
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return (
            proc.returncode or 0,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", f"TIMEOUT after {timeout}s"


async def run_training_script(
    script_path: str, job_id: str, timeout: int = 300
) -> tuple[bool, str, str]:
    env = os.environ.copy()
    env["JOB_ID"] = job_id
    env["PYTHONUNBUFFERED"] = "1"
    rc, stdout, stderr = await _run_subprocess(
        [sys.executable, str(script_path)],
        timeout=timeout,
        env=env,
    )
    if rc != 0:
        return False, stdout, stderr
    return True, stdout, stderr


async def run_arbiter_eval(job_id: str, task_type: str) -> dict | None:
    from agents.arbiter.tools import (
        compute_classification_metrics,
        compute_regression_metrics,
        make_decision,
    )

    ckpt_dir = Path(f"outputs/{job_id}/checkpoints")

    if not (ckpt_dir / "y_test.npy").exists():
        logger.warning(f"[{job_id}] No y_test.npy found at {ckpt_dir}")
        return None

    from sklearn.preprocessing import LabelEncoder

    y_true_raw = np.load(str(ckpt_dir / "y_test.npy"), allow_pickle=True)
    y_pred_raw = np.load(str(ckpt_dir / "y_pred.npy"), allow_pickle=True)

    if task_type == "classification":
        le = None
        y_true_flat = y_true_raw.ravel()
        y_pred_flat = y_pred_raw.ravel()
        if y_true_raw.dtype.kind in ("i", "u", "f") and y_pred_raw.dtype.kind in (
            "i",
            "u",
            "f",
        ):
            y_true_enc = y_true_flat
            y_pred_enc = y_pred_flat
        else:
            le = LabelEncoder()
            y_true_enc = le.fit_transform(y_true_flat.astype(str))
            try:
                y_pred_enc = le.transform(y_pred_flat.astype(str))
            except ValueError:
                logger.warning(
                    f"[{job_id}] y_pred contains labels unseen during fit; "
                    f"fitting combined encoder"
                )
                from sklearn.preprocessing import LabelEncoder as LE2

                le2 = LE2()
                all_labels = sorted(
                    set(str(v) for v in y_true_flat) | set(str(v) for v in y_pred_flat)
                )
                le2.fit(all_labels)
                y_true_enc = le2.transform(y_true_flat.astype(str))
                y_pred_enc = le2.transform(y_pred_flat.astype(str))
        prob_path = ckpt_dir / "y_prob.npy"
        y_prob = np.load(str(prob_path), allow_pickle=True) if prob_path.exists() else None
        n_classes = len(np.unique(y_true_enc))
        if y_prob is not None and y_prob.ndim > 1 and y_prob.shape[1] > 2 and n_classes == 2:
            y_prob = y_prob[:, 1]
        metrics = compute_classification_metrics(
            y_true_enc.tolist(),
            y_pred_enc.tolist(),
            y_prob.tolist() if y_prob is not None else None,
        )
    else:
        metrics = compute_regression_metrics(
            y_true_raw.ravel().tolist(), y_pred_raw.ravel().tolist()
        )

    decision, reason = make_decision(task_type, metrics, crash_count=0)
    return {
        "metrics": metrics,
        "decision": decision,
        "reason": reason,
        "task_type": task_type,
    }


PATCH_LOG_PATH = Path("research/patch_log.jsonl")


async def drain_patch_log_queue(redis_client) -> int:
    """Pop all entries from patch_log_queue and append to patch_log.jsonl.
    Returns the number of entries flushed.
    """
    count = 0
    while True:
        raw = await redis_client.blpop("patch_log_queue", timeout=1)
        if raw is None:
            break
        try:
            entry = json.loads(raw)
            with open(PATCH_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            count += 1
        except Exception:
            pass
    if count:
        logger.info(f"Flushed {count} patch log entries to {PATCH_LOG_PATH}")
    return count


def save_results_batch(condition: str, results: list[dict], batch_idx: int):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"batch_{batch_idx}_condition_{condition}.json"
    path = RESULTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Saved {len(results)} results -> {path}")


def print_problem_header(problem: dict, idx: int, total: int):
    print()
    print(f"{'='*60}")
    print(f"  [{idx+1}/{total}] {problem['id']}: {problem['problem_description'][:70]}")
    print(
        f"  Dataset: {problem['dataset']['name']} | "
        f"{problem['task_type']} | {problem['modality']} | "
        f"{problem['difficulty']}"
    )
    print(f"{'='*60}")


def print_result(result: dict):
    status_color = (
        "PASS"
        if result["status"] == "pass"
        else "CRASH" if result["status"] == "crash" else "ESCALATE"
    )
    metric = result["best_val_metric"]
    print(
        f"  >> {status_color} | metric={metric:.4f} | "
        f"duration={result['duration_seconds']:.1f}s | "
        f"patches={result['crash_count']} | "
        f"error={result['error'][:60] if result['error'] else 'None'}"
    )


def print_batch_summary(results_b: list[dict], results_c: list[dict]):
    print()
    print(f"{'='*60}")
    print("  BATCH SUMMARY")
    print(f"{'='*60}")

    for label, results in [
        ("B (No Dissect)", results_b),
        ("C (With Dissect)", results_c),
    ]:
        passed = sum(1 for r in results if r["status"] == "pass")
        crashed = sum(1 for r in results if r["status"] == "crash")
        escalated = sum(1 for r in results if r["status"] == "escalate")
        total = len(results)
        avg_metric = sum(r["best_val_metric"] for r in results) / max(total, 1)
        avg_time = sum(r["duration_seconds"] for r in results) / max(total, 1)
        interventions = sum(r["human_interventions"] for r in results)
        print(f"\n  Condition {label}:")
        print(f"    Passed:    {passed}/{total}")
        print(f"    Crashed:   {crashed}/{total}")
        print(f"    Escalated: {escalated}/{total}")
        print(f"    Avg metric: {avg_metric:.4f}")
        print(f"    Avg time:   {avg_time:.1f}s")
        print(f"    Interventions: {interventions}")

    print(f"{'='*60}\n")


async def run_scout_phase(job_id: str, problem: dict) -> dict | None:
    from agents.scout.agent import ScoutAgent

    scout = ScoutAgent(job_id=job_id)
    await scout.redis.connect()
    try:
        dataset_path = resolve_dataset_path(problem)
        dataset_path = ensure_csv(dataset_path)
        brief = await scout.run_with_data(
            problem_description=problem["problem_description"],
            file_path=dataset_path,
            target_column=problem["target_column"],
            modality_override=problem.get("modality"),
        )
        logger.info(
            f"[{job_id}] Scout done | task={brief['task_type']} modality={brief['modality']}"
        )
        return brief
    except Exception as e:
        logger.error(f"[{job_id}] Scout failed: {e}")
        return None
    finally:
        await scout.redis.close()


async def run_forge_phase(job_id: str, brief: dict) -> str | None:
    from agents.forge.agent import ForgeAgent

    forge = ForgeAgent(job_id=job_id)
    await forge.redis.connect()
    try:
        script_path = await forge.run_with_brief(brief)
        abs_path = PROJECT_ROOT / script_path
        if not abs_path.exists():
            logger.error(f"[{job_id}] Script not found: {abs_path}")
            return None
        logger.info(f"[{job_id}] Forge done | script={script_path}")
        return str(abs_path)
    except Exception as e:
        logger.error(f"[{job_id}] Forge failed: {e}")
        return None
    finally:
        await forge.redis.close()


async def evaluate(job_id: str, problem: dict) -> dict | None:
    task = problem["task_type"]
    result = await run_arbiter_eval(job_id, task)
    if result is None:
        ckpt_dir = Path(f"outputs/{job_id}/checkpoints")
        if ckpt_dir.exists():
            shutil.rmtree(str(ckpt_dir.parent))
        return None
    return result


async def run_condition_a(
    problem: dict,
    job_id: str,
    timeout: int,
) -> dict:
    """Condition A: Human-written baseline training.

    Simulates a human providing a well-tuned training script by using
    the generated script directly and evaluating the result.
    """
    t0 = time.time()

    from agents.scout.agent import ScoutAgent
    from agents.forge.agent import ForgeAgent

    scout = ScoutAgent(job_id=job_id)
    await scout.redis.connect()
    try:
        dataset_path = resolve_dataset_path(problem)
        dataset_path = ensure_csv(dataset_path)
        brief = await scout.run_with_data(
            problem_description=problem["problem_description"],
            file_path=dataset_path,
            target_column=problem["target_column"],
            modality_override=problem.get("modality"),
        )
    except Exception as e:
        await scout.redis.close()
        return make_result(
            problem,
            "A_human_baseline",
            "crash",
            job_id,
            duration=time.time() - t0,
            error=f"Scout failed: {e}",
        )

    forge = ForgeAgent(job_id=job_id)
    await forge.redis.connect()
    try:
        script_path = await forge.run_with_brief(brief)
        abs_path = PROJECT_ROOT / script_path
        if not abs_path.exists():
            return make_result(
                problem,
                "A_human_baseline",
                "crash",
                job_id,
                duration=time.time() - t0,
                error="Script not found",
            )
    except Exception as e:
        await forge.redis.close()
        await scout.redis.close()
        return make_result(
            problem,
            "A_human_baseline",
            "crash",
            job_id,
            duration=time.time() - t0,
            error=f"Forge failed: {e}",
        )
    finally:
        await forge.redis.close()
        await scout.redis.close()

    ok, stdout, stderr = await run_training_script(str(abs_path), job_id, timeout=timeout)
    if not ok:
        exc_type, exc_msg = _parse_exception(stderr)
        return make_result(
            problem,
            "A_human_baseline",
            "crash",
            job_id,
            duration=time.time() - t0,
            error=f"{exc_type}: {exc_msg}",
        )

    eval_result = await evaluate(job_id, problem)
    if eval_result is None:
        return make_result(
            problem,
            "A_human_baseline",
            "crash",
            job_id,
            duration=time.time() - t0,
            error="No predictions found",
        )

    return make_result(
        problem,
        "A_human_baseline",
        eval_result["decision"],
        job_id,
        duration=time.time() - t0,
        metrics=eval_result["metrics"],
        decision=eval_result["decision"],
    )


async def run_condition_b(
    problem: dict,
    script_path: str,
    job_id: str,
    timeout: int,
) -> dict:
    t0 = time.time()
    ok, stdout, stderr = await run_training_script(script_path, job_id, timeout=timeout)
    if not ok:
        exc_type, exc_msg = _parse_exception(stderr)
        return make_result(
            problem,
            "B_no_dissect",
            "crash",
            job_id,
            duration=time.time() - t0,
            error=f"{exc_type}: {exc_msg}",
        )

    eval_result = await evaluate(job_id, problem)
    if eval_result is None:
        return make_result(
            problem,
            "B_no_dissect",
            "crash",
            job_id,
            duration=time.time() - t0,
            error="No predictions found",
        )

    return make_result(
        problem,
        "B_no_dissect",
        eval_result["decision"],
        job_id,
        duration=time.time() - t0,
        metrics=eval_result["metrics"],
        decision=eval_result["decision"],
    )


async def run_condition_c(
    problem: dict,
    script_path: str,
    job_id: str,
    timeout: int,
) -> dict:
    from agents.dissect.agent import DissectAgent
    from memory.redis_client import RedisClient

    t0 = time.time()
    total_patches = 0
    last_error = None

    for attempt in range(1, 4):
        ok, stdout, stderr = await run_training_script(script_path, job_id, timeout=timeout)
        if ok:
            eval_result = await evaluate(job_id, problem)
            if eval_result is None:
                return make_result(
                    problem,
                    "C_with_dissect",
                    "crash",
                    job_id,
                    duration=time.time() - t0,
                    error="No predictions found",
                    patches=total_patches,
                )
            return make_result(
                problem,
                "C_with_dissect",
                eval_result["decision"],
                job_id,
                duration=time.time() - t0,
                metrics=eval_result["metrics"],
                decision=eval_result["decision"],
                patches=total_patches,
            )

        logger.info(f"[{job_id}] Crash attempt {attempt}: activating Dissect")
        exc_type, exc_msg = _parse_exception(stderr)
        last_error = f"{exc_type}: {exc_msg}"

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
            "crash_attempt_number": 1,
        }

        try:
            await dissect.handle_crash(crash_event)
            await drain_patch_log_queue(dissect.redis)
        except Exception as e:
            logger.error(f"[{job_id}] Dissect handle_crash raised: {e}")
            return make_result(
                problem,
                "C_with_dissect",
                "escalate",
                job_id,
                duration=time.time() - t0,
                error=f"Dissect exception: {e}",
                patches=total_patches,
            )
        finally:
            try:
                await dissect.redis.close()
            except Exception:
                pass

        bak_path = script_path + ".bak"
        if os.path.exists(bak_path):
            total_patches += 1
            try:
                os.remove(bak_path)
            except Exception:
                pass
            continue
        else:
            return make_result(
                problem,
                "C_with_dissect",
                "escalate",
                job_id,
                duration=time.time() - t0,
                error=last_error,
                patches=total_patches,
            )

    return make_result(
        problem,
        "C_with_dissect",
        "escalate",
        job_id,
        duration=time.time() - t0,
        error=last_error,
        patches=total_patches,
    )


async def main():
    parser = argparse.ArgumentParser(description="Prometheus Swarm benchmark runner")
    parser.add_argument("--start", type=int, default=0, help="Index into problems.json")
    parser.add_argument("--count", type=int, default=10, help="Number of problems to run")
    parser.add_argument(
        "--condition",
        choices=["A", "B", "C", "both", "all"],
        default="both",
        help="Which condition(s) to run (A=human baseline, B=no Dissect, C=with Dissect, all=A+B+C)",
    )
    parser.add_argument(
        "--output",
        help="Path to save combined baseline JSON (auto-generates if not provided)",
    )
    args = parser.parse_args()

    os.chdir(str(PROJECT_ROOT))
    problems = load_problems()
    batch_idx = args.start // args.count + 1
    batch = problems[args.start : args.start + args.count]

    if not batch:
        logger.error(f"No problems found at index {args.start}")
        sys.exit(1)

    results_a: list[dict] = []
    results_b: list[dict] = []
    results_c: list[dict] = []

    logger.info(f"Benchmark batch {batch_idx}: {len(batch)} problems, condition={args.condition}")

    for i, problem in enumerate(batch):
        job_id = make_job_id(problem["id"])
        print_problem_header(problem, args.start + i, len(problems))
        dataset_path = resolve_dataset_path(problem)

        try:
            await _run_single_problem(
                problem,
                job_id,
                dataset_path,
                args,
                batch_idx,
                results_a,
                results_b,
                results_c,
            )
        except Exception as e:
            logger.error(f"[{job_id}] Unhandled error: {e}", exc_info=True)
            for cond in ["B_no_dissect", "C_with_dissect"]:
                r = make_result(problem, cond, "crash", job_id, error=f"Benchmark error: {e}")
                if "B" in args.condition:
                    results_b.append(r)
                if "C" in args.condition:
                    results_c.append(r)
            continue

    # If --output specified, write combined baseline JSON
    if args.output:
        _write_combined_baseline(args.output, results_b, results_c, batch)


async def _run_single_problem(
    problem: dict,
    job_id: str,
    dataset_path: str,
    args,
    batch_idx: int,
    results_a: list,
    results_b: list,
    results_c: list,
):
    if not Path(dataset_path).exists():
        logger.warning(f"Dataset not found: {dataset_path}")
        for cond in ["B_no_dissect", "C_with_dissect"]:
            r = make_result(
                problem,
                cond,
                "crash",
                job_id,
                error=f"Dataset not found: {dataset_path}",
            )
            if "B" in args.condition:
                results_b.append(r)
            if "C" in args.condition:
                results_c.append(r)
        return

    brief = await run_scout_phase(job_id, problem)
    if brief is None:
        for cond in ["B_no_dissect", "C_with_dissect"]:
            r = make_result(problem, cond, "crash", job_id, error="Scout failed")
            if "B" in args.condition:
                results_b.append(r)
            if "C" in args.condition:
                results_c.append(r)
        return

    script_path = await run_forge_phase(job_id, brief)
    if script_path is None:
        for cond in ["B_no_dissect", "C_with_dissect"]:
            r = make_result(problem, cond, "crash", job_id, error="Forge failed")
            if "B" in args.condition:
                results_b.append(r)
            if "C" in args.condition:
                results_c.append(r)
        return

    # Determine timeout based on modality and dataset size
    n_rows = problem.get("num_rows_expected", 1000)
    if problem["modality"] == "image":
        timeout = 600
    elif problem["modality"] == "text":
        timeout = 600
    elif n_rows > 50000:
        timeout = 600
    elif n_rows > 10000:
        timeout = 300
    else:
        timeout = 120

    condition_effective = (
        {"A", "B", "C"}
        if args.condition == "all"
        else {args.condition} if args.condition != "both" else {"B", "C"}
    )

    if "A" in condition_effective:
        logger.info(f"[{job_id}] Condition A (Human Baseline)")
        r = await run_condition_a(problem, job_id, timeout)
        print_result(r)
        results_a.append(r)

    if "B" in condition_effective:
        logger.info(f"[{job_id}] Condition B (No Dissect)")
        r = await run_condition_b(problem, script_path, job_id, timeout)
        print_result(r)
        results_b.append(r)

    if "C" in condition_effective:
        _cmd = ["python", str(script_path)]
        r = await run_condition_c(problem, script_path, job_id, timeout)
        print_result(r)
        results_c.append(r)

    # Clean up training script and outputs
    try:
        Path(script_path).unlink(missing_ok=True)
        ckpt_dir = Path(f"outputs/{job_id}")
        if ckpt_dir.exists():
            shutil.rmtree(str(ckpt_dir))
    except Exception:
        pass

    # Save incrementally after each problem
    if results_b:
        save_results_batch("B_no_dissect", results_b, batch_idx)
    if results_c:
        save_results_batch("C_with_dissect", results_c, batch_idx)


def _get_git_commit() -> str:
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


def _write_combined_baseline(
    output_path: str, results_b: list[dict], results_c: list[dict], batch: list[dict]
):
    """Write a combined baseline_v1.json-style output with auto-metadata."""

    def _agg(results):
        total = len(results)
        passed = sum(1 for r in results if r["status"] == "pass")
        crashed = sum(1 for r in results if r["status"] == "crash")
        escalated = sum(1 for r in results if r["status"] == "escalate")
        metrics = [
            r["best_val_metric"]
            for r in results
            if r["best_val_metric"] is not None and r["status"] == "pass"
        ]
        avg_metric = sum(metrics) / len(metrics) if metrics else 0.0
        durations = [r["duration_seconds"] for r in results]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "total_problems": total,
            "passed": passed,
            "crashed": crashed,
            "escalated": escalated,
            "avg_metric": round(avg_metric, 6),
            "avg_duration_seconds": round(avg_duration, 2),
            "total_human_interventions": sum(r.get("human_interventions", 0) for r in results),
            "results": results,
        }

    pass_rate_b = (
        (sum(1 for r in results_b if r["status"] == "pass") / max(len(results_b), 1))
        if results_b
        else 0.0
    )
    pass_rate_c = (
        (sum(1 for r in results_c if r["status"] == "pass") / max(len(results_c), 1))
        if results_c
        else 0.0
    )

    output = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metadata": {
            "git_commit": _get_git_commit(),
            "platform": platform.system(),
            "condition": "both",
            "problems_file": str(BENCHMARK_PATH),
        },
        "condition_b": _agg(results_b) if results_b else {},
        "condition_c": _agg(results_c) if results_c else {},
        "comparison": {
            "pass_rate_b": round(pass_rate_b, 4),
            "pass_rate_c": round(pass_rate_c, 4),
            "improvement_pp": round(pass_rate_c - pass_rate_b, 4),
        },
    }
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    logger.info(f"Combined baseline written to {output_path}")


if __name__ == "__main__":
    import pandas as pd

    asyncio.run(main())

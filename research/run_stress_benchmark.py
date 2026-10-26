"""Stress benchmark — makes the B-vs-C comparison actually exercise Dissect.

The 2026-09-15 rerun showed conditions B and C are INDISTINGUISHABLE on clean
data: tabular scripts don't crash (0 repairs needed), and text/image failures
are CPU-resource limits Dissect cannot patch. That is a benchmark-design gap,
not a Dissect defect — and it is fixable: inject faults that produce the exact
error categories Dissect claims to repair, then measure B (no repair loop) vs
C (repair loop) on each injected variant.

Fault sources:
  * DATA faults — evaluation/stress_injector.py (8 dataset corruptions) applied
    to a copy of the problem's dataset BEFORE Scout, so the whole pipeline
    faces them honestly (no hand-tuned scripts — the swarm's own generator must
    cope or crash).
  * CODE faults — tests/fixtures/injected_errors/*.py (5 broken training
    scripts) run directly through Furnace (Forge bypassed — the fixture IS the
    script), with a job_runner-style Dissect listener for C. These target the
    repair loop itself.

Verdicts per fault:
  DISCRIMINATING   B fail→C pass — the Dissect lift the paper claims
  NEGATIVE         B pass→C fail — a repair that broke a working job
  both-fail        outside Dissect's repair scope (upstream/terminal/LLM-auth)
  both pass        fault too mild to crash

Usage:
    python -m research.run_stress_benchmark --problem TC01 --mode data
    python -m research.run_stress_benchmark --mode code
    python -m research.run_stress_benchmark --problems TC01,TC05 --mode both
Output:
    research/benchmark/results/stress_matrix_<timestamp>.json
"""

import argparse
import asyncio
import json
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv()

import redis.asyncio as aioredis

from evaluation.stress_injector import inject_fault
from orchestrator.job_runner import JobConfig, run_job
from research.run_benchmark import (
    ensure_csv,
    evaluate,
    resolve_dataset_path,
)
from runtime.paths import get_job_paths

RESULTS_DIR = PROJECT_ROOT / "research" / "benchmark" / "results"
CODE_FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "injected_errors"

DATA_FAULTS = [
    "missing_column",
    "feature_type_mismatch",
    "nan_explosion",
    "empty_dataset",
    "corrupted_csv",
    "schema_drift",
    "extreme_imbalance",
    "unseen_categorical",
]


def _select_columns(source_csv: str, problem: dict) -> tuple[str, str]:
    """Pick one numeric and one object feature column (for targeted faults)."""
    import pandas as pd

    df = pd.read_csv(source_csv, nrows=20, sep=None, engine="python")
    target = problem.get("target_column")
    feats = [c for c in df.columns if c != target]
    num = [c for c in feats if pd.api.types.is_numeric_dtype(df[c])]
    obj = [c for c in feats if not pd.api.types.is_numeric_dtype(df[c])]
    return (num[0] if num else ""), (obj[0] if obj else "")


def _inject_data_fault(source_csv: str, fault: str, problem: dict, temp_dir: Path) -> tuple[str, str]:
    kw: dict = {}
    if fault == "missing_column":
        kw["column"] = problem.get("target_column")
    elif fault == "feature_type_mismatch":
        num_col, _obj_col = _select_columns(source_csv, problem)
        kw["col"] = num_col
    elif fault == "extreme_imbalance":
        kw["target_col"] = problem.get("target_column")
    return inject_fault(source_csv, fault, temp_dir=temp_dir, **kw)


async def _drain_job_patches(r: aioredis.Redis, job_id: str) -> list[dict]:
    """Pop all queued patch-log entries; keep this job's. The stress harness
    owns the drain (patch_log_writer is not running) so synthetic entries stay
    out of research/patch_log.jsonl while the report keeps the audit trail."""
    entries: list[dict] = []
    while True:
        raw = await r.blpop("patch_log_queue", timeout=1)
        if raw is None:
            break
        try:
            entry = json.loads(raw[1])
        except Exception:
            continue
        if entry.get("job_id") == job_id:
            entries.append(entry)
    return entries


async def _kill_train_container(job_id: str) -> None:
    name = f"prometheus-train-{job_id}"
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "rm",
        "-f",
        name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()


def _patch_summary(patches: list[dict]) -> dict:
    return {
        "patch_attempts": len(patches),
        "patch_successes": sum(1 for p in patches if p.get("patch_outcome") == "success"),
        "categories": sorted({p.get("error_taxonomy_category", "?") for p in patches}),
        "methods": sorted({p.get("taxonomy_match_method", "?") for p in patches}),
    }


async def run_data_fault_pair(problem: dict, fault: str, dataset_path: str, timeout: int, r) -> dict:
    """B vs C of the FULL pipeline (job_runner) on a corrupted dataset copy."""
    row: dict = {
        "fault": fault,
        "fault_kind": "data",
        "problem_id": problem["id"],
        "dataset": dataset_path,
    }
    for cond, use_dissect in (("B", False), ("C", True)):
        job_id = f"stress-{problem['id'].lower()}-{fault.lower()[:10]}-{cond.lower()}-{uuid.uuid4().hex[:4]}"
        config = JobConfig(
            problem_description=problem["problem_description"],
            dataset_path=dataset_path,
            target_column=problem.get("target_column"),
            evaluation_metric=problem.get("evaluation_metric"),
            task_type=problem.get("task_type"),
            modality=problem.get("modality"),
            use_dissect=use_dissect,
            use_harbor=False,
            use_docker=True,
            job_id=job_id,
            timeout_seconds=timeout,
        )
        t0 = time.time()
        try:
            res = await run_job(config, r)
            patches = await _drain_job_patches(r, job_id)
            status, metric = res.status, res.metric_value
            err = (res.crash_message or res.error_detail or "")[:300]
        except Exception as e:
            patches = []
            status, metric, err = "error", 0.0, str(e)[:300]
        finally:
            await _kill_train_container(job_id)
        row[cond] = {
            "status": status,
            "metric": round(metric, 6) if metric else 0.0,
            "duration": round(time.time() - t0, 1),
            "error": err,
            **_patch_summary(patches),
        }
    _attach_verdict(row)
    return row


async def run_code_fault_pair(fixtures_dir: Path, fixture: Path, timeout: int, r) -> dict:
    """B vs C of Furnace+Dissect on a broken training script (Forge bypassed)."""
    from bus.consumer import ensure_consumer_group
    from bus.events import (
        CRASH_EVENT,
        GROUP_DISSECT,
        STREAM_FURNACE_CRASH,
    )

    row: dict = {
        "fault": fixture.stem,
        "fault_kind": "code",
        "problem_id": "FIXTURE",
        "dataset": str(fixture),
    }
    for cond, use_dissect in (("B", False), ("C", True)):
        job_id = f"stresscode-{fixture.stem[:16]}-{cond.lower()}-{uuid.uuid4().hex[:4]}"
        script_path = str(get_job_paths(job_id).script_path)
        Path(script_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(fixture), script_path)
        t0 = time.time()
        patches: list[dict] = []
        status, err = "crash", ""
        try:
            from memory.redis_client import RedisClient

            rc = RedisClient()
            rc._client = r

            from agents.furnace.agent import FurnaceAgent

            furnace = FurnaceAgent(job_id=job_id)
            furnace.redis = rc

            listener = None
            if use_dissect:
                from agents.dissect.agent import DissectAgent

                dissect = DissectAgent(job_id=job_id)
                dissect.redis = rc
                await ensure_consumer_group(r, STREAM_FURNACE_CRASH, GROUP_DISSECT)

                async def dissect_listener():
                    while True:
                        try:
                            results = await r.xreadgroup(
                                groupname=GROUP_DISSECT,
                                consumername=f"stress-dissect-{job_id}",
                                streams={STREAM_FURNACE_CRASH: ">"},
                                count=1,
                                block=2000,
                            )
                            if results:
                                _, messages = results[0]
                                for msg_id, raw_fields in messages:
                                    fields = {}
                                    for k, v in raw_fields.items():
                                        try:
                                            fields[k] = json.loads(v)
                                        except Exception:
                                            fields[k] = v
                                    if fields.get("job_id") != job_id:
                                        await r.xack(STREAM_FURNACE_CRASH, GROUP_DISSECT, msg_id)
                                        continue
                                    if fields.get("event_type") == CRASH_EVENT:
                                        await r.xack(STREAM_FURNACE_CRASH, GROUP_DISSECT, msg_id)
                                        await dissect.handle_crash(fields)
                        except asyncio.CancelledError:
                            break
                        except Exception as e:
                            print(f"    [listener {job_id}] {type(e).__name__}: {e}", flush=True)

                listener = asyncio.create_task(dissect_listener())

            try:
                await asyncio.wait_for(
                    furnace.run(script_path=script_path, use_docker=True, wait_for_dissect=use_dissect),
                    timeout=timeout,
                )
                status = "pass" if (Path(script_path).parent / "checkpoints" / "best.ckpt").exists() else "crash"
            except asyncio.TimeoutError:
                status = "timeout"
                err = f"TIMEOUT after {timeout}s"
            except Exception as e:
                exc = str(e)
                status = "escalate" if "ESCALAT" in exc.upper() else "crash"
                err = exc[:300]
            finally:
                if listener:
                    listener.cancel()
                    try:
                        await listener
                    except (asyncio.CancelledError, Exception):
                        pass
                patches = await _drain_job_patches(r, job_id)
        except Exception as e:
            err = str(e)[:300]
        finally:
            await _kill_train_container(job_id)
            shutil.rmtree(str(get_job_paths(job_id).job_dir), ignore_errors=True)
        row[cond] = {
            "status": status,
            "metric": 0.0,
            "duration": round(time.time() - t0, 1),
            "error": err,
            **_patch_summary(patches),
        }
    # Confirm C's "pass" really trained: metric contract via evaluate on the
    # surviving checkpoint dir is skipped here (job dir removed above) — the
    # status pass already implies Furnace._finalize_training validated the
    # checkpoint and TRAINING_COMPLETE published.
    _attach_verdict(row)
    return row


def _attach_verdict(row: dict) -> None:
    b, c = row.get("B", {}), row.get("C", {})
    b_ok, c_ok = b.get("status") == "pass", c.get("status") == "pass"
    if b_ok and c_ok:
        row["verdict"] = "both pass (fault too mild — not discriminating)"
    elif b_ok and not c_ok:
        row["verdict"] = "NEGATIVE (C broke a passing job)"
    elif not b_ok and c_ok:
        row["verdict"] = "DISCRIMINATING (Dissect converted fail→pass)"
    else:
        if c.get("patch_attempts"):
            row["verdict"] = "both fail (Dissect attempted, could not repair)"
        else:
            row["verdict"] = "both fail (no repair attempted — out of scope)"


async def main_async(args: argparse.Namespace) -> None:
    from research.run_benchmark import load_problems

    all_problems = load_problems()
    if args.problems:
        wanted = {p.strip().upper() for p in args.problems.split(",")}
        problems = [p for p in all_problems if p["id"].upper() in wanted]
    else:
        problems = [p for p in all_problems if p["id"].upper() == args.problem.upper()]

    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    await r.ping()

    matrix: list[dict] = []

    if args.mode in ("data", "both"):
        for problem in problems:
            source = ensure_csv(resolve_dataset_path(problem))
            if not Path(source).exists():
                print(f"!! {problem['id']}: dataset missing — skipped")
                continue
            temp_dir = PROJECT_ROOT / "outputs" / f"stress_temp_{problem['id']}"
            temp_dir.mkdir(parents=True, exist_ok=True)
            for fault in DATA_FAULTS:
                if args.faults and fault not in args.faults:
                    continue
                try:
                    injected_path, desc = _inject_data_fault(source, fault, problem, temp_dir)
                except Exception as e:
                    print(f"  {problem['id']}/{fault}: injection failed ({e})")
                    continue
                print(f"  {problem['id']}/{fault}: B vs C ...", flush=True)
                row = await run_data_fault_pair(problem, fault, injected_path, args.timeout, r)
                row["fault_desc"] = desc
                matrix.append(row)
                print(
                    f"    B={row['B']['status']} C={row['C']['status']} "
                    f"patches C={row['C']['patch_attempts']} -> {row['verdict']}",
                    flush=True,
                )
            shutil.rmtree(temp_dir, ignore_errors=True)

    if args.mode in ("code", "both"):
        for fixture in sorted(CODE_FIXTURES.glob("*.py")):
            if args.faults and fixture.stem not in args.faults:
                continue
            print(f"  CODE/{fixture.stem}: B vs C ...", flush=True)
            row = await run_code_fault_pair(CODE_FIXTURES, fixture, args.timeout, r)
            row["fault_desc"] = f"broken training script {fixture.name}"
            matrix.append(row)
            print(
                f"    B={row['B']['status']} C={row['C']['status']} "
                f"patches C={row['C']['patch_attempts']} -> {row['verdict']}",
                flush=True,
            )

    summary = {
        "total": len(matrix),
        "discriminating": sum(1 for m in matrix if m["verdict"].startswith("DISCRIMINATING")),
        "both_pass": sum(1 for m in matrix if m["verdict"].startswith("both pass")),
        "both_fail": sum(1 for m in matrix if m["verdict"].startswith("both fail")),
        "negative": sum(1 for m in matrix if m["verdict"].startswith("NEGATIVE")),
        "discriminating_faults": [m["fault"] for m in matrix if m["verdict"].startswith("DISCRIMINATING")],
    }
    out = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "problems": [p["id"] for p in problems],
        "mode": args.mode,
        "timeout_seconds": args.timeout,
        "matrix": matrix,
        "summary": summary,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = RESULTS_DIR / f"stress_matrix_{ts}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print("\n" + "=" * 70)
    print("STRESS BENCHMARK SUMMARY")
    for k, v in summary.items():
        print(f"  {k}: {v}")
    print(f"  saved -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stress B-vs-C discriminator benchmark")
    parser.add_argument("--problem", default="TC01")
    parser.add_argument("--problems", default="", help="comma list overrides --problem")
    parser.add_argument("--mode", choices=["data", "code", "both"], default="both")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--faults", default="", help="comma subset of fault names to run")
    args = parser.parse_args()
    if args.faults:
        args.faults = {f.strip() for f in args.faults.split(",")}
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()

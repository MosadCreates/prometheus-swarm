"""
Campaign runner — runs the 10-problem benchmark N times to measure learning.

Usage:
    # Run 3 campaigns (repetitions) on the first 10 tabular problems:
    python research/run_campaign.py --runs 3 --count 10 --name pilot-v1

    # Run on specific problems:
    python research/run_campaign.py --problems tc01,tc02,tc03 --runs 2

    # Dry-run: analyze existing data without running new experiments:
    python research/run_campaign.py --analyze --name pilot-v1
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from runtime.paths import get_job_paths
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("campaign")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATH = PROJECT_ROOT / "research/benchmark/problems.json"
RESULTS_DIR = PROJECT_ROOT / "research/benchmark/results"
CAMPAIGNS_DIR = PROJECT_ROOT / "research/campaigns"
PATCH_LOG_PATH = PROJECT_ROOT / "research/patch_log.jsonl"


def load_problems():
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def get_10_problem_subset(problems: list[dict]) -> list[dict]:
    """Select the first 10 tabular problems (TC01-TC10) as the pilot subset."""
    tabular = [p for p in problems if p.get("modality") == "tabular"]
    return tabular[:10]


def make_run_id() -> str:
    return uuid.uuid4().hex[:8]


def save_campaign_manifest(campaign_dir: Path, manifest: dict):
    campaign_dir.mkdir(parents=True, exist_ok=True)
    path = campaign_dir / "manifest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    logger.info(f"Campaign manifest saved -> {path}")


def load_patch_log() -> list[dict]:
    entries = []
    if not PATCH_LOG_PATH.exists():
        return entries
    with open(PATCH_LOG_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def partition_patch_log_by_time(entries: list[dict], n_slices: int = 3):
    """Partition patch log entries into N time-based slices for trend analysis.
    Each slice simulates one run of the campaign.
    """
    if not entries:
        return []

    def _parse_ts(e):
        ts = e.get("timestamp", "")
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return datetime.min.replace(tzinfo=timezone.utc)

    sorted_entries = sorted(entries, key=_parse_ts)
    total = len(sorted_entries)
    slice_size = max(total // n_slices, 1)
    slices = []
    for i in range(n_slices):
        start = i * slice_size
        end = (i + 1) * slice_size if i < n_slices - 1 else total
        slices.append(sorted_entries[start:end])
    return slices


def compute_run_metrics(patch_entries: list[dict], run_results: list[dict] | None = None) -> dict:
    """Compute a complete metrics snapshot for a single campaign run."""
    total_patches = len(patch_entries)
    llm_calls = sum(1 for e in patch_entries if e.get("llm_used_for_repair", False))
    regex_calls = sum(1 for e in patch_entries if e.get("taxonomy_match_method") == "regex")
    successful = sum(1 for e in patch_entries if e.get("patch_outcome") == "success")
    rollbacks = sum(1 for e in patch_entries if e.get("patch_outcome") == "rollback")
    escalated = sum(1 for e in patch_entries if e.get("patch_outcome") == "escalated")

    # Cascade level distribution
    cascade: dict[str, int] = {}
    for e in patch_entries:
        cat = e.get("error_taxonomy_category", "unknown")
        method = e.get("taxonomy_match_method", "")
        if method == "regex":
            lev = "level0_rule"
        elif method in ("llm", "llm_classification"):
            retrieved = e.get("retrieved_similar_patches", [])
            if retrieved:
                lev = "level3_memory"
            else:
                lev = "level4_llm"
        else:
            lev = "unknown"
        cascade[lev] = cascade.get(lev, 0) + 1

    # Approximate token/cost estimation
    input_tokens = llm_calls * 3000
    output_tokens = llm_calls * 800
    input_cost = input_tokens * 3.0 / 1_000_000
    output_cost = output_tokens * 15.0 / 1_000_000
    total_cost = round(input_cost + output_cost, 4)

    # Error category distribution
    cat_dist: dict[str, int] = {}
    for e in patch_entries:
        cat = e.get("error_taxonomy_category", "unknown")
        cat_dist[cat] = cat_dist.get(cat, 0) + 1

    # Attempt distribution
    attempt_dist: dict[str, int] = {}
    for e in patch_entries:
        att = str(e.get("attempt_number", 1))
        attempt_dist[att] = attempt_dist.get(att, 0) + 1

    # Result metrics from run_results
    pass_count = 0
    fail_count = 0
    total_duration = 0.0
    if run_results:
        for r in run_results:
            if r.get("status") == "pass":
                pass_count += 1
            else:
                fail_count += 1
            total_duration += r.get("duration_seconds", 0)

    metrics = {
        "total_patches": total_patches,
        "llm_calls": llm_calls,
        "regex_calls": regex_calls,
        "successful_patches": successful,
        "rollbacks": rollbacks,
        "escalations": escalated,
        "patch_success_rate": round(successful / max(total_patches, 1), 4),
        "cascade_distribution": cascade,
        "cat_distribution": cat_dist,
        "attempt_distribution": attempt_dist,
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_cost_usd": total_cost,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "total_duration_s": round(total_duration, 2),
        "pass_rate": round(pass_count / max(pass_count + fail_count, 1), 4),
        "unique_errors_seen": len(cat_dist),
        "llm_fallback_rate": round(llm_calls / max(total_patches, 1), 4),
    }
    return metrics


async def _flush_patch_queue_to_file() -> None:
    """Read all pending entries from Redis patch_log_queue and write to file."""
    import redis.asyncio as aioredis
    from filelock import FileLock

    r = aioredis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        decode_responses=True,
    )
    path = Path(os.getenv("PATCH_LOG_PATH", "./research/patch_log.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            result = await r.blpop("patch_log_queue", timeout=1)
            if result is None:
                break
            _, raw = result
            entry = json.loads(raw)
            lock_file = str(path) + ".lock"
            with FileLock(lock_file):
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except Exception:
            break
    await r.aclose()


async def run_campaign_live(
    problems: list[dict],
    num_runs: int,
    campaign_dir: Path,
    condition: str = "C",
):
    """Run the benchmark N times live, collecting metrics per run."""
    from research.run_benchmark import (
        run_scout_phase,
        run_forge_phase,
        run_condition_b,
        run_condition_c,
        make_job_id,
        ensure_dataset_available,
        resolve_dataset_path,
        make_result,
    )

    # Load existing patch_log to get baseline count
    pre_patch_count = len(load_patch_log())

    for run_idx in range(1, num_runs + 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"CAMPAIGN RUN {run_idx}/{num_runs}")
        logger.info(f"{'='*60}")

        run_id = make_run_id()
        run_results_cond: list[dict] = []

        for problem in problems:
            job_id = make_job_id(problem["id"])
            dataset_path = resolve_dataset_path(problem)

            # Ensure dataset
            local_path = await ensure_dataset_available(problem)
            if local_path is None:
                logger.warning(f"[{problem['id']}] Dataset unavailable, skipping")
                continue

            # Scout
            brief = await run_scout_phase(job_id, problem)
            if brief is None:
                continue

            # Forge
            script_path = await run_forge_phase(job_id, brief)
            if script_path is None:
                continue

            # Determine timeout
            timeout = 300
            if problem.get("modality") in ("image", "text"):
                timeout = 600
            elif problem.get("num_rows_expected", 1000) > 50000:
                timeout = 600

            # Run condition
            if condition == "B":
                r = await run_condition_b(problem, script_path, job_id, timeout)
            else:
                r = await run_condition_c(problem, script_path, job_id, timeout)
            run_results_cond.append(r)

            # Flush patch log queue to file
            try:
                await _flush_patch_queue_to_file()
            except Exception:
                pass

            # Cleanup
            try:
                Path(script_path).unlink(missing_ok=True)
                ckpt_dir = get_job_paths(job_id).job_dir
                if ckpt_dir.exists():
                    shutil.rmtree(str(ckpt_dir))
            except Exception:
                pass

        # Compute metrics for this run from new patch_log entries
        post_patch_count = len(load_patch_log())
        new_entries = load_patch_log()[pre_patch_count:]
        metrics = compute_run_metrics(new_entries, run_results_cond)

        # Save run results
        run_dir = campaign_dir / f"run_{run_idx:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)
        with open(run_dir / "results.json", "w", encoding="utf-8") as f:
            json.dump(run_results_cond, f, indent=2)
        with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

        # Print summary
        logger.info(f"\nRun {run_idx} metrics:")
        logger.info(f"  Pass rate: {metrics['pass_rate']:.1%}")
        logger.info(f"  LLM calls: {metrics['llm_calls']}")
        logger.info(f"  Cost: ${metrics['estimated_cost_usd']:.4f}")
        logger.info(f"  Cascade: {metrics['cascade_distribution']}")


def run_campaign_analysis(
    problems: list[dict],
    num_runs: int,
    campaign_dir: Path,
):
    """Analyze existing patch_log and benchmark data to demonstrate learning trends.
    Partitions the patch_log into time slices to simulate repeated runs.
    """
    patch_entries = load_patch_log()
    if not patch_entries:
        logger.warning("No patch_log.jsonl found. Run the benchmark first.")
        return

    # Partition by time
    slices = partition_patch_log_by_time(patch_entries, num_runs)

    # Load latest benchmark results for reference
    benchmark_results: list[dict] = []
    results_files = sorted(RESULTS_DIR.glob("batch_*_condition_*.json"))
    if results_files:
        with open(results_files[-1], encoding="utf-8") as f:
            benchmark_results = json.load(f)

    for run_idx, slice_entries in enumerate(slices, 1):
        # Determine approximate run results from benchmark data
        run_results = benchmark_results if run_idx == len(slices) else []

        metrics = compute_run_metrics(slice_entries, run_results)
        run_dir = campaign_dir / f"run_{run_idx:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)

        with open(run_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
        with open(run_dir / "patch_log_slice.json", "w", encoding="utf-8") as f:
            json.dump(slice_entries, f, indent=2)

        logger.info(f"\nRun {run_idx} (time slice {run_idx}/{num_runs}):")
        logger.info(f"  Entries: {len(slice_entries)}")
        logger.info(f"  LLM calls: {metrics['llm_calls']}")
        logger.info(f"  Regex calls: {metrics['regex_calls']}")
        logger.info(f"  Cascade: {metrics['cascade_distribution']}")
        logger.info(f"  Cost: ${metrics['estimated_cost_usd']:.4f}")

    # Save overall manifest
    manifest = {
        "campaign_name": campaign_dir.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "num_runs": num_runs,
        "num_problems": len(problems),
        "condition": "analyze (post-hoc)",
        "problem_ids": [p["id"] for p in problems],
        "git_tag": "v1.0-research-freeze",
        "run_dirs": [f"run_{i:02d}" for i in range(1, num_runs + 1)],
    }
    save_campaign_manifest(campaign_dir, manifest)


def main():
    parser = argparse.ArgumentParser(description="Prometheus Swarm campaign runner")
    parser.add_argument("--runs", type=int, default=3, help="Number of campaign runs (repetitions)")
    parser.add_argument(
        "--count", type=int, default=10, help="Number of problems to use from subset"
    )
    parser.add_argument("--problems", help="Comma-separated problem IDs (overrides --count)")
    parser.add_argument("--name", default=None, help="Campaign name (auto-generated if not given)")
    parser.add_argument(
        "--condition", choices=["B", "C", "both"], default="C", help="Which condition to run"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Analysis-only mode: partitions existing patch_log by time",
    )
    args = parser.parse_args()

    os.chdir(str(PROJECT_ROOT))
    problems = load_problems()

    if args.problems:
        pids = [p.strip().lower() for p in args.problems.split(",")]
        problems = [p for p in problems if p["id"].lower() in pids]
    else:
        problems = get_10_problem_subset(problems)[: args.count]

    if not problems:
        logger.error("No problems matched")
        sys.exit(1)

    campaign_name = args.name or f"campaign-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    campaign_dir = CAMPAIGNS_DIR / campaign_name

    logger.info(f"Campaign: {campaign_name}")
    logger.info(f"Problems: {[p['id'] for p in problems]}")
    logger.info(f"Runs: {args.runs}")
    logger.info(f"Mode: {'analysis (post-hoc)' if args.analyze else 'live'}")

    if args.analyze:
        run_campaign_analysis(problems, args.runs, campaign_dir)
    else:
        asyncio.run(run_campaign_live(problems, args.runs, campaign_dir, args.condition))

    # Save campaign summary
    run_metrics = []
    for i in range(1, args.runs + 1):
        metrics_path = campaign_dir / f"run_{i:02d}" / "metrics.json"
        if metrics_path.exists():
            with open(metrics_path) as f:
                run_metrics.append(json.load(f))

    summary = {
        "campaign_name": campaign_name,
        "num_runs": args.runs,
        "num_problems": len(problems),
        "condition": args.condition,
        "run_metrics": run_metrics,
        "trends": {},
    }
    if run_metrics:
        summary["trends"] = {
            "llm_calls": [m["llm_calls"] for m in run_metrics],
            "pass_rate": [m["pass_rate"] for m in run_metrics],
            "cost": [m["estimated_cost_usd"] for m in run_metrics],
            "llm_fallback_rate": [m["llm_fallback_rate"] for m in run_metrics],
            "patch_success_rate": [m["patch_success_rate"] for m in run_metrics],
        }
    summary_path = campaign_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Campaign summary saved -> {summary_path}")
    print(f"\nCampaign output: {campaign_dir}")


if __name__ == "__main__":
    main()

"""Benchmark CLI — summary, wins, and stats from benchmark results."""

from __future__ import annotations

import json
import os
import glob

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode

BENCHMARK_RESULTS_DIR = "research/benchmark/results"


@click.group(
    cls=AliasedGroup,
    name="benchmark",
    aliases={"bench": "benchmark"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def benchmark():
    """Benchmark commands — inspect benchmark results."""


@benchmark.command(name="summary")
@click.pass_context
def benchmark_summary(ctx):
    """Show aggregated benchmark results across all conditions."""
    renderer = renderer_from_ctx(ctx)

    results = _load_benchmark_results()
    if not results:
        renderer.error("No benchmark results found.", title="No data")
        return ExitCode.ERROR_NOT_FOUND

    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "pass")
    crashed = sum(
        1 for r in results if r.get("status") == "crash" and r.get("status") != "escalate"
    )
    escalated = sum(1 for r in results if r.get("status") == "escalate")
    retried = sum(1 for r in results if r.get("status") == "retry")

    metrics = [
        r["best_val_metric"]
        for r in results
        if r.get("best_val_metric") is not None and r.get("status") == "pass"
    ]
    avg_metric = sum(metrics) / len(metrics) if metrics else 0.0

    durations = [r.get("duration_seconds", 0) for r in results if r.get("duration_seconds")]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    renderer.print(f"\n  [bold]Benchmark Summary[/]  [dim]{total} problems[/]")
    renderer.print()
    renderer.print(
        f"  Passed:    [green]{passed}[/]  ({passed / total * 100:.0f}%)"
        if total
        else "  Passed:    0"
    )
    renderer.print(f"  Retried:   [yellow]{retried}[/]")
    renderer.print(f"  Escalated: [red]{escalated}[/]")
    renderer.print(f"  Crashed:   [red]{crashed}[/]")
    renderer.print(f"  Avg metric: {avg_metric:.4f}" if avg_metric else "")
    renderer.print(f"  Avg duration: {avg_duration:.0f}s" if avg_duration else "")
    renderer.print()
    return ExitCode.SUCCESS


@benchmark.command(name="wins")
@click.pass_context
def benchmark_wins(ctx):
    """Show architecture win rates across benchmark problems."""
    renderer = renderer_from_ctx(ctx)

    results = _load_benchmark_results()
    if not results:
        renderer.error("No benchmark results found.", title="No data")
        return ExitCode.ERROR_NOT_FOUND

    arch_stats: dict[str, dict] = {}
    for r in results:
        arch = r.get("architecture", "unknown")
        if arch not in arch_stats:
            arch_stats[arch] = {"count": 0, "pass": 0, "retry": 0, "escalate": 0}
        arch_stats[arch]["count"] += 1
        status = r.get("status", "")
        if status in arch_stats[arch]:
            arch_stats[arch][status] += 1

    renderer.print("\n  [bold]Architecture Win Rates[/]  [dim]from benchmark[/]")
    renderer.print()
    for arch, s in sorted(arch_stats.items()):
        rate = s["pass"] / s["count"] * 100 if s["count"] else 0
        renderer.print(
            f"  [bold]{arch:<14}[/]  {s['count']:>3} runs  "
            f"[green]{rate:.0f}% pass[/]  "
            f"[yellow]{s['retry']} retries[/]  "
            f"[red]{s['escalate']} escalated[/]"
        )
    renderer.print()
    return ExitCode.SUCCESS


@benchmark.command(name="stats")
@click.pass_context
def benchmark_stats(ctx):
    """Show execution statistics from benchmark data."""
    renderer = renderer_from_ctx(ctx)

    results = _load_benchmark_results()
    if not results:
        renderer.error("No benchmark results found.", title="No data")
        return ExitCode.ERROR_NOT_FOUND

    arch_data: dict[str, dict] = {}
    for r in results:
        arch = r.get("architecture", "unknown")
        if arch not in arch_data:
            arch_data[arch] = {"count": 0, "durations": [], "metrics": []}
        d = arch_data[arch]
        d["count"] += 1
        dur = r.get("duration_seconds")
        if dur:
            d["durations"].append(dur)
        met = r.get("best_val_metric")
        if met is not None:
            d["metrics"].append(met)

    renderer.print("\n  [bold]Benchmark Statistics[/]  [dim]per architecture[/]")
    renderer.print()
    for arch, d in sorted(arch_data.items()):
        avg_dur = sum(d["durations"]) / len(d["durations"]) / 60 if d["durations"] else 0
        avg_met = sum(d["metrics"]) / len(d["metrics"]) if d["metrics"] else 0
        renderer.print(
            f"  [bold]{arch:<14}[/]  {d['count']:>3} runs  "
            f"avg [yellow]{avg_dur:.1f}m[/]  "
            f"metric [green]{avg_met:.4f}[/]"
        )
    renderer.print()
    return ExitCode.SUCCESS


def _load_benchmark_results() -> list[dict]:
    """Load all benchmark result files from the results directory."""
    results = []
    pattern = os.path.join(BENCHMARK_RESULTS_DIR, "*.json")
    for path in glob.glob(pattern):
        if os.path.basename(path) == "aggregate_reports.json":
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results

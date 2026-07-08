"""Evaluation CLI — run, compare, report, visualize, list, failures, calibration."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EXPERIMENTS_DIR = _PROJECT_ROOT / "experiments"
_FIGURES_DIR = _PROJECT_ROOT / "research" / "figures"
_REPORTS_DIR = _PROJECT_ROOT / "research" / "reports"
_BENCHMARK_PATH = _PROJECT_ROOT / "research" / "benchmark" / "problems.json"
_BASELINE_DEFAULT = _PROJECT_ROOT / "research" / "benchmark" / "baseline_v1.json"
_BATCH_DIR = _PROJECT_ROOT / "research" / "benchmark" / "results"


@click.group(
    cls=AliasedGroup,
    name="evaluate",
    aliases={"eval": "evaluate"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def evaluate():
    """Research validation — run experiments, compare hypotheses, generate reports & figures."""


# ── evaluate run ──────────────────────────────────────────────────────


@evaluate.command(name="run")
@click.option("--start", type=int, default=0, help="Index into problems.json")
@click.option("--count", type=int, default=5, help="Number of problems to run")
@click.option(
    "--condition",
    type=click.Choice(["A", "B", "C", "both", "all"]),
    default="C",
    help="Which condition(s) to run",
)
@click.option("--timeout", type=int, default=300, help="Timeout per script (s)")
@click.option("--name", default="CLI benchmark run", help="Experiment set name")
@click.pass_context
def evaluate_run(ctx, start, count, condition, timeout, name):
    """Run benchmark experiments and capture results as an ExperimentSet."""
    renderer = renderer_from_ctx(ctx)
    renderer.print(
        f"\n  [bold]Running evaluation ({condition})[/] — {count} problems from index {start}\n"
    )

    problems = _load_problems()
    batch = problems[start : start + count]

    if not batch:
        renderer.error(f"No problems in range {start}..{start + count}", title="Empty range")
        return ExitCode.ERROR

    from research.validation.runner import run_benchmark_batch

    exp_set = asyncio.run(
        run_benchmark_batch(
            batch,
            start=start,
            conditions=condition,
            timeout_per_problem=timeout,
            experiment_name=name,
        )
    )

    # Summarise
    for h_key, exp in exp_set.experiments.items():
        total = len(exp.runs)
        successes = sum(1 for r in exp.runs if r.research_metrics.deployment_success is True)
        renderer.print(
            f"  [bold]{h_key}:[/] {total} runs, [green]{successes} passed[/]"
            f" ({successes / max(total, 1) * 100:.0f}%)"
        )

    renderer.print(f"\n  Experiment set saved: [bold]{exp_set.set_id}[/bold]")
    renderer.print(f"  {_EXPERIMENTS_DIR / f'{exp_set.set_id}.json'}")
    renderer.print()

    return ExitCode.SUCCESS


# ── evaluate compare ──────────────────────────────────────────────────


@evaluate.command(name="compare")
@click.argument("experiment_set_id")
@click.option("--h1-vs-h2", is_flag=True, help="Compare H1 vs H2")
@click.option("--h2-vs-h3", is_flag=True, help="Compare H2 vs H3")
@click.option("--h1-vs-h3", is_flag=True, help="Compare H1 vs H3")
@click.option("--all", "all_", is_flag=True, help="Run all comparisons")
@click.pass_context
def evaluate_compare(ctx, experiment_set_id, h1_vs_h2, h2_vs_h3, h1_vs_h3, all_):
    """Compare hypotheses within an experiment set."""
    from research.validation.models import Experiment, ResearchHypothesis
    from research.validation.tracker import load_experiment_set
    from research.validation.statistics import compare_experiments

    renderer = renderer_from_ctx(ctx)

    path = _EXPERIMENTS_DIR / f"{experiment_set_id}.json"
    if not path.exists():
        path = Path(experiment_set_id)
        if not path.exists():
            renderer.error(f"Experiment set not found: {experiment_set_id}", title="Not found")
            return ExitCode.ERROR_NOT_FOUND

    exp_set = load_experiment_set(path)
    pairs = []

    if all_ or h1_vs_h2:
        pairs.append(("H1", "H2", ResearchHypothesis.H1, ResearchHypothesis.H2))
    if all_ or h2_vs_h3:
        pairs.append(("H2", "H3", ResearchHypothesis.H2, ResearchHypothesis.H3))
    if all_ or h1_vs_h3:
        pairs.append(("H1", "H3", ResearchHypothesis.H1, ResearchHypothesis.H3))

    METRICS_TO_COMPARE = [
        ("duration_seconds", "system", "Duration (s)"),
        ("final_metric", "research", "Final metric"),
        ("crashes", "system", "Crash count"),
        ("deployment_success", "research", "Deployment success"),
    ]

    renderer.print(f"\n  [bold]Comparing {exp_set.name}[/]\n")

    for label_a, label_b, h_a, h_b in pairs:
        runs_a = exp_set.experiments.get(h_a.value, Experiment(name="", hypothesis=h_a)).runs
        runs_b = exp_set.experiments.get(h_b.value, Experiment(name="", hypothesis=h_b)).runs

        if not runs_a or not runs_b:
            renderer.print(f"  [yellow]Skipping {label_a} vs {label_b}: missing data[/]")
            continue

        renderer.print(f"  [bold]{label_a} vs {label_b}[/]  ({len(runs_a)} vs {len(runs_b)} runs)")

        for metric_key, metric_group, label in METRICS_TO_COMPARE:
            cr = compare_experiments(runs_a, runs_b, metric_key, metric_group)
            sig = " [green]SIGNIFICANT[/]" if cr.significant else ""
            renderer.print(
                f"    {label:<20}  p={cr.p_value:.4f}  d={cr.effect_size:.3f}"
                f"  [{cr.ci_lower:.3f}, {cr.ci_upper:.3f}]{sig}"
            )

            # Store in experiment set
            result_key = f"compare_{h_a.value}_vs_{h_b.value}_{metric_key}"
            exp_set.comparisons[result_key] = cr

        renderer.print()

    from research.validation.tracker import save_experiment_set

    save_experiment_set(exp_set)

    renderer.print("  Comparisons saved to experiment set.\n")
    return ExitCode.SUCCESS


# ── evaluate report ───────────────────────────────────────────────────


@evaluate.command(name="report")
@click.argument("experiment_set_id")
@click.option("--title", default=None, help="Report title")
@click.pass_context
def evaluate_report(ctx, experiment_set_id, title):
    """Generate evaluation report (Markdown + JSON) for an experiment set."""
    from research.validation.tracker import load_experiment_set
    from research.validation.reports import save_report_to_disk
    from research.validation.failures import generate_failure_report

    renderer = renderer_from_ctx(ctx)

    path = _EXPERIMENTS_DIR / f"{experiment_set_id}.json"
    if not path.exists():
        path = Path(experiment_set_id)
        if not path.exists():
            renderer.error(f"Experiment set not found: {experiment_set_id}", title="Not found")
            return ExitCode.ERROR_NOT_FOUND

    exp_set = load_experiment_set(path)

    # Find figure files
    figure_paths = sorted(_FIGURES_DIR.glob("*.png")) if _FIGURES_DIR.exists() else []

    # Generate failure report
    all_runs = []
    for exp in exp_set.experiments.values():
        all_runs.extend(exp.runs)
    failure_rep = generate_failure_report(all_runs)

    md_path, json_path = save_report_to_disk(
        exp_set,
        figure_paths=figure_paths,
        failure_report=failure_rep,
        title=title,
    )

    renderer.print("\n  [bold]Report saved:[/]")
    renderer.print(f"    MD:   {md_path}")
    renderer.print(f"    JSON: {json_path}")
    renderer.print()
    return ExitCode.SUCCESS


# ── evaluate visualize ────────────────────────────────────────────────


@evaluate.command(name="visualize")
@click.argument("experiment_set_id")
@click.pass_context
def evaluate_visualize(ctx, experiment_set_id):
    """Generate all figures for an experiment set."""
    from research.validation.models import Experiment, ResearchHypothesis
    from research.validation.tracker import load_experiment_set
    from research.validation.figures import generate_all_figures

    renderer = renderer_from_ctx(ctx)

    path = _EXPERIMENTS_DIR / f"{experiment_set_id}.json"
    if not path.exists():
        path = Path(experiment_set_id)
        if not path.exists():
            renderer.error(f"Experiment set not found: {experiment_set_id}", title="Not found")
            return ExitCode.ERROR_NOT_FOUND

    exp_set = load_experiment_set(path)

    runs_h1 = exp_set.experiments.get(
        "H1", Experiment(name="", hypothesis=ResearchHypothesis.H1)
    ).runs
    runs_h2 = exp_set.experiments.get(
        "H2", Experiment(name="", hypothesis=ResearchHypothesis.H2)
    ).runs
    runs_h3 = exp_set.experiments.get(
        "H3", Experiment(name="", hypothesis=ResearchHypothesis.H3)
    ).runs

    renderer.print(f"\n  [bold]Generating figures for {exp_set.name}[/]\n")

    paths = generate_all_figures(runs_h1, runs_h2, runs_h3)

    for p in paths:
        renderer.print(f"    [green]✓[/] {p.name}")

    renderer.print(f"\n  [bold]{len(paths)} figures saved[/] to {_FIGURES_DIR}\n")
    return ExitCode.SUCCESS


# ── evaluate list ─────────────────────────────────────────────────────


@evaluate.command(name="list")
@click.pass_context
def evaluate_list(ctx):
    """List all saved experiment sets."""
    from research.validation.tracker import list_experiment_sets

    renderer = renderer_from_ctx(ctx)
    files = list_experiment_sets()

    if not files:
        renderer.print("  No experiment sets found.")
        return ExitCode.SUCCESS

    renderer.print(f"\n  [bold]Saved Experiment Sets[/]  ({len(files)})\n")

    for fp in files:
        try:
            exp_set = json.loads(fp.read_text())
            set_id = exp_set.get("set_id", fp.stem)
            name = exp_set.get("name", "")
            h_keys = list(exp_set.get("experiments", {}).keys())
            total_runs = sum(
                len(e.get("runs", [])) for e in exp_set.get("experiments", {}).values()
            )
            renderer.print(
                f"  [bold]{set_id}[/]  {name[:50]}"
                f"  [dim]{', '.join(h_keys)}[/]  {total_runs} runs"
            )
        except Exception:
            renderer.print(f"  [dim]{fp.name}[/]")

    renderer.print()
    return ExitCode.SUCCESS


# ── evaluate failures ─────────────────────────────────────────────────


@evaluate.command(name="failures")
@click.argument("experiment_set_id")
@click.pass_context
def evaluate_failures(ctx, experiment_set_id):
    """Analyse failures in an experiment set."""
    from research.validation.tracker import load_experiment_set
    from research.validation.failures import generate_failure_report

    renderer = renderer_from_ctx(ctx)

    path = _EXPERIMENTS_DIR / f"{experiment_set_id}.json"
    if not path.exists():
        path = Path(experiment_set_id)
        if not path.exists():
            renderer.error(f"Experiment set not found: {experiment_set_id}", title="Not found")
            return ExitCode.ERROR_NOT_FOUND

    exp_set = load_experiment_set(path)

    all_runs = []
    for exp in exp_set.experiments.values():
        all_runs.extend(exp.runs)

    report = generate_failure_report(all_runs)

    renderer.print(f"\n  [bold]Failure Analysis[/]  ({report.total_failed} failed)\n")

    if not report.categories:
        renderer.print("  [green]No failures found.[/]")
        renderer.print()
        return ExitCode.SUCCESS

    total = len(all_runs)
    renderer.print("  [bold]Category Breakdown:[/]\n")
    for cat, count in sorted(report.categories.items(), key=lambda x: -x[1]):
        pct = report.category_percentages.get(cat, 0)
        renderer.print(f"    {cat:<30}  {count:>3}  ({pct:.1f}%)")

    if report.representative_examples:
        renderer.print("\n  [bold]Representative Examples:[/]\n")
        for ex in report.representative_examples[:3]:
            renderer.print(f"    [{ex.get('problem_id', '?')}] {ex.get('failure_category', '?')}")
            error = ex.get("error", "")[:80]
            if error:
                renderer.print(f"      Error: {error}")

    renderer.print()
    return ExitCode.SUCCESS


# ── evaluate calibration ──────────────────────────────────────────────


@evaluate.command(name="calibration")
@click.argument("experiment_set_id")
@click.pass_context
def evaluate_calibration(ctx, experiment_set_id):
    """Show planner calibration metrics from an experiment set."""
    from research.validation.tracker import load_experiment_set
    from research.validation.metrics import aggregate_research_metrics

    renderer = renderer_from_ctx(ctx)

    path = _EXPERIMENTS_DIR / f"{experiment_set_id}.json"
    if not path.exists():
        path = Path(experiment_set_id)
        if not path.exists():
            renderer.error(f"Experiment set not found: {experiment_set_id}", title="Not found")
            return ExitCode.ERROR_NOT_FOUND

    exp_set = load_experiment_set(path)

    has_calibration = any(
        r.calibration is not None for exp in exp_set.experiments.values() for r in exp.runs
    )

    renderer.print(f"\n  [bold]Planner Calibration — {exp_set.name}[/]\n")

    if not has_calibration:
        renderer.print("  [yellow]No calibration data in this experiment set.[/]")
        renderer.print()

        # Show what's available
        for h_val, exp in exp_set.experiments.items():
            rm = aggregate_research_metrics(exp.runs)
            conf = rm.get("planner_confidence", {})
            if conf.get("mean"):
                renderer.print(f"  {h_val}: Planner confidence mean={conf['mean']:.2f}")
        renderer.print()
        return ExitCode.SUCCESS

    renderer.print("  [bold]Calibration Data:[/]\n")
    renderer.print(f"  {'Run':<20} {'Predicted (min)':<20} {'Actual (min)':<20} {'Confidence':<15}")
    renderer.print(f"  {'-'*20} {'-'*20} {'-'*20} {'-'*15}")

    for h_val, exp in exp_set.experiments.items():
        for run in exp.runs:
            if run.calibration is None:
                continue
            c = run.calibration
            pred_min = c.predicted_duration_minutes or 0
            act_min = c.actual_duration_minutes or 0
            conf = c.planner_confidence or 0
            renderer.print(
                f"  {run.problem_id[:16]:<20} {pred_min:<20} {act_min:<20.1f} {conf:<15.2f}"
            )

    renderer.print()
    return ExitCode.SUCCESS


# ── helpers ───────────────────────────────────────────────────────────


def _load_problems() -> list[dict]:
    if not _BENCHMARK_PATH.exists():
        return []
    return json.loads(_BENCHMARK_PATH.read_text())

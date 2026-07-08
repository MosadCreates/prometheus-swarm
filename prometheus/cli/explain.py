from __future__ import annotations

import asyncio
import json
from pathlib import Path

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.command(name="explain")
@click.argument("job_id")
@click.option("--full", "-f", is_flag=True, help="Show full field values (no truncation)")
@click.pass_context
def explain(ctx, job_id, full):
    """Explain a job's decisions, history, and results.

    JOB_ID is the job UUID or its 8-character prefix.
    """
    renderer = renderer_from_ctx(ctx)
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    async def _fetch():
        from prometheus.core.redis import CliRedis

        redis = CliRedis()
        try:
            status = await redis.get_job_status(job_id)
            if not status:
                return None
            data = {"status": status}
            for key_suffix in (
                "meta",
                "mission_brief",
                "mission_spec",
                "engineering_plan",
                "training_complete",
            ):
                val = await redis._client.get(f"job:{status.get('job_id', job_id)}:{key_suffix}")
                data[key_suffix] = json.loads(val.decode()) if val else None
            return data
        finally:
            await redis.close()

    with Spinner("Loading job data..."):
        try:
            data = asyncio.run(_fetch())
        except Exception as e:
            renderer.error(str(e), title="Error loading job")
            return ExitCode.ERROR

    if not data or not data.get("status"):
        renderer.error(f"Job '{job_id}' not found.", hint="prometheus job list")
        return ExitCode.ERROR_NOT_FOUND

    status = data["status"]
    status_text = status.get("status", "unknown")
    job_id_full = status.get("job_id", job_id)

    # --- Overview ---
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold cyan")
    t.add_column()
    t.add_row("Job ID", job_id_full[:8] + ("..." if len(job_id_full) > 8 else ""))
    t.add_row(
        "Status",
        f"[{'green' if status_text in ('completed','COMPLETED','PASS') else 'red' if status_text in ('failed','escalated','ESCALATED') else 'yellow'}]{status_text}[/]",
    )
    t.add_row("Agent", status.get("current_agent") or "—")
    t.add_row("Crashes", str(status.get("crash_count", 0)))
    renderer.console.print(Panel(t, title="[bold]Job Status[/]"))

    # --- Mission Brief ---
    brief = data.get("mission_brief") or data.get("meta") or {}
    if brief:
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold cyan")
        t.add_column()
        desc = brief.get("problem_description", brief.get("description", "—"))
        if not full and len(desc) > 120:
            desc = desc[:120] + "..."
        t.add_row("Problem", desc)
        ds = brief.get("dataset", {})
        if ds:
            t.add_row("Dataset", ds.get("file_path", "—"))
            t.add_row("Rows", str(ds.get("num_rows", "—")))
            t.add_row("Columns", str(ds.get("num_columns", "—")))
        t.add_row("Task Type", brief.get("task_type", "—"))
        t.add_row("Modality", brief.get("modality", "—"))
        t.add_row("Metric", brief.get("evaluation_metric", "—"))
        renderer.console.print(Panel(t, title="[bold]Mission Brief[/]"))

    # --- Engineering Plan ---
    plan = data.get("engineering_plan", {})
    if plan:
        arch = plan.get("architecture_selected", {})
        if arch:
            t = Table.grid(padding=(0, 2))
            t.add_column(style="bold cyan")
            t.add_column()
            t.add_row("Architecture", arch.get("name", "—"))
            mr = arch.get("expected_metric_range")
            if mr:
                t.add_row("Expected Metric", f"[{mr[0]:.2f}, {mr[1]:.2f}]")
            t.add_row("Training Time", f"~{arch.get('expected_training_minutes', '?')} min")
            t.add_row("Peak RAM", f"~{arch.get('expected_ram_mb', '?')} MB")
            reason = arch.get("reason_for_selection", "")
            if not full and len(reason) > 120:
                reason = reason[:120] + "..."
            if reason:
                t.add_row("Why", reason)
            pipeline = plan.get("preprocessing_pipeline", [])
            if pipeline:
                steps = "; ".join(s.get("name", "?") for s in pipeline)
                t.add_row("Pipeline", steps)
            renderer.console.print(Panel(t, title="[bold]Engineering Plan[/]"))

    # --- Training ---
    training = data.get("training_complete", {})
    if training:
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold cyan")
        t.add_column()
        if training.get("best_val_metric") is not None:
            t.add_row("Best Metric", str(training["best_val_metric"]))
        if training.get("total_epochs") is not None:
            t.add_row("Epochs", str(training["total_epochs"]))
        t.add_row("Crashes", str(training.get("total_crashes", 0)))
        t.add_row("Recovered", str(training.get("crashes_recovered", 0)))
        renderer.console.print(Panel(t, title="[bold]Training Outcome[/]"))

    # --- Failures from patch_log ---
    _show_patch_summary(renderer, job_id_full, full)

    # --- Report hint ---
    outputs_dir = Path("outputs") / job_id_full
    report_md = outputs_dir / f"mission_report_{job_id_full}.md"
    if report_md.exists():
        renderer.print(f"\n  [dim]Full report:[/dim] {report_md}")
        renderer.print(f"  [dim]View with:[/dim] [bold]prometheus report {job_id[:8]}[/bold]")

    return ExitCode.SUCCESS


def _show_patch_summary(renderer, job_id: str, full: bool) -> None:
    """Read patch_log.jsonl and show a summary for this job_id."""
    from pathlib import Path

    log_path = Path("research") / "patch_log.jsonl"
    if not log_path.exists():
        return

    entries = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("job_id") == job_id or entry.get("job_id") == job_id[:8]:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return

    if not entries:
        return

    from rich.panel import Panel
    from rich.table import Table

    t = Table(box=None, padding=(0, 2))
    t.add_column("#", style="dim")
    t.add_column("Error")
    t.add_column("Category", style="cyan")
    t.add_column("Strategy", style="yellow")
    t.add_column("Outcome")
    for i, e in enumerate(entries, 1):
        outcome = e.get("patch_outcome", "?")
        outcome_style = (
            "green" if outcome == "success" else "red" if outcome in ("escalated",) else "yellow"
        )
        strategy = e.get("repair_strategy_used", e.get("repair_strategy", "?"))
        if not full and len(strategy) > 50:
            strategy = strategy[:50] + "..."
        t.add_row(
            str(i),
            e.get("exception_type", "?"),
            e.get("error_taxonomy_category", e.get("error_category", "?")),
            strategy,
            f"[{outcome_style}]{outcome}[/]",
        )
    renderer.console.print(Panel(t, title="[bold]Patch History[/]"))

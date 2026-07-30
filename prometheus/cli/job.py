from __future__ import annotations

import asyncio

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.tables import job_list_table, job_result_panel
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="job",
    aliases={"jb": "job", "ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def job():
    """Manage ML pipeline jobs."""


@job.command(name="submit")
@click.argument("dataset", type=click.Path(exists=True))
@click.option("--description", "-d", required=True, help="Natural-language problem description")
@click.option("--target-column", "-t", default=None, help="Name of the target column")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.pass_context
def job_submit(ctx, dataset, description, target_column, output_format):
    """Submit a dataset + problem description to the swarm."""
    from prometheus.cli.output import detect_format, emit_dict, Format

    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).jobs
    with Spinner("Submitting job..."):
        result = svc.submit(dataset, description, target_column)
    if result.status == "failed":
        renderer.error(result.reason or "Pipeline error", title="Job failed")
        return ExitCode.ERROR

    data = {
        "job_id": result.id,
        "status": result.status,
        "decision": result.decision,
        "reason": result.reason,
        "metrics": result.metrics,
        "endpoint_url": result.endpoint_url,
        "checkpoint_path": result.checkpoint_path,
    }
    if fmt in (Format.JSON, Format.PLAIN):
        emit_dict(ctx, fmt, data, schema="prometheus.job_submit.v1")
    else:
        renderer.console.print(job_result_panel(data))
    return ExitCode.SUCCESS


@job.command(name="list")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.pass_context
def job_list(ctx, output_format):
    """List all known jobs."""
    from prometheus.cli.output import detect_format, emit_str_table, Format

    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).jobs
    jobs = svc.list_jobs()
    if not jobs:
        if fmt != Format.JSON:
            renderer.print("[dim]No jobs found.[/dim]")
            renderer.print(
                "  [cyan]prometheus job submit data.csv[/cyan]  [dim]to submit your first job[/dim]"
            )
        else:
            emit_str_table(ctx, fmt, headers=[], rows=[], json_schema="prometheus.job_list.v1")
        return ExitCode.SUCCESS

    rows = [[j.id[:8], j.status, j.agent or "", str(j.crashes)] for j in jobs]
    headers = ["Job ID", "Status", "Agent", "Crashes"]
    emit_str_table(ctx, fmt, headers=headers, rows=rows, json_schema="prometheus.job_list.v1")
    return ExitCode.SUCCESS


@job.command(name="status")
@click.argument("job_id")
@click.option("--watch", is_flag=True, help="Refresh every second until the job finishes")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.pass_context
def job_status(ctx, job_id, watch, output_format):
    """Show the status of a single job."""
    from prometheus.cli.output import detect_format, emit_dict, Format

    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).jobs
    if not watch:
        s = svc.get_status(job_id)
        if s is None:
            renderer.error(f"Job '{job_id}' not found.", hint="prometheus job list")
            return ExitCode.ERROR_NOT_FOUND
        data = {"job_id": s.id, "status": s.status, "agent": s.agent, "crashes": s.crashes}
        if fmt in (Format.JSON, Format.PLAIN):
            emit_dict(ctx, fmt, data, schema="prometheus.job_status.v1")
        else:
            renderer.print(
                f"  Job [bold]{s.id}[/]  [{status_color(s.status)}]{s.status}[/]  agent={s.agent}  crashes={s.crashes}"
            )
        return ExitCode.SUCCESS

    renderer.print(f"[dim]Watching job {job_id[:8]}... Ctrl+C to stop[/dim]")
    try:
        while True:
            s = svc.get_status(job_id)
            if s:
                renderer.print(f"  {s.status:20s} agent={s.agent:15s} crashes={s.crashes}")
            import time

            time.sleep(1)
    except KeyboardInterrupt:
        renderer.print("\n[dim]Stopped watching.[/dim]")
    return ExitCode.SUCCESS


@job.command(name="cancel")
@click.argument("job_id")
@click.pass_context
def job_cancel(ctx, job_id):
    """Cancel a running job."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).jobs
    with Spinner("Cancelling job..."):
        ok = svc.cancel(job_id)
    if ok:
        detail = f"Job: {job_id[:8]}"
        renderer.success("Job cancelled.", detail=detail, hint="prometheus job list")
    else:
        renderer.error(f"Could not cancel job {job_id[:8]}.")
    return ExitCode.SUCCESS


@job.command(name="retry")
@click.argument("job_id")
@click.pass_context
def job_retry(ctx, job_id):
    """Retry a failed job."""
    renderer = renderer_from_ctx(ctx)
    renderer.print(f"  [dim italic]retry is planned for {Token.command}v0.2.0[/]")
    return ExitCode.SUCCESS


@job.command(name="logs")
@click.argument("job_id")
@click.option("--lines", "-n", default=50, type=int)
@click.pass_context
def job_logs(ctx, job_id, lines):
    """Show job execution logs."""
    renderer = renderer_from_ctx(ctx)
    try:
        from prometheus.core.redis import CliRedis
    except ImportError:
        renderer.print("[dim]No logs available.[/dim]")
        return ExitCode.SUCCESS

    async def _fetch():
        redis = CliRedis()
        try:
            s = await redis.get_job_status(job_id)
            return s
        finally:
            await redis.close()

    try:
        s = asyncio.run(_fetch())
        if s:
            renderer.print(f"  [bold]Job {s.get('job_id', job_id)[:8]}[/]")
            for k, v in s.items():
                renderer.print(f"  [{k}]  {v}")
        else:
            renderer.print("[dim]No log data for this job.[/dim]")
    except Exception as e:
        renderer.error(str(e), title="Error")
    return ExitCode.SUCCESS


def status_color(status: str) -> str:
    return {
        "completed": "green",
        "running": "cyan",
        "pending": "yellow",
        "failed": "red",
        "cancelled": "dim",
    }.get(status, "white")

from __future__ import annotations

from pathlib import Path

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="logs",
    aliases={"follow": "tail"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def logs():
    """View and manage Prometheus logs."""


@logs.command(name="tail")
@click.option("--lines", "-n", default=20, type=int, help="Number of lines")
@click.option("--agent", default=None, help="Filter by agent name")
@click.pass_context
def logs_tail(ctx, lines, agent):
    """Tail Prometheus log output."""
    renderer = renderer_from_ctx(ctx)
    log_dir = Path(_app(ctx).workspace.root) / "outputs" / "logs"
    if not log_dir.exists():
        renderer.print("[dim]No logs directory found. Run a job first to generate logs.[/dim]")
        return ExitCode.SUCCESS

    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    if agent:
        log_files = [f for f in log_files if agent.lower() in f.stem.lower()]

    if not log_files:
        msg = (
            f"[dim]No log files found for '{agent}'.[/dim]"
            if agent
            else "[dim]No log files found.[/dim]"
        )
        renderer.print(msg)
        return ExitCode.SUCCESS

    log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    log_file = log_files[0]
    content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(0, len(content) - lines)
    renderer.print(f"[dim]Showing last {lines} lines from {log_file.name}:[/dim]\n")
    for line in content[start:]:
        renderer.print(f"  [dim]{line}[/dim]")
    return ExitCode.SUCCESS


@logs.command(name="search")
@click.argument("pattern")
@click.option("--agent", default=None, help="Filter by agent name")
@click.pass_context
def logs_search(ctx, pattern, agent):
    """Search log entries for a pattern."""
    renderer = renderer_from_ctx(ctx)
    log_dir = Path(_app(ctx).workspace.root) / "outputs" / "logs"
    if not log_dir.exists():
        renderer.print("[dim]No logs directory found. Run a job first to generate logs.[/dim]")
        return ExitCode.SUCCESS

    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    if agent:
        log_files = [f for f in log_files if agent.lower() in f.stem.lower()]

    if not log_files:
        renderer.print("[dim]No log files found.[/dim]")
        return ExitCode.SUCCESS

    with Spinner(f"Searching for '{pattern}' in {len(log_files)} files..."):
        matches: list[tuple[str, int, str]] = []
        for f in log_files:
            for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if pattern.lower() in line.lower():
                    matches.append((f.name, i, line))

    if not matches:
        renderer.print(f"[dim]No matches for '{pattern}'.[/dim]")
        return ExitCode.SUCCESS

    for fname, lineno, line in matches:
        renderer.print(f"  [dim]{fname}:{lineno}[/] {line.strip()}")
    n = len(matches)
    renderer.print(f"\n[dim]{n} matching entr{'y' if n == 1 else 'ies'}[/dim]")
    return ExitCode.SUCCESS

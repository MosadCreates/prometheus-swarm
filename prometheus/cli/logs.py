from __future__ import annotations

import json
from pathlib import Path

import click

from prometheus.cli.output import detect_format, Format
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
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.pass_context
def logs_tail(ctx, lines, agent, output_format):
    """Tail Prometheus log output."""
    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)
    log_dir = Path(_app(ctx).workspace.root) / "outputs" / "logs"
    if not log_dir.exists():
        if fmt == Format.JSON:
            print(json.dumps({"schema": "prometheus.logs_tail.v1", "lines": [], "file": ""}))
        else:
            renderer.print("[dim]No logs directory found. Run a job first to generate logs.[/dim]")
        return ExitCode.SUCCESS

    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    if agent:
        log_files = [f for f in log_files if agent.lower() in f.stem.lower()]

    if not log_files:
        if fmt == Format.JSON:
            print(json.dumps({"schema": "prometheus.logs_tail.v1", "lines": [], "file": ""}))
        else:
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
    tail_lines = content[start:]

    match fmt:
        case Format.JSON:
            print(
                json.dumps(
                    {
                        "schema": "prometheus.logs_tail.v1",
                        "file": log_file.name,
                        "lines": tail_lines,
                    },
                    indent=2,
                )
            )
        case Format.PLAIN:
            for line in tail_lines:
                print(line)
        case Format.INTERACTIVE:
            renderer.print(f"[dim]Showing last {lines} lines from {log_file.name}:[/dim]\n")
            for line in tail_lines:
                renderer.print(f"  [dim]{line}[/dim]")
    return ExitCode.SUCCESS


@logs.command(name="search")
@click.argument("pattern")
@click.option("--agent", default=None, help="Filter by agent name")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.pass_context
def logs_search(ctx, pattern, agent, output_format):
    """Search log entries for a pattern."""
    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)
    renderer = renderer_from_ctx(ctx)
    log_dir = Path(_app(ctx).workspace.root) / "outputs" / "logs"
    if not log_dir.exists():
        if fmt == Format.JSON:
            print(json.dumps({"schema": "prometheus.logs_search.v1", "matches": []}))
        else:
            renderer.print("[dim]No logs directory found. Run a job first to generate logs.[/dim]")
        return ExitCode.SUCCESS

    log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
    if agent:
        log_files = [f for f in log_files if agent.lower() in f.stem.lower()]

    if not log_files:
        if fmt == Format.JSON:
            print(json.dumps({"schema": "prometheus.logs_search.v1", "matches": []}))
        else:
            renderer.print("[dim]No log files found.[/dim]")
        return ExitCode.SUCCESS

    with Spinner(f"Searching for '{pattern}' in {len(log_files)} files..."):
        matches: list[dict] = []
        for f in log_files:
            for i, line in enumerate(
                f.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                if pattern.lower() in line.lower():
                    matches.append({"file": f.name, "line": i, "content": line.strip()})

    if not matches:
        if fmt == Format.JSON:
            print(
                json.dumps(
                    {"schema": "prometheus.logs_search.v1", "matches": [], "pattern": pattern}
                )
            )
        else:
            renderer.print(f"[dim]No matches for '{pattern}'.[/dim]")
        return ExitCode.SUCCESS

    match fmt:
        case Format.JSON:
            print(
                json.dumps(
                    {
                        "schema": "prometheus.logs_search.v1",
                        "pattern": pattern,
                        "count": len(matches),
                        "matches": matches,
                    },
                    indent=2,
                )
            )
        case Format.PLAIN:
            for m in matches:
                print(f"{m['file']}:{m['line']}  {m['content']}")
            print(f"\n{len(matches)} matching entr{'y' if len(matches) == 1 else 'ies'}")
        case Format.INTERACTIVE:
            for m in matches:
                renderer.print(f"  [dim]{m['file']}:{m['line']}[/] {m['content']}")
            n = len(matches)
            renderer.print(f"\n[dim]{n} matching entr{'y' if n == 1 else 'ies'}[/dim]")
    return ExitCode.SUCCESS

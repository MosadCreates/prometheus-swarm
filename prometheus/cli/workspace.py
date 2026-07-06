from __future__ import annotations

import os
import subprocess
import sys

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="workspace",
    aliases={"ws": "workspace", "ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def workspace():
    """Manage workspace and project files."""


@workspace.command(name="info")
@click.pass_context
def workspace_info(ctx):
    """Show workspace metadata and structure."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).workspace
    info = svc.get_info()
    items = [
        ("Name", info.name),
        ("Root", info.root),
        ("Version", info.version or "\u2014"),
        (".env", "\u2713" if info.has_env else "\u2717"),
        ("Docker", "\u2713" if info.has_docker else "\u2717"),
        ("Files", str(info.files)),
        ("Agents", str(info.agents)),
    ]
    renderer.status(items)
    return ExitCode.SUCCESS


@workspace.command(name="status")
@click.pass_context
def workspace_status(ctx):
    """Show workspace health checks."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).workspace
    msg = svc.status()
    renderer.status([("Workspace", msg)])
    return ExitCode.SUCCESS


@workspace.command(name="scan")
@click.pass_context
def workspace_scan(ctx):
    """Scan workspace files and structure."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).workspace
    with Spinner("Scanning workspace..."):
        result = svc.scan()
    items = [
        ("Total files", str(result.total_files)),
        ("Directories", str(result.directories)),
        ("Supported files", str(result.supported_files)),
        ("Size", f"{result.size_kb} KB"),
    ]
    renderer.status(items)
    return ExitCode.SUCCESS


@workspace.command(name="tree")
@click.option("--depth", "-d", default=2, type=int, help="Directory depth")
@click.pass_context
def workspace_tree(ctx, depth):
    """Show workspace directory tree."""
    renderer = renderer_from_ctx(ctx)
    from pathlib import Path

    root = _app(ctx).workspace.root
    lines = _build_tree(Path(root), depth=depth, prefix="")
    for line in lines:
        renderer.print(f"  [dim]{line}[/dim]")
    return ExitCode.SUCCESS


@workspace.command(name="open")
@click.pass_context
def workspace_open(ctx):
    """Open workspace in file manager."""
    renderer = renderer_from_ctx(ctx)
    root = _app(ctx).workspace.root
    try:
        if os.name == "nt":
            os.startfile(root)
        elif sys.platform == "darwin":
            subprocess.run(["open", root], check=True)
        else:
            subprocess.run(["xdg-open", root], check=True)
        renderer.success(f"Workspace at {root}")
    except Exception as e:
        renderer.error(str(e), hint=f"cd {root}")
        return ExitCode.ERROR
    return ExitCode.SUCCESS


def _build_tree(path, depth, prefix):
    if depth <= 0:
        return [f"{prefix}\u2514\u2500\u2500 ..."]
    entries = sorted(
        [p for p in path.iterdir() if not p.name.startswith(".")],
        key=lambda p: (not p.is_dir(), p.name.lower()),
    )
    lines = []
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
        next_prefix = prefix + ("    " if is_last else "\u2502   ")
        label = f"{entry.name}/" if entry.is_dir() else entry.name
        lines.append(f"{prefix}{connector}{label}")
        if entry.is_dir():
            lines.extend(_build_tree(entry, depth=depth - 1, prefix=next_prefix))
    return lines

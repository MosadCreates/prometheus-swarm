from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


_WORKSPACE_DIR = ".prometheus"


@click.group(
    cls=AliasedGroup,
    name="workspace",
    aliases={"ws": "workspace"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def workspace():
    """Manage workspace directories and project environments."""


@workspace.command(name="init")
@click.argument("path", default=".")
@click.option("--reset", is_flag=True, default=False, help="Re-initialize an existing workspace")
@click.pass_context
def workspace_init(ctx, path: str, reset: bool):
    """Mark a directory as a Prometheus workspace.

    Creates the .prometheus/ skeleton and configures the project root.
    """
    renderer = renderer_from_ctx(ctx)
    target = Path(path).resolve()

    if not target.exists():
        renderer.print(f"Creating directory [bold]{target}[/]...")
        target.mkdir(parents=True, exist_ok=True)

    ws_dir = target / _WORKSPACE_DIR
    if ws_dir.exists():
        if not reset:
            renderer.error(
                f"Workspace already exists at {target}",
                hint="Use --reset to re-initialize",
            )
            return ExitCode.ERROR
        renderer.print(f"Re-initializing workspace at [bold]{target}[/]...")
    else:
        renderer.print(f"Initializing workspace at [bold]{target}[/]...")

    ws_dir.mkdir(parents=True, exist_ok=True)
    (ws_dir / "config.toml").write_text("# Prometheus workspace configuration\n")
    (ws_dir / "missions").mkdir(exist_ok=True)
    (ws_dir / "models").mkdir(exist_ok=True)

    os.chdir(str(target))
    renderer.success(f"Workspace initialized at {target}")
    return ExitCode.SUCCESS


@workspace.command(name="list")
@click.pass_context
def workspace_list(ctx):
    """List known workspace directories."""
    renderer = renderer_from_ctx(ctx)
    cfg = _app(ctx).config

    known = cfg.get("workspaces", [])
    if not known:
        renderer.empty('No workspaces configured. Use "prometheus workspace init" to create one.')
        return ExitCode.SUCCESS

    current = cfg.get("current_workspace")
    rows = []
    for w in known:
        label = w
        if w == current:
            label = f"{w}  [{Token.accent}active[/]"
        rows.append([label])

    renderer.table(["Workspace"], rows)
    return ExitCode.SUCCESS


@workspace.command(name="use")
@click.argument("name")
@click.pass_context
def workspace_use(ctx, name: str):
    """Switch the active workspace by name or path."""
    renderer = renderer_from_ctx(ctx)
    cfg = _app(ctx).config

    known = cfg.get("workspaces", [])
    target = Path(name).resolve()
    target_str = str(target)

    if target_str not in known:
        renderer.error(
            f"Workspace '{name}' not in known list",
            hint="prometheus workspace list",
        )
        return ExitCode.ERROR

    cfg.set("current_workspace", target_str)
    os.chdir(target_str)
    renderer.success(f"Switched to workspace {target_str}")
    return ExitCode.SUCCESS

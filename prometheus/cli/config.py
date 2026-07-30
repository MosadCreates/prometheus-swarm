from __future__ import annotations

import os
import subprocess

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.tables import config_check_table
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="config",
    aliases={"cfg": "config"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def config():
    """Manage .env configuration."""


@config.command(name="list")
@click.pass_context
def config_list(ctx):
    """Show current .env configuration."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    env = svc.show()
    if not env:
        renderer.print(
            "[dim]No .env configuration found. Run [cyan]prometheus config set KEY VALUE[/cyan] to add variables.[/dim]"
        )
        return ExitCode.SUCCESS

    items = []
    for k, v in env.items():
        display = "***" if "KEY" in k.upper() or "PASSWORD" in k.upper() else v
        items.append((k, display))
    renderer.status(items, title="Configuration")
    return ExitCode.SUCCESS


@config.command(name="set")
@click.argument("key")
@click.argument("value")
@click.pass_context
def config_set(ctx, key, value):
    """Set a KEY VALUE pair in .env."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    svc.set_key(key, value)
    display = "***" if "KEY" in key.upper() or "PASSWORD" in key.upper() else value
    detail = f"{key}={display}"
    renderer.success("Configuration updated.", detail=detail, hint="prometheus config list")
    return ExitCode.SUCCESS


@config.command(name="get")
@click.argument("key")
@click.pass_context
def config_get(ctx, key):
    """Get a single configuration value by key."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    env = svc.show()
    if key in env:
        display = "***" if "KEY" in key.upper() or "PASSWORD" in key.upper() else env[key]
        renderer.print(f"  {key}={display}")
        return ExitCode.SUCCESS
    else:
        renderer.error(f"Key '{key}' not found in configuration.", hint="prometheus config list")
        return ExitCode.ERROR_NOT_FOUND


@config.command(name="check")
@click.pass_context
def config_check(ctx):
    """Validate all prerequisites."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    results = svc.check_prerequisites()
    renderer.console.print(config_check_table(results))
    if any(not r["ok"] for r in results):
        return ExitCode.ERROR_CONFIG
    return ExitCode.SUCCESS


@config.command(name="edit")
@click.pass_context
def config_edit(ctx):
    """Open .env in the default editor."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    env_path = svc.root / ".env"
    if not env_path.exists():
        env_path.write_text("# Prometheus Configuration\n")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if editor:
        subprocess.run([editor, str(env_path)], check=False)
    else:
        os.startfile(str(env_path))
    renderer.success("Configuration opened.", detail=f"Path: {env_path}")
    return ExitCode.SUCCESS

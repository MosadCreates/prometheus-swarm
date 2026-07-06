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


@config.command(name="show")
@click.pass_context
def config_show(ctx):
    """Show current .env configuration."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    env = svc.show()
    if not env:
        renderer.print(
            "[dim]No .env configuration found. Run [cyan]prometheus config set KEY=VALUE[/cyan] to add variables.[/dim]"
        )
        return ExitCode.SUCCESS

    items = []
    for k, v in env.items():
        display = "***" if "KEY" in k.upper() or "PASSWORD" in k.upper() else v
        items.append((k, display))
    renderer.status(items, title="Configuration")
    return ExitCode.SUCCESS


@config.command(name="set")
@click.argument("pairs", nargs=-1)
@click.pass_context
def config_set(ctx, pairs):
    """Set one or more KEY=VALUE pairs in .env."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).config
    for pair in pairs:
        if "=" not in pair:
            renderer.error(f"'{pair}' has no '=' separator.", hint="KEY=VALUE")
            continue
        key, _, value = pair.partition("=")
        svc.set_key(key, value)
        display = "***" if "KEY" in key.upper() or "PASSWORD" in key.upper() else value
        detail = f"{key}={display}"
        renderer.success("Configuration updated.", detail=detail, hint="prometheus config show")
    return ExitCode.SUCCESS


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

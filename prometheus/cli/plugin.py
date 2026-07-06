from __future__ import annotations

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="plugin",
    aliases={"plugins": "plugin"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def plugin():
    """Manage plugins."""


@plugin.command(name="list")
@click.pass_context
def plugin_list(ctx):
    """List all registered plugins."""
    renderer = renderer_from_ctx(ctx)
    registry = _app(ctx).plugins
    plugins = registry.list()
    if not plugins:
        renderer.print("[dim]No plugins registered.[/dim]")
        return ExitCode.SUCCESS
    for p in plugins:
        renderer.print(f"  [bold]{p.name}[/]  [dim]v{p.version}[/dim]")
    n = len(plugins)
    renderer.print(f"\n[dim]{n} plugin(s) registered[/dim]")
    return ExitCode.SUCCESS


@plugin.command(name="inspect")
@click.argument("name")
@click.pass_context
def plugin_inspect(ctx, name):
    """Inspect a specific plugin."""
    renderer = renderer_from_ctx(ctx)
    registry = _app(ctx).plugins
    p = registry.get(name)
    if p is None:
        renderer.error(f"Plugin '{name}' not found.", hint="prometheus plugin list")
        return ExitCode.SUCCESS
    renderer.print(f"  [bold]{p.name}[/]  v{p.version}")
    renderer.print(f"  [dim]{p.__class__.__module__}[/dim]")
    return ExitCode.SUCCESS

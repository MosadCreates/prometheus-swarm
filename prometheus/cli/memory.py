from __future__ import annotations

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="memory",
    aliases={"mem": "memory"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def memory():
    """Manage Prometheus memory and vector stores."""


@memory.command(name="stats")
@click.pass_context
def memory_stats(ctx):
    """Show memory store statistics."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).memory
    with Spinner("Reading memory stats..."):
        stats = svc.stats()
    items: list[tuple[str, str]] = []
    chroma = stats.get("chroma", {})
    redis = stats.get("redis", {})
    if isinstance(chroma, dict):
        for k, v in chroma.items():
            items.append((f"Chroma: {k}", str(v)))
    if isinstance(redis, dict):
        for k, v in redis.items():
            items.append((f"Redis: {k}", str(v)))
    if not items:
        items.append(("Status", "No memory backends available"))
    renderer.status(items)
    return ExitCode.SUCCESS


@memory.command(name="search")
@click.argument("query")
@click.option("--limit", "-n", default=10, type=int, help="Max results")
@click.pass_context
def memory_search(ctx, query, limit):
    """Search the memory store."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).memory
    results = svc.search(query, limit=limit)
    if not results:
        renderer.print(f"[dim]No results for '{query}'.[/dim]")
        return ExitCode.SUCCESS
    for r in results:
        if isinstance(r, dict):
            renderer.print(f"  [bold]{r.get('id', '?')}[/]  [dim]{r.get('text', '')[:100]}[/dim]")
        else:
            renderer.print(f"  [dim]{r}[/dim]")
    n = len(results)
    renderer.print(f"\n[dim]{n} matching entr{'y' if n == 1 else 'ies'}[/dim]")
    return ExitCode.SUCCESS

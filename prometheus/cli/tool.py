from __future__ import annotations

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="tool",
    aliases={"ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def tool():
    """Manage agent tools."""


@tool.command(name="list")
@click.option("--agent", default=None, help="Filter by agent name")
@click.pass_context
def tool_list(ctx, agent):
    """List all registered tools across agents."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    agents = svc.list_agents()
    found = False
    for a in agents:
        if agent and a.name != agent.lower():
            continue
        detail = svc.inspect_agent(a.name)
        if detail and detail.tools:
            found = True
            renderer.print(
                f"\n  [bold]{a.name}[/] [{Token.secondary}]{a.display_name}[/] [{Token.status_text}]({len(detail.tools)} tools)[/]"
            )
            for t in detail.tools:
                renderer.print(f"    \u2514\u2500 [dim]{t}[/dim]")
    if not found:
        if agent:
            renderer.print(f"[dim]No tools found for agent '{agent}'.[/dim]")
        else:
            renderer.print("[dim]No tools registered across any agent.[/dim]")
    return ExitCode.SUCCESS


@tool.command(name="inspect")
@click.argument("tool_path")
@click.pass_context
def tool_inspect(ctx, tool_path):
    """Inspect a specific tool."""
    renderer = renderer_from_ctx(ctx)
    parts = tool_path.split(".")
    if len(parts) < 2:
        renderer.print("[red]Use format: <agent>.<tool_name>[/red]")
        return ExitCode.ERROR_VALIDATION
    agent_name = parts[0]
    tool_name = ".".join(parts[1:])
    svc = _app(ctx).agents
    detail = svc.inspect_agent(agent_name)
    if detail is None:
        renderer.print(f"[red]Agent '{agent_name}' not found.[/red]")
        return ExitCode.ERROR_NOT_FOUND
    matches = [t for t in detail.tools if tool_name in t]
    if matches:
        for m in matches:
            renderer.print(f"  [bold]{m}[/]")
    else:
        renderer.print(f"[dim]No tool matching '{tool_name}' in agent '{agent_name}'.[/dim]")
    return ExitCode.SUCCESS

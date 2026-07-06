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
    name="agent",
    aliases={"ag": "agent", "ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def agent():
    """Manage AI agents in the swarm."""


@agent.command(name="list")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed info")
@click.pass_context
def agent_list(ctx, verbose):
    """List all registered agents with their status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    agents = svc.list_agents()
    if not agents:
        renderer.print("[dim]No agents registered.[/dim]")
        return ExitCode.SUCCESS

    if verbose:
        rows = [[a.name, a.display_name, str(a.tools), a.version] for a in agents]
        renderer.table(["Name", "Display", "Tools", "Version"], rows)
    else:
        rows = [[a.name, a.display_name] for a in agents]
        renderer.table(["Name", "Display"], rows)
    label = f"{len(agents)} agent(s) registered"
    renderer.print(f"  [dim]{label}[/dim]")
    return ExitCode.SUCCESS


@agent.command(name="inspect")
@click.argument("agent_name")
@click.pass_context
def agent_inspect(ctx, agent_name):
    """Inspect a specific agent in detail."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    detail = svc.inspect_agent(agent_name)
    if detail is None:
        renderer.error(f"Agent '{agent_name}' not found.", hint="prometheus agent list")
        return ExitCode.ERROR_NOT_FOUND

    items = [
        ("Name", detail.name),
        ("Display", detail.display_name),
        ("Role", detail.role),
        ("Status", detail.status),
        ("Version", detail.version),
        ("Tools", str(len(detail.tools))),
    ]
    if detail.capabilities:
        items.append(("Capabilities", ", ".join(detail.capabilities)))

    renderer.status(items, title=f"Agent: {detail.name}")
    return ExitCode.SUCCESS


@agent.command(name="logs")
@click.argument("agent_name")
@click.option("--lines", "-n", default=20, type=int)
@click.pass_context
def agent_logs(ctx, agent_name, lines):
    """Show agent execution logs."""
    renderer = renderer_from_ctx(ctx)
    renderer.print(f"[dim]Logs for {agent_name} ({lines} lines):[/dim]")
    try:
        log_path = _app(ctx).agents.root / agent_name / "agent.py"
        if log_path.exists():
            content = log_path.read_text().splitlines()
            start = max(0, len(content) - lines)
            for line in content[start:]:
                renderer.print(f"  [dim]{line}[/dim]")
        else:
            renderer.print(f"  [dim](no log data for {agent_name})[/dim]")
    except Exception:
        renderer.print(f"  [dim](no log data for {agent_name})[/dim]")
    return ExitCode.SUCCESS


@agent.command(name="metrics")
@click.pass_context
def agent_metrics(ctx):
    """Show agent performance metrics."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).agents
    agents = svc.list_agents()
    if not agents:
        renderer.print("[dim]No agent metrics available.[/dim]")
        return ExitCode.SUCCESS
    items = [(a.name, f"{a.tools} tools, v{a.version}") for a in agents]
    renderer.status(items)
    return ExitCode.SUCCESS

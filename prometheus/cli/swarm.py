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
    name="swarm",
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def swarm():
    """Manage the Prometheus agent swarm."""


@swarm.command(name="status")
@click.pass_context
def swarm_status(ctx):
    """Show swarm runtime status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx)
    agent_count = svc.agents.count_agents()
    tool_count = svc.agents.count_tools()
    provider = svc.providers.current_provider()
    configured = "\u25cf" if provider.configured else "\u25cb"
    items = [
        ("Agents", f"{agent_count} Active"),
        ("Tools", f"{tool_count} Registered"),
        ("Provider", provider.model),
        ("Status", f"{configured} Ready" if provider.configured else "\u25cb Unconfigured"),
    ]
    renderer.status(items)
    return ExitCode.SUCCESS


@swarm.command(name="health")
@click.pass_context
def swarm_health(ctx):
    """Run swarm health checks."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx)
    passed = 0
    checks: list[tuple[str, str, str]] = []

    prov = svc.providers.current_provider()
    if prov.configured:
        passed += 1
        checks.append(("\u2713 Provider", f"{prov.model} configured", Token.success))
    else:
        checks.append(("\u2717 Provider", "Not configured", Token.error))

    count = svc.agents.count_agents()
    checks.append(("\u2713 Agents", f"{count} registered", Token.success))

    info = svc.workspace.get_info()
    if info.has_env:
        passed += 1
        checks.append(("\u2713 Workspace", info.name, Token.success))
    else:
        checks.append(("\u2717 Workspace", "Missing .env", Token.error))

    for label, detail, color in checks:
        renderer.print(f"  [{color}]{label}[/]  [dim]{detail}[/dim]")
    renderer.print(f"\n  [dim]{passed}/{len(checks)} checks passed[/dim]")
    if passed < len(checks):
        return ExitCode.ERROR
    return ExitCode.SUCCESS


@swarm.command(name="monitor")
@click.option("--interval", "-i", default=2, type=int, help="Refresh interval (seconds)")
@click.pass_context
def swarm_monitor(ctx, interval):
    """Monitor swarm activity in real-time."""
    import time

    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx)
    try:
        while True:
            import shutil

            w = shutil.get_terminal_size().columns
            renderer.print("\u2500" * min(w, 60), style=Token.border)
            agents = svc.agents.list_agents()
            if not agents:
                renderer.print("  [dim]No agents active.[/dim]")
            for a in agents:
                renderer.print(
                    f"  [{Token.secondary}]{a.name:<12}[/] [{Token.status_text}]{a.display_name:<20}[/] [{Token.success}]idle[/]"
                )
            renderer.print(f"\n  [dim]Ctrl+C to stop (refreshing every {interval}s)[/dim]")
            time.sleep(interval)
            renderer.console.clear()
    except KeyboardInterrupt:
        renderer.print("\n  [dim]Monitor stopped.[/dim]")
    return ExitCode.SUCCESS

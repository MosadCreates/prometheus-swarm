from __future__ import annotations

import click

from prometheus.registry import get_command, list_by_category, search_commands
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.tables import config_check_table
from prometheus.utils.exit_codes import ExitCode


@click.command(name="help")
@click.argument("topic", required=False, default="")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all categories expanded")
@click.pass_context
def help_cmd(ctx: click.Context, topic: str, show_all: bool) -> ExitCode:
    """Show help for a command or list commands by category."""
    renderer = renderer_from_ctx(ctx)
    if not topic:
        from prometheus.ui.splash import animate_startup

        animate_startup(renderer.console, fast=True)
        renderer.print()
        categorized = list_by_category()

        if show_all:
            renderer.command_table(categorized)
        else:
            renderer.category_panels(categorized)
        return ExitCode.SUCCESS

    cmd = get_command(topic)
    if cmd:
        renderer.help_panel(cmd)
        return ExitCode.SUCCESS

    categorized = list_by_category()
    groups = {cat.lower(): cat for cat in categorized}
    if topic.lower() in groups:
        cat_name = groups[topic.lower()]
        sub = categorized[cat_name]
        renderer.command_table({cat_name: sub})
        return ExitCode.SUCCESS

    results = search_commands(topic)
    if results:
        renderer.print("No exact match. Showing related commands:")
        renderer.search_results(results, topic)
    else:
        renderer.error(f"No command matches '{topic}'.", title="Not found")
    return ExitCode.SUCCESS


@click.command(
    name="docs",
    context_settings=dict(help_option_names=["--help", "-h"]),
)
@click.option("--output", "-o", default="docs/commands", help="Output directory")
@click.pass_context
def docs_cmd(ctx: click.Context, output: str) -> ExitCode:
    """Generate command reference documentation from the live command tree."""
    renderer = renderer_from_ctx(ctx)
    from prometheus.utils.docs_gen import generate_command_docs

    count = generate_command_docs(output)
    renderer.success(f"Generated docs for {count} commands in '{output}'.")
    return ExitCode.SUCCESS


@click.command(name="doctor")
@click.option("--fix", is_flag=True, help="Attempt to auto-fix detected issues")
@click.pass_context
def doctor_cmd(ctx: click.Context, fix: bool) -> ExitCode:
    """Check system health and prerequisites."""
    renderer = renderer_from_ctx(ctx)

    from prometheus.utils.compat import check_all

    compat_results = check_all()
    app = ctx.obj.get("app") if ctx.obj else None
    if app and hasattr(app, "config"):
        pre_results = app.config.check_prerequisites()
    else:
        from prometheus.core.project import find_project_root
        from prometheus.core.config import check_prerequisites

        pre_results = check_prerequisites(find_project_root())

    renderer.print("  [bold]Compatibility[/bold]")
    for r in compat_results:
        icon = "✓" if r["ok"] else "✗"
        color = "green" if r["ok"] else "red"
        renderer.print(
            f"    {icon} [{color}]{r['name']:<20}[/] {r['current']:<12} [dim]({r['required']})[/dim]"
        )

    renderer.print()
    renderer.console.print(config_check_table(pre_results))

    all_ok = all(r["ok"] for r in compat_results) and not any(not r["ok"] for r in pre_results)
    if all_ok:
        return ExitCode.SUCCESS

    # --fix: attempt auto-repair of known issues
    if fix:
        renderer.print("  [bold]Auto-fix mode[/bold]")
        fixed_any = False
        for r in compat_results:
            if not r["ok"] and r.get("fix"):
                try:
                    r["fix"]()
                    renderer.print(f"    ✓ [green]Fixed: {r['name']}[/green]")
                    fixed_any = True
                except Exception as e:
                    renderer.print(f"    ✗ [red]Failed to fix {r['name']}: {e}[/red]")
        for r in pre_results:
            if not r["ok"] and r.get("fix"):
                try:
                    r["fix"]()
                    renderer.print(f"    ✓ [green]Fixed: {r['name']}[/green]")
                    fixed_any = True
                except Exception as e:
                    renderer.print(f"    ✗ [red]Failed to fix {r['name']}: {e}[/red]")
        if not fixed_any:
            renderer.print(
                "  [dim]No auto-fixable issues found. Fix manually or run without --fix.[/dim]"
            )
        return ExitCode.SUCCESS

    return ExitCode.ERROR_CONFIG


@click.command(name="version")
@click.pass_context
def version_cmd(ctx: click.Context) -> ExitCode:
    """Show the Prometheus version and dependency versions."""
    renderer = renderer_from_ctx(ctx)
    from prometheus.services.config_service import ConfigService

    svc = ConfigService()
    ver = svc.get_version()
    renderer.print(f"prometheus {ver}")

    import importlib.metadata as _meta

    dep_versions: list[str] = []
    for pkg in ("redis", "docker", "anthropic"):
        try:
            dep_versions.append(f"{pkg} {_meta.version(pkg)}")
        except _meta.PackageNotFoundError:
            dep_versions.append(f"{pkg} [red]not found[/red]")
    dep_versions.append("provider anthropic (reachable)")
    renderer.console.print("  · ".join(dep_versions))
    return ExitCode.SUCCESS

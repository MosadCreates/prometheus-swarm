from __future__ import annotations

import click

from prometheus.registry import get_command, list_by_category, search_commands
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.tables import config_check_table
from prometheus.ui.styles import Token
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

        animate_startup(renderer.console)
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


@click.command(name="commands")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show full table instead of panels")
@click.option("--category", "-c", default=None, help="Filter by category")
@click.pass_context
def commands_cmd(ctx: click.Context, show_all: bool, category: str) -> ExitCode:
    """List all available commands by category."""
    renderer = renderer_from_ctx(ctx)
    categorized = list_by_category()

    if category:
        cat_name = None
        for c in categorized:
            if c.lower() == category.lower():
                cat_name = c
                break
        if cat_name:
            renderer.command_table({cat_name: categorized[cat_name]})
        else:
            renderer.error(f"Category '{category}' not found.", hint="prometheus help")
        return ExitCode.SUCCESS

    if show_all:
        renderer.command_table(categorized)
    else:
        renderer.category_panels(categorized)
    return ExitCode.SUCCESS


@click.command(name="search")
@click.argument("query")
@click.option("--all", "-a", "show_all", is_flag=True, help="Show all matches without limit")
@click.pass_context
def search_cmd(ctx: click.Context, query: str, show_all: bool) -> ExitCode:
    """Search commands by name, description, or keyword."""
    renderer = renderer_from_ctx(ctx)
    limit = None if show_all else 10
    results = search_commands(query, limit=limit)
    if not results:
        renderer.error(f"No commands match '{query}'.", title="No results")
        return ExitCode.SUCCESS
    renderer.search_results(results, query)
    return ExitCode.SUCCESS


@click.command(name="doctor")
@click.pass_context
def doctor_cmd(ctx: click.Context) -> ExitCode:
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
        icon = "\u2713" if r["ok"] else "\u2717"
        color = "green" if r["ok"] else "red"
        renderer.print(
            f"    {icon} [{color}]{r['name']:<20}[/] {r['current']:<12} [dim]({r['required']})[/dim]"
        )

    renderer.print()
    renderer.console.print(config_check_table(pre_results))

    all_ok = all(r["ok"] for r in compat_results) and not any(not r["ok"] for r in pre_results)
    if not all_ok:
        return ExitCode.ERROR_CONFIG
    return ExitCode.SUCCESS


@click.command(name="version")
@click.pass_context
def version_cmd(ctx: click.Context) -> ExitCode:
    """Show the Prometheus version."""
    renderer = renderer_from_ctx(ctx)
    from prometheus.services.config_service import ConfigService

    svc = ConfigService()
    ver = svc.get_version()
    name = svc.get_workspace_name()
    renderer.print(f"[bold]{name}[/] [dim]v{ver}[/dim]")
    return ExitCode.SUCCESS


@click.command(name="cheatsheet")
@click.argument("section", required=False, default="")
@click.pass_context
def cheatsheet_cmd(ctx: click.Context, section: str) -> ExitCode:
    """Show a quick-reference cheatsheet."""
    renderer = renderer_from_ctx(ctx)
    if section:
        renderer.console.print(_section_cheatsheet(section))
    else:
        renderer.console.print(_full_cheatsheet())
    return ExitCode.SUCCESS


@click.command(name="docs")
@click.option("--output", "-o", default="docs/commands", help="Output directory")
@click.pass_context
def docs_cmd(ctx: click.Context, output: str) -> ExitCode:
    """Generate command reference documentation."""
    renderer = renderer_from_ctx(ctx)
    from prometheus.utils.docs_gen import generate_command_docs

    count = generate_command_docs(output)
    renderer.success(f"Generated docs for {count} commands in '{output}'.")
    return ExitCode.SUCCESS


@click.command(name="diagnostics")
@click.pass_context
def diagnostics_cmd(ctx: click.Context) -> ExitCode:
    """Show command diagnostics and telemetry."""
    renderer = renderer_from_ctx(ctx)
    from prometheus.utils.telemetry import get_diagnostics

    diag = get_diagnostics()
    if diag["total_commands"] == 0:
        renderer.print("[dim]No diagnostics data yet.[/dim]")
        return ExitCode.SUCCESS
    items: list[tuple[str, str]] = [
        ("Total Commands", str(diag["total_commands"])),
        ("Successful", str(diag["successful"])),
        ("Failed", str(diag["failed"])),
        ("Avg Duration", f"{diag['avg_duration_ms']}ms"),
        ("Min Duration", f"{diag['min_duration_ms']}ms"),
        ("Max Duration", f"{diag['max_duration_ms']}ms"),
        ("P50 Duration", f"{diag['p50_duration_ms']}ms"),
        ("P95 Duration", f"{diag['p95_duration_ms']}ms"),
    ]
    renderer.status(items, title="Diagnostics")
    return ExitCode.SUCCESS


def _full_cheatsheet():
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    cheat = Table.grid(padding=(0, 4))
    cheat.add_column()
    cheat.add_column()

    left = Text()
    left.append("[bold]Getting Started[/bold]\n", style=Token.heading)
    left.append("  \u2713 Install & verify\n", style=Token.dim)
    left.append("    prometheus --version\n")
    left.append("  \u2713 Run diagnostics\n", style=Token.dim)
    left.append("    prometheus doctor\n")
    left.append("  \u2713 Open interactive shell\n", style=Token.dim)
    left.append("    prometheus\n")

    left.append("\n[bold]Workspace[/bold]\n", style=Token.heading)
    left.append("  ws info        Show workspace metadata\n", style=Token.dim)
    left.append("  ws status      Health checks\n", style=Token.dim)
    left.append("  ws scan        Scan structure\n", style=Token.dim)

    left.append("\n[bold]Profiles[/bold]\n", style=Token.heading)
    left.append("  profile list       List profiles\n", style=Token.dim)
    left.append("  profile save <n>   Save current env\n", style=Token.dim)
    left.append("  profile switch <n> Activate profile\n", style=Token.dim)

    right = Text()
    right.append("[bold]AI Agents[/bold]\n", style=Token.success)
    right.append("  ag list           List all agents\n", style=Token.dim)
    right.append("  ag inspect <n>    Inspect an agent\n", style=Token.dim)

    right.append("\n[bold]ML Jobs[/bold]\n", style=Token.warning)
    right.append("  job submit <file> Submit a dataset\n", style=Token.dim)
    right.append("  job list          List all jobs\n", style=Token.dim)
    right.append("  job status <id>   Check status\n", style=Token.dim)

    right.append("\n[bold]Providers[/bold]\n", style=Token.command)
    right.append("  provider list     List providers\n", style=Token.dim)
    right.append("  provider current  Show active\n", style=Token.dim)

    right.append("\n[bold]Help & Support[/bold]\n", style=Token.secondary)
    right.append("  help <cmd>       Command help\n", style=Token.dim)
    right.append("  commands         All commands\n", style=Token.dim)
    right.append("  search <term>    Search commands\n", style=Token.dim)

    cheat.add_row(left, right)

    return Panel(
        cheat,
        title="[bold]Cheatsheet[/]",
        subtitle="[dim]First five minutes[/dim]",
        border_style="#525252",
        padding=(1, 2),
    )


def _section_cheatsheet(section: str):
    section = section.lower()
    sections = {
        "workspace": (
            "Workspace",
            Token.heading,
            [
                "ws info         Show workspace metadata",
                "ws status       Workspace health checks",
                "ws scan         Scan workspace files",
                "ws tree         Show directory tree",
                "ws open         Open in file manager",
            ],
        ),
        "agents": (
            "AI Agents",
            Token.success,
            [
                "ag list         List all agents",
                "ag inspect <n>  Inspect an agent",
                "ag logs <n>     Agent execution logs",
                "ag metrics      Agent performance",
            ],
        ),
        "jobs": (
            "ML Jobs",
            Token.warning,
            [
                "job submit <f>  Submit training job",
                "job list        List all jobs",
                "job status <id> Check job status",
                "job cancel <id> Cancel a job",
                "job logs <id>   Job execution logs",
            ],
        ),
        "profiles": (
            "Profiles",
            Token.heading,
            [
                "profile list        List saved profiles",
                "profile current     Show active profile",
                "profile save <n>    Save current env",
                "profile switch <n>  Activate profile",
                "profile inspect <n> Show env variables",
                "profile delete <n>  Delete a profile",
            ],
        ),
        "providers": (
            "Providers",
            Token.command,
            [
                "provider list     List providers",
                "provider current  Show active provider",
            ],
        ),
        "help": (
            "Help & Search",
            Token.secondary,
            [
                "help              Show categorized commands",
                "help <cmd>        Help for a command",
                "help <category>   Commands in a category",
                "commands          List all commands",
                "search <term>     Search commands",
                "cheatsheet        This reference",
                "cheatsheet <sec>  Section-specific help",
            ],
        ),
    }
    from rich.panel import Panel
    from rich.text import Text

    if section not in sections:
        return f"[dim]Unknown section '{section}'. Try: {', '.join(sections.keys())}[/dim]"

    title, color, cmds = sections[section]
    text = Text()
    text.append(f"[bold {color}]{title}[/bold {color}]\n\n")
    for c in cmds:
        text.append(f"  {c}\n", style=Token.dim)
    return Panel(text, border_style=color, padding=(1, 2))


def _group_results(results: list[tuple]) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for cmd, _score in results:
        grouped.setdefault(cmd.category, []).append(cmd)
    return grouped

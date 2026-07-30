from __future__ import annotations

from rich.table import Table

from prometheus.registry import Command
from prometheus.ui.theme import Theme


def CategorizedCommandTable(categorized: dict[str, list[Command]]) -> Table:
    table = Table(
        title="Prometheus Commands",
        title_style="bold",
        border_style=str(Theme.border),
        padding=(0, 1),
    )
    table.add_column("Category", style=str(Theme.secondary), width=14, no_wrap=True)
    table.add_column("Command", style=str(Theme.title), no_wrap=True)
    table.add_column("Description", style=str(Theme.muted))

    first = True
    for category in [
        "System",
        "Config",
        "Workspace",
        "Project",
        "Agents",
        "Swarm",
        "Jobs",
        "Provider",
        "Memory",
        "Deploy",
        "Tools",
        "Logs",
    ]:
        commands = categorized.get(category)
        if not commands:
            continue
        if not first:
            table.add_section()
        first = False

        sorted_cmds = sorted(commands, key=lambda c: c.name)
        for i, cmd in enumerate(sorted_cmds):
            if cmd.implemented is False:
                tier_tag = f" [{Theme.muted}]Coming in {cmd.since}[/]"
            elif cmd.experimental:
                tier_tag = f" [{Theme.warning}](experimental)[/]"
            else:
                tier_tag = ""
            table.add_row(
                category if i == 0 else "",
                f"[{'bold' if cmd.implemented else 'dim'}]{cmd.name}[/{'bold' if cmd.implemented else 'dim'}]{tier_tag}",
                cmd.description if cmd.implemented else f"[{Theme.muted}]{cmd.description}[/]",
            )

    return table

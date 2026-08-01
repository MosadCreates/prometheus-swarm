from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.registry import Command, get_categories
from prometheus.ui.theme import Theme


_CATEGORY_STYLES = {
    "System": str(Theme.heading),
    "Config": str(Theme.heading),
    "Workspace": str(Theme.heading),
    "Project": str(Theme.heading),
    "Mission": str(Theme.success),
    "Agents": str(Theme.success),
    "Swarm": str(Theme.success),
    "Jobs": str(Theme.warning),
    "Provider": str(Theme.command),
    "Memory": str(Theme.command),
    "Deploy": str(Theme.warning),
    "Tools": str(Theme.secondary),
    "Logs": str(Theme.secondary),
    "Model": str(Theme.command),
    "Plugin": str(Theme.secondary),
    "Evaluate": str(Theme.warning),
    "Planner": str(Theme.command),
    "Profile": str(Theme.heading),
}


def CategoryPanels(categorized: dict[str, list[Command]]) -> Group:
    panels = []
    for cat in get_categories():
        commands = categorized.get(cat)
        if not commands:
            continue

        sorted_cmds = sorted(commands, key=lambda c: c.name)
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column()

        for cmd in sorted_cmds:
            name_style = f"bold {Theme.title}" if cmd.implemented else str(Theme.muted)
            name = Text(cmd.name, style=name_style)

            if cmd.implemented is False:
                desc = Text(f"  Coming in {cmd.since}", style=str(Theme.muted))
            elif cmd.experimental:
                desc = Text(cmd.description, style=str(Theme.muted))
            else:
                desc = Text(cmd.description, style=str(Theme.muted))

            table.add_row(name, desc)

        cat_color = _CATEGORY_STYLES.get(cat, str(Theme.body))
        panel = Panel(
            table,
            title=f"[bold {cat_color}]{cat}[/]",
            border_style=cat_color,
            padding=(1, 2),
        )
        panels.append(panel)

    return Group(*panels)

from __future__ import annotations

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.registry import Command
from prometheus.ui.styles import Token


_CATEGORY_ORDER = [
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
]

_CATEGORY_STYLES = {
    "System": Token.heading,
    "Config": Token.heading,
    "Workspace": Token.heading,
    "Project": Token.heading,
    "Agents": Token.success,
    "Swarm": Token.success,
    "Jobs": Token.warning,
    "Provider": Token.command,
    "Memory": Token.command,
    "Deploy": Token.warning,
    "Tools": Token.secondary,
    "Logs": Token.secondary,
}


def CategoryPanels(categorized: dict[str, list[Command]]) -> Group:
    panels = []
    for cat in _CATEGORY_ORDER:
        commands = categorized.get(cat)
        if not commands:
            continue

        sorted_cmds = sorted(commands, key=lambda c: c.name)
        table = Table.grid(padding=(0, 2))
        table.add_column(no_wrap=True)
        table.add_column()

        for cmd in sorted_cmds:
            name_style = "bold white" if cmd.implemented else Token.muted
            name = Text(cmd.name, style=name_style)

            if cmd.implemented is False:
                desc = Text(f"  Coming in {cmd.since}", style=Token.muted)
            elif cmd.experimental:
                desc = Text(cmd.description, style=Token.dim)
            else:
                desc = Text(cmd.description, style=Token.dim)

            table.add_row(name, desc)

        cat_color = _CATEGORY_STYLES.get(cat, Token.white)
        panel = Panel(
            table,
            title=f"[bold {cat_color}]{cat}[/]",
            border_style=cat_color,
            padding=(1, 2),
        )
        panels.append(panel)

    return Group(*panels)

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from prometheus.ui.theme import Theme


def StatusPanel(items: list[tuple[str, str]], title: str = "Runtime") -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=str(Theme.secondary))
    table.add_column(style=str(Theme.body))
    for label, value in items:
        table.add_row(label, value)
    return Panel(
        table,
        title=f"[bold {Theme.heading}]{title}[/]",
        border_style=str(Theme.border),
    )

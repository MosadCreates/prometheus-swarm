from __future__ import annotations

from rich.panel import Panel
from rich.table import Table

from prometheus.ui.styles import Token


def StatusPanel(items: list[tuple[str, str]], title: str = "Runtime") -> Panel:
    table = Table.grid(padding=(0, 2))
    table.add_column(style=Token.secondary)
    table.add_column(style="white")
    for label, value in items:
        table.add_row(label, value)
    return Panel(
        table,
        title=f"[bold {Token.heading}]{title}[/]",
        border_style=Token.border,
    )

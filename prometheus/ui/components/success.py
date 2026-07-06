from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.ui.console import console


def SuccessPanel(
    title: str,
    message: str,
    *,
    detail: str | None = None,
    hint: str | None = None,
) -> Panel:
    inner = Table.grid(padding=(0, 1))
    inner.add_column()

    row = Text()
    row.append("\n  \u2713 ", style="bold green")
    row.append(message, style="green")
    inner.add_row(row)

    if detail:
        inner.add_row(Text(f"  {detail}", style="dim white"))
    if hint:
        inner.add_row(Text(f"  \u21d2 {hint}", style="cyan"))

    return Panel(
        inner,
        title=f"[bold green]{title}[/]",
        border_style="green",
        padding=(0, 1),
    )

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.ui.icons import CHECK
from prometheus.ui.theme import Theme


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
    row.append(f"\n  {CHECK} ", style=f"bold {Theme.success}")
    row.append(message, style=str(Theme.success))
    inner.add_row(row)

    if detail:
        inner.add_row(Text(f"  {detail}", style=str(Theme.muted)))
    if hint:
        inner.add_row(Text(f"  \u21d2 {hint}", style=str(Theme.info)))

    return Panel(
        inner,
        title=f"[bold {Theme.success}]{title}[/]",
        border_style=str(Theme.success),
        padding=(0, 1),
    )

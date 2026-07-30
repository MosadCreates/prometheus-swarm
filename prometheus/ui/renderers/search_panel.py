from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.registry import Command
from prometheus.ui.theme import Theme


def SearchPanel(results: list[tuple[Command, float]], query: str) -> Panel:
    inner = Table.grid(padding=(0, 2))
    inner.add_column(no_wrap=True)
    inner.add_column()

    for cmd, score in results:
        stars = _star_rating(score)
        color = (
            str(Theme.command)
            if score >= 0.8
            else str(Theme.body) if score >= 0.6 else str(Theme.secondary)
        )

        name_text = Text()
        name_text.append(f"  {stars}  ", style=str(Theme.warning))
        name_text.append(cmd.name, style=f"bold {color}")

        desc = Text(cmd.description, style=str(Theme.muted))

        extra = Text()
        parts = []
        if cmd.aliases:
            parts.append(f"Aliases: {', '.join(cmd.aliases)}")
        if cmd.examples:
            parts.append(f"Example: {cmd.examples[0]}")
        if cmd.related:
            parts.append(f"Related: {', '.join(cmd.related)}")
        if parts:
            extra.append("\n       ")
            extra.append("  \u2502  ".join(parts), style=str(Theme.muted))

        inner.add_row(name_text, Text.assemble(desc, extra))

    panel = Panel(
        inner,
        title=f"[bold]Search: {query}[/]",
        subtitle=f"[{Theme.muted}]{len(results)} matching command(s)[/]",
        border_style=str(Theme.border),
        padding=(1, 2),
    )
    return panel


def _star_rating(score: float) -> str:
    if score >= 0.95:
        return "\u2605\u2605\u2605\u2605\u2605"
    if score >= 0.8:
        return "\u2605\u2605\u2605\u2605"
    if score >= 0.6:
        return "\u2605\u2605\u2605"
    if score >= 0.45:
        return "\u2605\u2605"
    return "\u2605"

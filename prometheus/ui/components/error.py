from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prometheus.ui.console import console
from prometheus.ui.theme import Theme


def ErrorPanel(
    title: str,
    message: str,
    hint: str | None = None,
    *,
    _console: Console = console,
) -> Panel:
    text = Text()
    text.append(f"\n  {message}\n", style=str(Theme.error))
    if hint:
        text.append(f"\n  [dim]Try:[/dim] [{Theme.info}]{hint}[/{Theme.info}]\n")
    return Panel(
        text,
        title=f"[bold {Theme.error}]{title}[/]",
        border_style=str(Theme.error),
    )

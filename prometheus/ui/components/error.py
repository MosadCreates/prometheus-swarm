from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prometheus.ui.console import console


def ErrorPanel(
    title: str,
    message: str,
    hint: str | None = None,
    *,
    _console: Console = console,
) -> Panel:
    text = Text()
    text.append(f"\n  {message}\n", style="red")
    if hint:
        text.append(f"\n  [dim]Try:[/dim] [cyan]{hint}[/cyan]\n")
    return Panel(text, title=f"[bold red]{title}[/]", border_style="red")

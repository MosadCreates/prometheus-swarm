from __future__ import annotations

import contextlib
import time
from typing import Any, Iterator

from rich.console import Console

from prometheus.ui.console import console


@contextlib.contextmanager
def Spinner(
    message: str = "",
    *,
    _console: Console = console,
) -> Iterator[None]:
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    try:
        _console.print(f"  [dim]{frames[0]} {message}[/dim]", end="")
        yield
        _console.print(f"\r  [green]\u2713[/] [dim]{message}[/]")
    except Exception:
        _console.print(f"\r  [red]\u2717[/] [dim]{message}[/]")
        raise

from __future__ import annotations

import contextlib
import itertools
import time
import threading
from typing import Iterator

from rich.console import Console

from prometheus.ui.console import console
from prometheus.ui.icons import CHECK, CROSS, SPINNER
from prometheus.ui.theme import Theme


@contextlib.contextmanager
def Spinner(
    message: str = "",
    *,
    _console: Console = console,
) -> Iterator[None]:
    stop = threading.Event()
    frame_gen = itertools.cycle(SPINNER)

    def _animate() -> None:
        while not stop.is_set():
            frame = next(frame_gen)
            _console.print(f"\r  [{Theme.muted}]{frame} {message}[/]", end="")
            stop.wait(0.15)

    t = threading.Thread(target=_animate, daemon=True)
    t.start()
    try:
        yield
    except Exception:
        _console.print(f"\r  [{Theme.error}]{CROSS}[/] [{Theme.muted}]{message}[/]")
        raise
    finally:
        stop.set()
        t.join(timeout=1)
        _console.print(f"\r  [{Theme.success}]{CHECK}[/] [{Theme.muted}]{message}[/]")

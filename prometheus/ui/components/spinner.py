from __future__ import annotations

import contextlib
import itertools
import sys
import threading
from io import StringIO
from typing import Iterator

from rich.console import Console
from rich.text import Text

from prometheus.ui.console import console
from prometheus.ui.icons import CHECK, CROSS, SPINNER
from prometheus.ui.theme import Theme


def _to_ansi(text: str, style: str) -> str:
    """Render styled text to a raw ANSI string.

    Uses a scratch Console writing into a buffer, then emits the result
    through sys.stdout directly — Rich's ``Console.print`` drops ``\\r``,
    which breaks in-place animation.
    """
    buf = StringIO()
    scratch = Console(
        file=buf,
        emoji=False,
        highlight=False,
        force_terminal=True,
        soft_wrap=True,
        width=200,
    )
    scratch.print(Text(text, style=style), end="", markup=False, overflow="ignore")
    return buf.getvalue()


@contextlib.contextmanager
def Spinner(
    message: str = "",
    *,
    _console: Console = console,
) -> Iterator[None]:
    stop = threading.Event()
    frame_gen = itertools.cycle(SPINNER)

    indent = _to_ansi("  ", str(Theme.muted))
    body = _to_ansi(message, str(Theme.muted))

    def _animate() -> None:
        while not stop.is_set():
            frame = next(frame_gen)
            sys.stdout.write(f"\r\033[K{indent}{frame} {body}")
            sys.stdout.flush()
            stop.wait(0.15)

    t = threading.Thread(target=_animate, daemon=True)
    t.start()
    try:
        yield
    except Exception:
        sys.stdout.write(f"\r\033[K{_to_ansi(f'{CROSS} {message}', str(Theme.error))}\n")
        sys.stdout.flush()
        raise
    finally:
        stop.set()
        t.join(timeout=1)
        sys.stdout.write(f"\r\033[K{_to_ansi(f'{CHECK} {message}', str(Theme.success))}\n")
        sys.stdout.flush()

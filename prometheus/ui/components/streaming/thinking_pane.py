from __future__ import annotations

import math
import time
from collections import deque

from rich.text import Text

from prometheus.ui.theme import Theme


_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class ThinkingPane:
    MAX_PREVIEW_LINES = 4

    def __init__(self) -> None:
        self._tokens: deque[str] = deque(maxlen=5000)
        self._last_append: float = 0.0

    def append_token(self, token: str) -> None:
        self._tokens.append(token)
        self._last_append = time.monotonic()

    def clear(self) -> None:
        self._tokens.clear()

    @property
    def token_count(self) -> int:
        return len(self._tokens)

    def _word_wrap(self, text: str, width: int, indent: str) -> list[str]:
        lines: list[str] = []
        current = ""
        for word in text.split(" "):
            test = f"{current} {word}".strip()
            if len(test) > width:
                lines.append(f"{indent}{current}".rstrip())
                current = word
            else:
                current = test
        if current:
            lines.append(f"{indent}{current}")
        return lines

    def render(self, collapsed: bool = True, width: int = 80, indent: str = "   │   ") -> Text:
        full = "".join(self._tokens)
        if not full:
            return Text()

        wrapped = self._word_wrap(full, width - len(indent), indent)

        now = time.monotonic()
        glow = (math.sin((now - self._last_append) * math.pi * 2 / 2.0) + 1) / 2
        base_alpha = 0.5 + glow * 0.3
        dim_style = f"italic rgb({int(142*base_alpha)},{int(142*base_alpha)},{int(147*base_alpha)})"

        t = Text()
        t.append(f"{indent}\u25cc ", style=dim_style)

        if collapsed and len(wrapped) > self.MAX_PREVIEW_LINES:
            shown = wrapped[: self.MAX_PREVIEW_LINES]
            remainder = len(wrapped) - self.MAX_PREVIEW_LINES
            for line in shown:
                t.append(line, style=dim_style)
                t.append("\n")
                t.append(f"{indent}", style=dim_style)
                t.append("  ", style=dim_style)
            t.append(f"\u25be {remainder} more lines", style=f"italic {Theme.muted}")
        else:
            for i, line in enumerate(wrapped):
                if i > 0:
                    t.append("\n")
                    t.append(f"{indent}  ", style=dim_style)
                t.append(line, style=dim_style)

        return t

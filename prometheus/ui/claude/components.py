from __future__ import annotations

from rich.text import Text
from rich.style import Style

from prometheus.ui.claude.theme import CLAUDE, INACTIVE, SUBTLE, CLAWD_BODY


CLAWD_ART = [
    "  ▐▛███▜▌",
    " ▝▜█████▛▘",
    "   ▘▘ ▝▝",
]


def make_clawd() -> Text:
    t = Text()
    for i, line in enumerate(CLAWD_ART):
        if i > 0:
            t.append("\n")
        t.append(line, style=Style(color=CLAWD_BODY))
    return t


def make_divider(width: int, char: str = "─") -> Text:
    return Text(char * width, style=Style(color=SUBTLE, dim=True))


def make_feed(title: str, lines: list[str], footer: str | None = None, width: int = 48) -> Text:
    t = Text()
    t.append(title, style=Style(color=CLAUDE, bold=True))
    t.append("\n")
    if not lines:
        return t
    for line in lines:
        t.append(line[:width], style=Style(color=INACTIVE))
        t.append("\n")
    if footer:
        t.append(footer[:width], style=Style(color=INACTIVE, italic=True, dim=True))
    return t

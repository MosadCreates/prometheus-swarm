from __future__ import annotations

import shutil

from rich.style import Style
from rich.text import Text

VERSION = "0.1.0"


# ── Claude Code color tokens ──
_CLAUDE = "#E68A4C"
_TEXT = "#ECECEC"
_INACTIVE = "#8E8E93"
_SUBTLE = "#48484A"
_CLAWD_FG = "#E68A4C"

_STYLE_BORDER = Style(color=_SUBTLE, dim=True)
_STYLE_INACTIVE = Style(color=_INACTIVE, dim=True)
_STYLE_INACTIVE_PLAIN = Style(color=_INACTIVE)
_STYLE_CLAUDE_BOLD = Style(color=_CLAUDE, bold=True)
_STYLE_CLAUDE = Style(color=_CLAUDE)
_STYLE_BODY = Style(color=_TEXT)
_STYLE_BOLD = Style(bold=True)
_STYLE_CLAWD = Style(color=_CLAWD_FG)
_STYLE_FEED_DIVIDER = Style(color=_SUBTLE, dim=True)
_STYLE_FEED_FOOTER = Style(color=_INACTIVE, italic=True, dim=True)
_STYLE_FEED_LINE = Style(color=_INACTIVE)
_STYLE_FEED_TITLE = Style(color=_CLAUDE, bold=True)

CLAWD_ART = [
    " \u2590\u259b\u2588\u2588\u2588\u259c\u258c ",
    "\u259d\u259f\u2588\u2588\u2588\u2588\u2588\u2599\u2598",
    "  \u2598\u2598 \u259d\u259d  ",
]


def _get_pipeline() -> list[str]:
    return [
        "6 Specialized Agents",
        "Scout \u2192 Forge \u2192 Furnace",
        "Dissect \u2192 Arbiter \u2192 Harbor",
    ]


def splash(console) -> None:
    width = console.width or shutil.get_terminal_size().columns
    if width < 64:
        _render_compact(console, width)
    else:
        _render_full(console, width)


def _render_full(console, width: int) -> None:
    left_w = 30
    right_w = width - left_w - 6
    if right_w < 28:
        right_w = 28
        left_w = width - right_w - 6
    if left_w < 22:
        left_w = 22
        right_w = width - left_w - 6

    left = _build_left(left_w)
    right = _build_right(right_w)
    rows = max(len(left), len(right))
    while len(left) < rows:
        left.append(Text(" "))
    while len(right) < rows:
        right.append(Text(" "))

    _emit(console, _make_top(width))

    _emit(console, _make_side("", width))

    for i in range(rows):
        t = Text()
        t.append("\u2502 ", style=_STYLE_BORDER)
        _put(t, left[i], left_w)
        t.append(" \u2502", style=_STYLE_BORDER)
        _put(t, right[i], right_w)
        t.append(" \u2502", style=_STYLE_BORDER)
        _emit(console, t)

    _emit(console, _make_side("", width))
    _emit(console, _make_bot(width))


def _render_compact(console, width: int) -> None:
    console.rule("[bold #E68A4C]Prometheus Swarm[/]", characters="\u2500", style=_STYLE_BORDER)
    console.print()
    pipe = _get_pipeline()
    console.print(_ctr("Autonomous ML Engineering", width, _STYLE_BOLD))
    console.print()
    for line in CLAWD_ART:
        console.print(_ctr(line, width, _STYLE_CLAWD))
    console.print()
    console.print(_ctr(pipe[0], width, _STYLE_BODY))
    for line in pipe[1:]:
        console.print(_ctr(line, width, _STYLE_INACTIVE_PLAIN))


def _make_top(width: int) -> Text:
    t = Text()
    t.append("\u256d\u2500\u2500\u2500 ", style=_STYLE_BORDER)
    t.append("Prometheus Swarm", style=_STYLE_CLAUDE_BOLD)
    t.append(" ", style=_STYLE_BORDER)
    t.append(f"v{VERSION}", style=_STYLE_INACTIVE)
    used = 5 + len("Prometheus Swarm") + 1 + len(f"v{VERSION}")
    rest = width - used - 1
    if rest > 0:
        t.append("\u2500" * rest, style=_STYLE_BORDER)
    t.append("\u256e", style=_STYLE_BORDER)
    return t


def _make_bot(width: int) -> Text:
    return Text("\u2570" + "\u2500" * (width - 2) + "\u256f", style=_STYLE_BORDER)


def _make_side(content: str, width: int) -> Text:
    t = Text()
    t.append("\u2502", style=_STYLE_BORDER)
    if content:
        t.append(" " + content)
        pad = width - len(content) - 2
        if pad > 0:
            t.append(" " * pad)
    else:
        t.append(" " * (width - 2))
    t.append("\u2502", style=_STYLE_BORDER)
    return t


def _put(dest: Text, src: Text, w: int) -> None:
    dest.append(src)
    pad = w - len(src.plain)
    if pad > 0:
        dest.append(" " * pad)


def _emit(console, renderable) -> None:
    console.print(renderable, markup=False, highlight=False)


# ── left column ──


def _build_left(w: int) -> list[Text]:
    pipe = _get_pipeline()

    lines: list[Text] = []
    lines.append(Text(" " * w))
    lines.append(_ctr("Autonomous ML Engineering", w, _STYLE_BOLD))
    lines.append(Text(" " * w))

    for clawd_line in CLAWD_ART:
        lines.append(_ctr(clawd_line, w, _STYLE_CLAWD))
    lines.append(Text(" " * w))

    lines.append(_ctr(pipe[0], w, _STYLE_BODY))
    for line in pipe[1:]:
        lines.append(_ctr(line, w, _STYLE_INACTIVE_PLAIN))
    return lines


# ── right column (feeds) ──


FEED_SECTIONS: list[tuple[str, list[str], str | None]] = [
    (
        "Quick start",
        [
            "mission new --file data.csv",
            "mission list",
            "cockpit",
            "doctor",
        ],
        "/docs for full reference",
    ),
    (
        "Features",
        [
            "Dissect self-patching crash recovery",
            "Harbor live ONNX + FastAPI serving",
            "Arbiter auto model evaluation",
            "Cockpit TUI real-time telemetry",
        ],
        None,
    ),
]


def _build_right(w: int) -> list[Text]:
    lines: list[Text] = []
    for title, items, footer in FEED_SECTIONS:
        if w < 4:
            lines.append(Text(" "))
            continue
        lines.append(Text(f"  {title}", style=_STYLE_FEED_TITLE))
        for item in items:
            disp = item if len(item) <= w - 2 else item[: w - 5] + "..."
            lines.append(Text(f"  {disp}", style=_STYLE_FEED_LINE))
        gap = w - 2
        if gap > 0:
            div = "\u2500" * gap
            lines.append(Text(f"  {div}", style=_STYLE_FEED_DIVIDER))
        if footer:
            lines.append(Text(f"  {footer}", style=_STYLE_FEED_FOOTER))
        lines.append(Text(" "))
    return lines


def _ctr(text: str, width: int, style: Style) -> Text:
    pad = width - len(text)
    if pad <= 0:
        return Text(text[:width], style=style)
    left = pad // 2
    right = pad - left
    t = Text()
    t.append(" " * left)
    t.append(text, style=style)
    t.append(" " * right)
    return t

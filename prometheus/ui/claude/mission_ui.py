from __future__ import annotations

import shutil
import sys

from rich.style import Style
from rich.text import Text

from prometheus.ui.claude.agent_colors import AGENT_COLORS

# ── detect encoding — try for UTF-8 on Windows ──
_ENC = sys.stdout.encoding or ""
_UTF8_OK = _ENC.lower() in ("utf-8", "utf8") or sys.platform != "win32"

if not _UTF8_OK and sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        _ENC = "utf-8"
        _UTF8_OK = True
    except Exception:
        pass

# ── symbols ──
if _UTF8_OK:
    _POINTER = "\u276f"
    _DOT = "\u25cf"
    _CHECK = "\u2713"
    _CROSS = "\u2718"
    _THINKING = "\u2234"
    _TREE_V = "\u2502"
    _TREE_MID = "\u251c\u2500\u2500"
    _TREE_END = "\u2514\u2500\u2500"
    _INFO = "\u23bf"
    _SEP = "\u2500"
    _ELIPS = "\u2026"
else:
    _POINTER = ">"
    _DOT = "o"
    _CHECK = "+"
    _CROSS = "x"
    _THINKING = "."
    _TREE_V = "|"
    _TREE_MID = "+--"
    _TREE_END = "`--"
    _INFO = "-"
    _SEP = "-"
    _ELIPS = "..."

# ── base styles ──
_STYLE_BORDER = Style(color="#2A2A2A", dim=True)
_STYLE_DIM = Style(dim=True)
_STYLE_DIM_ITALIC = Style(dim=True, italic=True)
_STYLE_SUCCESS = Style(color="#5FD75F")
_STYLE_ERROR = Style(color="#D75F5F")
_STYLE_BODY = Style(color="#ECECEC")

# ── lazy console import (avoid circular deps) ──
_console = None


def _out():
    global _console
    if _console is None:
        from rich.console import Console

        _console = Console(
            emoji=False, safe_box=True, no_color=False, log_time=False, color_system="auto"
        )
    return _console


# ── public API ──


def separator() -> None:
    w = _width()
    t = Text(_SEP * w, style=_STYLE_BORDER)
    _out().print(t)


def user_message(text: str) -> None:
    t = Text(f"{_POINTER} {text}", style=_STYLE_BODY)
    _out().print(t)


def thinking(text: str = f"Thinking{_ELIPS}") -> None:
    t = Text(f"{_THINKING} {text}", style=_STYLE_DIM_ITALIC)
    _out().print(t)


def agent_start(agent: str, summary: str = "") -> None:
    t = Text()
    t.append(f"{_INFO}  ", style=_STYLE_DIM)
    t.append(_badge(agent))
    if summary:
        t.append(f"  {summary}", style=_STYLE_DIM)
    _out().print(t)


def agent_done(agent: str, summary: str) -> None:
    t = Text()
    t.append(f"{_CHECK}  ", style=_STYLE_SUCCESS)
    t.append(_badge(agent))
    t.append(f"  {summary}", style=_STYLE_BODY)
    _out().print(t)


def agent_error(agent: str, summary: str) -> None:
    t = Text()
    t.append(f"{_CROSS}  ", style=_STYLE_ERROR)
    t.append(_badge(agent))
    t.append(f"  {summary}", style=_STYLE_ERROR)
    _out().print(t)


def info_line(text: str) -> None:
    text = f"  {_TREE_V}  {_INFO}  {text}"
    t = Text(text, style=_STYLE_DIM)
    _out().print(t)


def tree_handoff(agent: str, is_last: bool = False) -> None:
    connector = _TREE_END if is_last else _TREE_MID
    t = Text()
    t.append(f"  {connector} ", style=_STYLE_DIM)
    t.append(_badge(agent))
    _out().print(t)


def agent_summary(agent: str, text: str) -> None:
    t = Text(f"  {_TREE_V}  {_INFO}  {text}", style=_STYLE_BODY)
    _out().print(t)


def mission_complete(summary: str = "Mission complete.") -> None:
    _out().print()
    t = Text(f"  {summary}", style=_STYLE_SUCCESS)
    _out().print(t)


# ── internal helpers ──


def _badge(agent: str) -> Text:
    color = AGENT_COLORS.get(agent, "#8E8E93")
    return Text(f" {agent} ", style=Style(bgcolor=color, bold=True, color="#FFFFFF"))


def _width() -> int:
    return shutil.get_terminal_size().columns

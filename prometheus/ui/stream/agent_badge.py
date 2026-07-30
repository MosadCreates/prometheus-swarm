# ruff: noqa: E501 — display strings with long styled fragments
"""Agent badge line rendering for the scroll-forward renderer.

Renders a single agent's status line in one of four states::

    Active:    ├── ⠹  Scout   Profiling dataset…  · 00m 03s
    Complete:  ├── ✔  Scout   Dataset profiled  · 00m 12s
    Error:     ├── ✘  Scout   Failed  · 00m 02s
    Pending:   │   ○  Forge   queued

Badge lines are built as Rich ``Text`` objects and then converted to
ANSI strings for direct ``sys.stdout.write()`` output.
"""

from __future__ import annotations

import time
from io import StringIO

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.claude.agent_colors import AGENT_COLORS
from prometheus.ui.theme import Theme

# ── Symbols ──────────────────────────────────────────────────────────────
_CHECK = "✔"
_CROSS = "✘"
_CIRCLE = "○"
_LIGHTNING = "⚡"
_BULLET = "·"

# ── Spinner frames (braille dots, bidirectional sweep) ───────────────────
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_SPINNER_INTERVAL_MS = 100

# ── Tree connector characters ────────────────────────────────────────────
_TREE_MID = "├──"
_TREE_END = "└──"
_TREE_PIPE = "│"

# ── Layout ───────────────────────────────────────────────────────────────
_PAD_LEFT = 3
_INDENT = " " * _PAD_LEFT
_NAME_COL_WIDTH = 9


def _format_duration(seconds: float) -> str:
    """Format duration as 00m 00s."""
    if seconds < 1:
        return ""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}m {s:02d}s"


def _get_spinner(tick: float) -> str:
    """Get the current spinner frame based on tick time."""
    idx = int(tick * 1000 / _SPINNER_INTERVAL_MS) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[idx]


def render_badge(
    name: str,
    status: str,
    summary: str = "",
    elapsed: float = 0.0,
    tick: float = 0.0,
    is_last: bool = False,
) -> Text:
    """Render a single agent badge line as a Rich Text object.

    Parameters
    ----------
    name
        Agent name (Scout, Forge, etc.).
    status
        One of: ``pending``, ``active``, ``done``, ``error``.
    summary
        Current activity or result summary.
    elapsed
        Seconds since the agent started.
    tick
        Monotonic time for spinner animation.
    is_last
        If True, use └── instead of ├── connector.
    """
    color = AGENT_COLORS.get(name, "#8E8E93")
    conn = _TREE_END if is_last else _TREE_MID
    t = Text()

    # ── Connector ──
    t.append(f"{_INDENT}{conn} ", style=str(Theme.muted))

    # ── Status icon ──
    if name == "Dissect" and status in ("active", "done", "error"):
        t.append(f" {_LIGHTNING} ", style=f"bold {color}")
    elif status == "active":
        spinner = _get_spinner(tick)
        t.append(f" {spinner} ", style=f"bold {color}")
    elif status == "done":
        t.append(f" {_CHECK} ", style=f"bold {Theme.stream_finalized}")
    elif status == "error":
        t.append(f" {_CROSS} ", style=f"bold {Theme.error}")
    else:
        t.append(f" {_CIRCLE} ", style=str(Theme.muted))

    # ── Agent name (fixed-width column) ──
    name_pad = max(1, _NAME_COL_WIDTH - len(name))
    t.append(f" {name}{' ' * name_pad}", style=f"bold {color}")

    # ── Summary text ──
    if summary:
        t.append("  ", style=str(Theme.muted))
        if status == "done":
            t.append(summary, style=str(Theme.success))
        elif status == "error":
            t.append(summary, style=str(Theme.error))
        else:
            t.append(summary, style=str(Theme.body))

    # ── Duration ──
    dur = _format_duration(elapsed)
    if dur:
        t.append(f"  {_BULLET} {dur}", style=str(Theme.muted))

    return t


def render_pending(name: str) -> Text:
    """Render a pending/queued agent line."""
    color = AGENT_COLORS.get(name, "#8E8E93")
    t = Text()
    t.append(f"{_INDENT}{_TREE_PIPE}   ", style=str(Theme.muted))
    t.append(f"{_CIRCLE} ", style=str(Theme.muted))
    t.append(name, style=f"bold {color}")
    t.append("   queued", style=str(Theme.muted))
    return t


def render_subaction(detail: str, state: str = "running", is_last: bool = False) -> Text:
    """Render a subaction detail line under an agent.

    ::

        │   ⎿ ▶ Evaluating candidates: LightGBM, XGBoost
        │   ⎿ ◆ Selected: LightGBM (confidence: 0.92)
        │   ⎿ ✔ Architecture: lightgbm
        │   ⎿ Error: KeyError at line 47
    """
    t = Text()
    t.append(f"{_INDENT}{_TREE_PIPE}   ⎿ ", style=str(Theme.muted))

    if state == "error":
        t.append(detail, style=str(Theme.error))
    elif state == "done":
        t.append(f"{_CHECK} ", style=str(Theme.stream_finalized))
        t.append(detail, style=str(Theme.body))
    elif state == "planning":
        t.append("◆ ", style=str(Theme.stream_running))
        t.append(detail, style=str(Theme.body))
    else:  # running / acting
        t.append("▶ ", style=str(Theme.stream_running))
        t.append(detail, style=str(Theme.stream_subaction))

    return t


def render_thinking_line(text: str) -> Text:
    """Render a thinking stream line (Dissect only).

    ::

        │   ⎿ thinking: The dataset crashed with a KeyError…
    """
    t = Text()
    t.append(f"{_INDENT}{_TREE_PIPE}   ⎿ ", style=str(Theme.muted))
    t.append("thinking: ", style=Style(color="#8E8E93", italic=True, dim=True))
    t.append(text, style=Style(color="#8E8E93", italic=True))
    return t


def render_thinking_summary(token_count: int) -> Text:
    """Render the token count summary after thinking completes.

    ::

        │   ⎿ Thinking: 847 tokens
    """
    t = Text()
    t.append(f"{_INDENT}{_TREE_PIPE}   ⎿ ", style=str(Theme.muted))
    t.append(f"Thinking: {token_count:,} tokens", style=Style(color="#8E8E93", dim=True))
    return t


def render_detail_line(key: str, value: str) -> Text:
    """Render a key=value detail line under a finalized agent.

    ::

        │   ⎿ task=binary_classification  modality=tabular  confidence=0.94
    """
    t = Text()
    t.append(f"{_INDENT}{_TREE_PIPE}   ⎿ ", style=str(Theme.muted))
    t.append(f"{key}={value}", style=str(Theme.muted))
    return t


def text_to_ansi(text: Text, width: int = 120, color_system: str = "auto") -> str:
    """Convert a Rich Text object to an ANSI escape string."""
    buf = StringIO()
    safe_width = max(10, width - 1)
    tmp = Console(
        file=buf,
        width=safe_width,
        color_system=color_system,
        force_terminal=True,
        emoji=False,
        highlight=False,
    )
    tmp.print(text, end="", overflow="ellipsis", no_wrap=True)
    return buf.getvalue()

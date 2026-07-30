# ruff: noqa: E501 — display strings with long styled fragments
"""Live mission header with cursor-up in-place updates.

Renders a 3-line header box at the top of the mission output::

    ┌─fraud-detect-a3f9────────────────── Elapsed  01:42 ── ▶ running ─┐
    │ ✔ Scout ── ⠹ Forge ── ○ Furnace ── ○ Dissect ── ○ Arbiter ── ○ Harbor │
    └──────────────────────────────────────────────────────────────────────┘

The header is printed once and then updated in-place via ANSI cursor
save/restore (``\\033[s`` / ``\\033[u``) with cursor-up (``\\033[{N}A``).
Same technique as ``docker compose up`` and ``kubectl``.
"""

from __future__ import annotations

import os
import sys
from io import StringIO

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.claude.agent_colors import AGENT_COLORS
from prometheus.ui.theme import Theme

# ── Agent pipeline order ─────────────────────────────────────────────────
AGENT_ORDER = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]

# ── Symbols ──────────────────────────────────────────────────────────────
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

_STATE_ICONS = {
    "pending": "○",
    "running": "▶",
    "complete": "✔",
    "error": "✘",
    "disabled": "—",
}

_STATE_COLORS = {
    "pending": str(Theme.muted),
    "running": str(Theme.stream_running),
    "complete": str(Theme.stream_finalized),
    "error": str(Theme.error),
    "disabled": str(Theme.muted),
}

_STATUS_LABELS = {
    "starting": "● STARTING",
    "running": "▶ running",
    "complete": "✔ complete",
    "error": "✘ error",
    "cancelled": "○ cancelled",
}

_STATUS_COLORS = {
    "starting": Theme.warning,
    "running": Theme.stream_running,
    "complete": Theme.stream_finalized,
    "error": Theme.error,
    "cancelled": Theme.muted,
}

# Number of lines the header occupies (top border + content + bottom border)
HEADER_LINE_COUNT = 3


def _get_spinner(tick: float) -> str:
    idx = int(tick * 1000 / 100) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[idx]


def _pipeline_ribbon(agent_states: dict[str, str], tick: float) -> Text:
    """Build the pipeline ribbon: ✔ Scout ── ⠹ Forge ── ○ Furnace …"""
    t = Text()
    for i, agent in enumerate(AGENT_ORDER):
        if i > 0:
            t.append(" ── ", style=str(Theme.tree_connector))

        state = agent_states.get(agent, "pending")
        if state == "running":
            icon = _get_spinner(tick)
        else:
            icon = _STATE_ICONS.get(state, "○")
        color = _STATE_COLORS.get(state, str(Theme.muted))
        agent_color = AGENT_COLORS.get(agent, "#8E8E93")
        
        # When complete, dim the text slightly so it doesn't overpower the running agent
        text_style = f"bold {agent_color}" if state in ("running", "error") else str(Theme.muted)

        t.append(icon, style=color)
        t.append(" ", style=color)
        t.append(agent, style=text_style)
    return t


def render_header(
    mission_id: str,
    agent_states: dict[str, str],
    status: str,
    elapsed_seconds: int,
    tick: float,
    width: int,
) -> str:
    """Render the complete 3-line header as a Rich Text object.
    
    This is passed directly to the `rich.Live` context to serve as
    the Sticky Footer.
    """
    w = min(width - 2, 96)
    inner_w = w - 2
    slug = mission_id[:20] if mission_id else "—"
    elapsed = f"{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}"
    sc = _STATUS_COLORS.get(status, Theme.secondary)
    status_label = _STATUS_LABELS.get(status, status.upper())

    # ── Line 1: Top border with slug and elapsed ──
    top = Text()
    top.append("┌─", style=str(Theme.tree_connector))
    top.append(slug, style=f"bold {Theme.accent}")
    right_content = f"  Elapsed  {elapsed}"
    used = 2 + len(slug)
    status_str = f" ── {status_label} ─"
    pad = inner_w - used - len(right_content) - len(status_str)
    if pad > 0:
        top.append("─" * pad, style=str(Theme.tree_connector))
    top.append(right_content, style=str(Theme.muted))
    top.append(" ── ", style=str(Theme.tree_connector))
    top.append(status_label, style=f"bold {sc}")
    top.append(" ─", style=str(Theme.tree_connector))
    top.append("┐\n", style=str(Theme.tree_connector))

    # ── Line 2: Pipeline ribbon ──
    line2 = Text()
    line2.append("│ ", style=str(Theme.tree_connector))
    ribbon = _pipeline_ribbon(agent_states, tick)
    line2.append_text(ribbon)
    ribbon_len = len(ribbon.plain)
    pad2 = max(1, inner_w - ribbon_len)
    line2.append(" " * pad2, style=str(Theme.tree_connector))
    line2.append("│\n", style=str(Theme.tree_connector))

    # ── Line 3: Bottom border ──
    bottom = Text()
    bottom.append("└", style=str(Theme.tree_connector))
    bottom.append("─" * inner_w, style=str(Theme.tree_connector))
    bottom.append("┘", style=str(Theme.tree_connector))

    top.append_text(line2)
    top.append_text(bottom)
    
    console = Console(width=width, highlight=False)
    with console.capture() as capture:
        console.print(top)
    return capture.get()

def supports_cursor_movement() -> bool:
    """Check if the terminal supports ANSI cursor movement."""
    import sys
    return sys.stdout.isatty()

def write_header_update(header: str, lines_since: int) -> None:
    """Write an in-place update to the header using ANSI cursor movement."""
    if not supports_cursor_movement():
        return
        
    import sys
    import shutil
    try:
        term_height = shutil.get_terminal_size().lines
    except (OSError, AttributeError):
        term_height = 40
        
    up = lines_since + HEADER_LINE_COUNT
    if up >= term_height - 1:
        return
        
    sys.stdout.write(f"\033[s\033[{up}A\r\033[K{header.rstrip(chr(10))}\033[u")
    sys.stdout.flush()

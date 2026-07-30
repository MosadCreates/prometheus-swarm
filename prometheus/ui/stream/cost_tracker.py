"""Token/cost summary line and terminal bell.

Renders the mission completion footer::

    ─────────────────────────────────────────────────────────────────────
      ✔ Mission complete · 03m 42s · 6 agents · 4,231 tokens · $0.0234
    ─────────────────────────────────────────────────────────────────────

Also emits a terminal bell (``\\a``) on completion.
"""

from __future__ import annotations

import sys
from io import StringIO

from rich.console import Console
from rich.text import Text

from prometheus.ui.theme import Theme


def _format_duration(seconds: float) -> str:
    secs = int(seconds)
    m, s = divmod(secs, 60)
    return f"{m:02d}m {s:02d}s"


def render_completion_line(
    duration_seconds: float,
    agent_count: int = 6,
    total_tokens: int = 0,
    total_cost: float = 0.0,
    success: bool = True,
    width: int = 80,
) -> str:
    """Render the final completion summary line with terminal bell.

    Returns an ANSI string with dividers and the summary.
    """
    dur = _format_duration(duration_seconds)
    icon = "✔" if success else "✘"
    label = "Mission complete" if success else "Mission failed"
    rule_width = min(width, 80)

    parts = [f"{dur}", f"{agent_count} agents"]
    if total_tokens:
        parts.append(f"{total_tokens:,} tokens")
    if total_cost > 0:
        parts.append(f"${total_cost:.4f}")

    detail = " · ".join(parts)

    t = Text()
    t.append("─" * rule_width, style=str(Theme.tree_connector))
    t.append("\n")
    t.append("  ", style=str(Theme.tree_connector))
    if success:
        t.append(f"{icon} ", style=str(Theme.success))
        t.append(label, style=f"bold {Theme.success}")
    else:
        t.append(f"{icon} ", style=str(Theme.error))
        t.append(label, style=f"bold {Theme.error}")
    t.append(f" · {detail}", style=str(Theme.muted))
    t.append("\n")
    t.append("─" * rule_width, style=str(Theme.tree_connector))

    # Convert to ANSI
    buf = StringIO()
    console = Console(
        file=buf,
        width=width,
        color_system="auto",
        force_terminal=True,
        emoji=False,
        highlight=False,
    )
    console.print(t, end="")
    return buf.getvalue()


def emit_bell() -> None:
    """Emit a terminal bell character."""
    sys.stdout.write("\a")
    sys.stdout.flush()

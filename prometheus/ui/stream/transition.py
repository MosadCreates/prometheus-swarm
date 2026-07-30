"""Agent handoff transition lines.

Renders a single-line banner between agent handoffs::

    ──── Scout → Forge ─── dataset profiled, selecting architecture ────

These are permanent lines — printed once and never rewritten.
"""

from __future__ import annotations

from io import StringIO

from rich.console import Console
from rich.text import Text

from prometheus.ui.claude.agent_colors import AGENT_COLORS
from prometheus.ui.theme import Theme


def render_transition(
    from_agent: str,
    to_agent: str,
    reason: str = "",
    width: int = 80,
) -> Text:
    """Render a one-line transition banner between agent handoffs.

    Parameters
    ----------
    from_agent
        Name of the completing agent.
    to_agent
        Name of the next agent.
    reason
        Optional human-readable reason for the handoff.
    width
        Terminal width for fill calculation.
    """
    inner = f" {from_agent} → {to_agent} "
    if reason:
        inner += f" — {reason} "

    total_fill = max(4, width - len(inner) - 2)
    left = total_fill // 2
    right = total_fill - left

    from_color = AGENT_COLORS.get(from_agent, "#8E8E93")
    to_color = AGENT_COLORS.get(to_agent, "#8E8E93")

    t = Text()
    t.append("─" * left, style=str(Theme.tree_connector))
    t.append(" ", style=str(Theme.tree_connector))
    t.append(from_agent, style=f"bold {from_color}")
    t.append(" → ", style=str(Theme.tree_connector))
    t.append(to_agent, style=f"bold {to_color}")
    if reason:
        t.append(" — ", style=str(Theme.tree_connector))
        t.append(reason, style=str(Theme.muted))
    t.append(" ", style=str(Theme.tree_connector))
    t.append("─" * right, style=str(Theme.tree_connector))

    return t

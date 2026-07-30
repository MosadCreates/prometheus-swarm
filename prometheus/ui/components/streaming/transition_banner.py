from __future__ import annotations

from rich.text import Text

from prometheus.ui.theme import Theme

_AGENT_ORDER = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]
_AGENT_COLORS = {
    "Scout": Theme.agent_scout,
    "Forge": Theme.agent_forge,
    "Furnace": Theme.agent_furnace,
    "Dissect": Theme.agent_dissect,
    "Arbiter": Theme.agent_arbiter,
    "Harbor": Theme.agent_harbor,
}


def render_transition(
    from_agent: str,
    to_agent: str,
    reason: str = "",
    width: int = 80,
) -> Text:
    """Render a one-line transition banner between agent handoffs.

    Output:
    ─── Scout → Forge ─── dataset profiled, selecting architecture ────
    """
    inner = f" {from_agent} \u2192 {to_agent} "
    if reason:
        inner += f" \u2014 {reason} "

    total_fill = max(4, width - len(inner) - 2)
    left = total_fill // 2
    right = total_fill - left

    from_color = _AGENT_COLORS.get(from_agent, Theme.secondary)
    to_color = _AGENT_COLORS.get(to_agent, Theme.secondary)

    t = Text()
    t.append("\u2500" * left, style=str(Theme.tree_connector))
    t.append(" ", style=str(Theme.tree_connector))
    t.append(from_agent, style=f"bold {from_color}")
    t.append(" \u2192 ", style=str(Theme.tree_connector))
    t.append(to_agent, style=f"bold {to_color}")
    if reason:
        t.append(" \u2014 ", style=str(Theme.tree_connector))
        t.append(reason, style=str(Theme.muted))
    t.append(" ", style=str(Theme.tree_connector))
    t.append("\u2500" * right, style=str(Theme.tree_connector))

    return t

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.text import Text

from prometheus.ui.theme import Theme


AGENT_ORDER = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]

STATE_ICONS = {
    "pending": "\u25cb",
    "starting": "\u25d0",
    "running": "\u25b6",
    "complete": "\u2714",
    "error": "\u2718",
    "disabled": "\u2014",
}

STATE_COLORS = {
    "pending": str(Theme.muted),
    "starting": str(Theme.warning),
    "running": str(Theme.info),
    "complete": str(Theme.success),
    "error": str(Theme.error),
    "disabled": str(Theme.muted),
}

AGENT_COLORS = {
    "Scout": str(Theme.agent_scout),
    "Forge": str(Theme.agent_forge),
    "Furnace": str(Theme.agent_furnace),
    "Dissect": str(Theme.agent_dissect),
    "Arbiter": str(Theme.agent_arbiter),
    "Harbor": str(Theme.agent_harbor),
}

_SPINNER_FRAMES = [
    "\u280b",
    "\u2819",
    "\u2839",
    "\u2838",
    "\u283c",
    "\u2834",
    "\u2826",
    "\u2827",
    "\u2807",
    "\u280f",
]
_ACTIVE_AGENT_SPINNER = "\u25b6"


def _agent_spinner(agent: str, tick: float) -> str:
    idx = int(tick * 1000 / 100) % len(_SPINNER_FRAMES)
    return _SPINNER_FRAMES[idx]


@dataclass
class PipelineTracker:
    agent_states: dict[str, str] = field(default_factory=dict)
    agent_summaries: dict[str, str] = field(default_factory=dict)
    agent_details: dict[str, dict[str, Any]] = field(default_factory=dict)
    compact: bool = False

    def __post_init__(self):
        for agent in AGENT_ORDER:
            if agent not in self.agent_states:
                self.agent_states[agent] = "pending"

    def set_state(self, agent: str, state: str) -> None:
        if agent in AGENT_ORDER:
            self.agent_states[agent] = state

    def set_summary(self, agent: str, summary: str) -> None:
        self.agent_summaries[agent] = summary

    def set_details(self, agent: str, details: dict[str, Any]) -> None:
        self.agent_details[agent] = details

    def set_compact(self, compact: bool) -> None:
        self.compact = compact

    def _all_pending(self) -> bool:
        return all(s == "pending" for s in self.agent_states.values())

    def _pending_count(self) -> int:
        return sum(1 for s in self.agent_states.values() if s == "pending")

    def render(self, tick: float = 0.0) -> Text:
        if self._all_pending():
            return self._render_waiting()
        return self._render_ribbon(tick)

    def _render_waiting(self) -> Text:
        t = Text()
        t.append("  \u23f3 ", style=str(Theme.muted))
        t.append("Waiting \u2014 ", style=str(Theme.muted))
        for i, agent in enumerate(AGENT_ORDER):
            if i > 0:
                t.append(" ", style=str(Theme.tree_connector))
            color = AGENT_COLORS.get(agent, str(Theme.secondary))
            t.append(agent, style=f"bold {color}")
            if i < len(AGENT_ORDER) - 1:
                t.append(" \u2192", style=str(Theme.tree_connector))
        return t

    def _render_ribbon(self, tick: float) -> Text:
        t = Text()
        for i, agent in enumerate(AGENT_ORDER):
            if i > 0:
                t.append(" ", style=str(Theme.tree_connector))
                t.append("\u2192", style="bold bright_cyan")
                t.append(" ", style=str(Theme.tree_connector))

            state = self.agent_states.get(agent, "pending")
            if state == "running":
                icon = _agent_spinner(agent, tick)
            else:
                icon = STATE_ICONS.get(state, "\u25cb")
            color = STATE_COLORS.get(state, str(Theme.muted))
            agent_color = AGENT_COLORS.get(agent, str(Theme.secondary))

            t.append(f"{icon} ", style=color)
            t.append(agent, style=f"bold {agent_color}")

        return t

    def render_compact(self) -> str:
        t = Text()
        active = [a for a in AGENT_ORDER if self.agent_states.get(a) == "running"]
        done = [a for a in AGENT_ORDER if self.agent_states.get(a) == "complete"]
        pending_count = self._pending_count()

        for a in done:
            t.append("\u2714 ", style=str(Theme.success))
            t.append(f"{a} ", style=f"bold {AGENT_COLORS.get(a, str(Theme.secondary))}")
        if active:
            for a in active:
                t.append("\u25b6 ", style=str(Theme.info))
                t.append(f"{a} ", style=f"bold {AGENT_COLORS.get(a, str(Theme.secondary))}")
        if pending_count:
            t.append(f"\u2026 {pending_count} pending", style=str(Theme.muted))
        return str(t)

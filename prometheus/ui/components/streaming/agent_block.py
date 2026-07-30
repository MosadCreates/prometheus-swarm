from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from rich.style import Style
from rich.text import Text

from prometheus.ui.components.streaming.cascade_panel import CascadePanel
from prometheus.ui.components.streaming.progress_bar import (
    ProgressBar,
    create_confidence_bar,
    create_training_bar,
    create_dataset_bar,
)
from prometheus.ui.components.streaming.thinking_pane import ThinkingPane
from prometheus.ui.theme import Theme

_AGENT_COLORS = {
    "Scout": Theme.agent_scout,
    "Forge": Theme.agent_forge,
    "Furnace": Theme.agent_furnace,
    "Dissect": Theme.agent_dissect,
    "Arbiter": Theme.agent_arbiter,
    "Harbor": Theme.agent_harbor,
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
_SPINNER_INTERVAL = 100

_TREE_CONT = "\u2502   "


@dataclass
class SubactionNode:
    detail: str = ""
    detail_data: dict[str, Any] | None = None
    progress: float = 0.0
    state: str = "running"


class AgentBlock:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status: str = "pending"
        self.summary: str = ""
        self.subactions: list[SubactionNode] = []
        self.thinking_pane = ThinkingPane()
        self.cascade_panel = CascadePanel()
        self.details: dict[str, Any] = {}
        self.progress_bars: dict[str, ProgressBar] = {}
        self.seen: bool = False
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.token_count: int = 0

    @property
    def color(self) -> str:
        return str(_AGENT_COLORS.get(self.name, Theme.secondary))

    @property
    def duration(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        if self.start_time:
            return time.monotonic() - self.start_time
        return 0.0

    def _dur_str(self) -> str:
        d = self.duration
        if d < 1:
            return ""
        if d < 60:
            return f"{int(d)}s"
        return f"{int(d // 60)}m {int(d % 60):02d}s"

    def _badge_line(self, tick: float) -> Text:
        t = Text()

        if self.status == "active":
            idx = int(tick * 1000 / _SPINNER_INTERVAL) % len(_SPINNER_FRAMES)
            spinner = _SPINNER_FRAMES[idx]
            t.append(f" {spinner} ", style=Style(bgcolor=self.color, bold=True, color="#FFFFFF"))
        elif self.status == "done":
            t.append(" \u2714 ", style=Style(bgcolor=Theme.success.hex, bold=True, color="#FFFFFF"))
        elif self.status == "error":
            t.append(" \u2718 ", style=Style(bgcolor=Theme.error.hex, bold=True, color="#FFFFFF"))
        else:
            t.append(" \u25cb ", style=str(Theme.muted))

        t.append(f" {self.name} ", style=f"bold {self.color}")

        dur = self._dur_str()
        if dur:
            t.append(f"  \u00b7 {dur}", style=str(Theme.muted))

        if self.summary:
            t.append("  ", style=str(Theme.muted))
            t.append(self.summary, style=str(Theme.body))

        return t

    def _render_subactions(self, indent: str) -> Text:
        t = Text()
        for sub in self.subactions:
            t.append(f"{indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
            if sub.state == "error":
                t.append(sub.detail, style=str(Theme.error))
            elif sub.state == "done":
                t.append("\u2714 ", style=str(Theme.success))
                t.append(sub.detail, style=str(Theme.body))
            else:
                t.append("\u25d0 ", style=str(Theme.info))
                t.append(sub.detail, style=str(Theme.muted))
            t.append("\n")
        return t

    def _render_progress_bars(self, indent: str) -> Text:
        t = Text()
        for key, bar in self.progress_bars.items():
            bar_text = bar.render()
            t.append(f"{indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
            t.append_text(bar_text)
            t.append("\n")
        return t

    def render_live(self, tick: float, width: int = 80) -> Text:
        indent = "   "
        t = Text()

        # Badge line
        t.append_text(self._badge_line(tick))
        t.append("\n")

        # Progress bars
        if self.progress_bars:
            bar_indent = f"{indent}\u2502   "
            t.append_text(self._render_progress_bars(bar_indent))

        # Thinking pane
        if self.status == "active" and self.thinking_pane.token_count > 0:
            think = self.thinking_pane.render(
                collapsed=True, width=width, indent=f"{indent}\u2502   "
            )
            if think.plain.strip():
                t.append_text(think)
                t.append("\n")

        # Cascade panel
        if self.name == "Dissect":
            cascade = self.cascade_panel.render(indent=f"{indent}\u2502   ")
            if cascade.plain.strip():
                t.append_text(cascade)

        # Subactions
        if self.subactions:
            t.append_text(self._render_subactions(f"{indent}\u2502   "))

        return t

    def render_finalized(self, width: int = 80) -> Text:
        indent = "   "
        t = Text()

        # Badge line
        t.append_text(self._badge_line(0))
        t.append("\n")

        # Progress bars
        if self.progress_bars:
            bar_indent = f"{indent}\u2502   "
            t.append_text(self._render_progress_bars(bar_indent))

        # Thinking (full)
        if self.thinking_pane.token_count > 0:
            think = self.thinking_pane.render(
                collapsed=False, width=width, indent=f"{indent}\u2502   "
            )
            if think.plain.strip():
                t.append_text(think)
                t.append("\n")

        # Cascade
        if self.name == "Dissect":
            cascade = self.cascade_panel.render(indent=f"{indent}\u2502   ")
            if cascade.plain.strip():
                t.append_text(cascade)

        # Subactions
        if self.subactions:
            t.append_text(self._render_subactions(f"{indent}\u2502   "))

        return t

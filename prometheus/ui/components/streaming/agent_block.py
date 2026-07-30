from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rich.style import Style
from rich.text import Text

from prometheus.ui.components.streaming.cascade_panel import CascadePanel
from prometheus.ui.components.streaming.progress_bar import (
    ProgressBar,
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


_NAME_COL_WIDTH = 9


class AgentBlock:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status: str = "pending"
        self.current_pane: str = "thinking"
        self.summary: str = ""
        self.subactions: list[SubactionNode] = []
        self.planning_items: list[str] = []
        self.acting_items: list[str] = []
        self.verifying_status: str = ""
        self.thinking_pane = ThinkingPane()
        self.cascade_panel = CascadePanel()
        self.details: dict[str, Any] = {}
        self.progress_bars: dict[str, ProgressBar] = {}
        self.seen: bool = False
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.token_count: int = 0
        self._expanded: bool = False
        self._focused: bool = False

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

        if self.name == "Dissect" and self.status in ("active", "done", "error"):
            t.append(" \u26a1 ", style=Style(bgcolor=self.color, bold=True, color="#FFFFFF"))
        elif self.status == "active":
            idx = int(tick * 1000 / _SPINNER_INTERVAL) % len(_SPINNER_FRAMES)
            spinner = _SPINNER_FRAMES[idx]
            t.append(f" {spinner} ", style=Style(bgcolor=self.color, bold=True, color="#FFFFFF"))
        elif self.status == "done":
            t.append(" \u2714 ", style=Style(bgcolor=Theme.success.hex, bold=True, color="#FFFFFF"))
        elif self.status == "error":
            t.append(" \u2718 ", style=Style(bgcolor=Theme.error.hex, bold=True, color="#FFFFFF"))
        else:
            t.append(" \u25cb ", style=str(Theme.muted))

        name_pad = _NAME_COL_WIDTH - len(self.name)
        if name_pad < 1:
            name_pad = 1
        t.append(f" {self.name}{' ' * name_pad}", style=f"bold {self.color}")

        dur = self._dur_str()
        if dur:
            t.append(f" \u00b7 {dur}", style=str(Theme.muted))

        if self.summary:
            t.append("  ", style=str(Theme.muted))
            t.append(self.summary, style=str(Theme.body))

        return t

    def _render_key_details(self, indent: str) -> Text:
        t = Text()
        if not self.details:
            return t

        relevant: list[str] = []

        if self.name == "Scout":
            for key in ("Task", "Modality", "Confidence", "Rows", "Features"):
                if key in self.details:
                    relevant.append(f"{key.lower()}={self.details[key]}")
            relevant = relevant[:3]

        elif self.name == "Forge":
            for key in ("Architecture", "Rationale", "Confidence", "Candidates"):
                if key in self.details:
                    val = self.details[key]
                    key_lower = key.lower()
                    if len(str(val)) > 40:
                        val = str(val)[:40] + "\u2026"
                    relevant.append(f"{key_lower}={val}")
            relevant = relevant[:2]

        elif self.name == "Furnace":
            for key in ("Epoch", "Best", "Loss", "AUC"):
                if key in self.details:
                    relevant.append(f"{key.lower()}={self.details[key]}")
            relevant = relevant[:2]

        elif self.name == "Dissect":
            for s in self.subactions:
                if "patch" in s.detail.lower() or "repair" in s.detail.lower():
                    relevant.append(s.detail)
                    break
            if not relevant:
                relevant.append("no patches needed")

        elif self.name == "Arbiter":
            pass

        elif self.name == "Harbor":
            if "Endpoint" in self.details:
                relevant.append(self.details["Endpoint"])
            if "ModelFormat" in self.details:
                relevant.append(f"[{self.details['ModelFormat']}]")

        if relevant:
            detail_str = "  ".join(relevant)
            t.append(f"{indent}   ")
            t.append(detail_str, style=str(Theme.muted))
            t.append("\n")

        return t

    def _render_full_content(self, indent: str, width: int) -> Text:
        pane_indent = f"{indent}\u2502   "
        t = Text()

        if self.planning_items:
            for item in self.planning_items:
                t.append(f"{pane_indent}\u25c6 ", style=str(Theme.info))
                t.append(item, style=str(Theme.body))
                t.append("\n")

        if self.acting_items:
            for item in self.acting_items:
                t.append(f"{pane_indent}\u25b6 ", style=str(Theme.warning))
                t.append(item, style=str(Theme.body))
                t.append("\n")

        if self.verifying_status:
            t.append(
                f"{pane_indent}\u2713? Verifying: {self.verifying_status}", style=str(Theme.info)
            )
            t.append("\n")

        if self.progress_bars:
            for key, bar in self.progress_bars.items():
                bar_text = bar.render()
                t.append(f"{pane_indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
                t.append_text(bar_text)
                t.append("\n")

        if self.thinking_pane.token_count > 0:
            think = self.thinking_pane.render(collapsed=False, width=width, indent=pane_indent)
            if think.plain.strip():
                t.append_text(think)
                t.append("\n")

        if self.name == "Dissect":
            cascade = self.cascade_panel.render(indent=pane_indent)
            if cascade.plain.strip():
                t.append_text(cascade)

        if self.subactions:
            for sub in self.subactions:
                t.append(f"{pane_indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
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

    def render_live(self, tick: float, width: int = 80) -> Text:
        indent = "   "
        pane_indent = f"{indent}\u2502   "
        t = Text()

        t.append_text(self._badge_line(tick))
        t.append("\n")

        if self.status == "active":
            if self.current_pane == "thinking" and self.thinking_pane.token_count > 0:
                think = self.thinking_pane.render(collapsed=True, width=width, indent=pane_indent)
                if think.plain.strip():
                    t.append_text(think)
                    t.append("\n")
            elif self.current_pane == "planning" and self.planning_items:
                for item in self.planning_items:
                    t.append(f"{pane_indent}\u25c6 ", style=str(Theme.info))
                    t.append(item, style=str(Theme.body))
                    t.append("\n")
            elif self.current_pane == "acting":
                if self.acting_items:
                    for item in self.acting_items:
                        t.append(f"{pane_indent}\u25b6 ", style=str(Theme.warning))
                        t.append(item, style=str(Theme.body))
                        t.append("\n")
                if self.progress_bars:
                    for key, bar in self.progress_bars.items():
                        bar_text = bar.render()
                        t.append(
                            f"{pane_indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector)
                        )
                        t.append_text(bar_text)
                        t.append("\n")
            elif self.current_pane == "verifying":
                if self.verifying_status:
                    t.append(
                        f"{pane_indent}\u2713? Verifying: {self.verifying_status}",
                        style=str(Theme.info),
                    )
                    t.append("\n")

        if self.current_pane != "acting" and self.progress_bars:
            for key, bar in self.progress_bars.items():
                bar_text = bar.render()
                t.append(f"{pane_indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
                t.append_text(bar_text)
                t.append("\n")

        if self.name == "Dissect":
            cascade = self.cascade_panel.render(indent=pane_indent)
            if cascade.plain.strip():
                t.append_text(cascade)

        if self.subactions:
            for sub in self.subactions:
                t.append(f"{pane_indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
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

    def render_finalized(self, width: int = 80) -> Text:
        indent = "   "
        t = Text()

        t.append_text(self._badge_line(0))
        t.append("\n")

        if self._expanded:
            t.append_text(self._render_full_content(indent, width))
        else:
            t.append_text(self._render_key_details(indent))

        return t

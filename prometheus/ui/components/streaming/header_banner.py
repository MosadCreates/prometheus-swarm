from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from rich.style import Style
from rich.text import Text

from prometheus.ui.theme import Theme

_AGENT_PIPELINE = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]
_AGENT_COLORS = {
    "Scout": Theme.agent_scout,
    "Forge": Theme.agent_forge,
    "Furnace": Theme.agent_furnace,
    "Dissect": Theme.agent_dissect,
    "Arbiter": Theme.agent_arbiter,
    "Harbor": Theme.agent_harbor,
}


@dataclass
class HeaderBanner:
    mission_id: str = ""
    problem_description: str = ""
    dataset_name: str = ""
    num_rows: int = 0
    version: str = "0.1.0"

    _status: str = "starting"
    _active_agent: str = ""
    _start_time: float = field(default_factory=time.monotonic)
    _gpu_name: str = "\u2014"
    _gpu_util: int = 0
    _memory_gb: float = 0.0

    _width: int = 80

    def update_width(self, width: int | None = None) -> None:
        if width is not None:
            self._width = width
        else:
            try:
                import shutil

                self._width = shutil.get_terminal_size().columns
            except Exception:
                self._width = 80

    @property
    def status(self) -> str:
        return self._status

    @property
    def active_agent(self) -> str:
        return self._active_agent

    def update_status(self, status: str, active_agent: str = "") -> None:
        self._status = status
        if active_agent:
            self._active_agent = active_agent

    def update_gpu(self, name: str, util: int) -> None:
        self._gpu_name = name
        self._gpu_util = max(0, min(100, util))

    def update_memory(self, gb: float) -> None:
        self._memory_gb = max(0.0, gb)

    @property
    def elapsed_seconds(self) -> int:
        return int(time.monotonic() - self._start_time)

    @property
    def elapsed_str(self) -> str:
        secs = self.elapsed_seconds
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def _status_badge(self) -> Text:
        status_colors = {
            "starting": Theme.warning,
            "running": Theme.info,
            "complete": Theme.success,
            "error": Theme.error,
            "detached": Theme.muted,
        }
        color = status_colors.get(self._status, Theme.secondary)
        status_labels = {
            "starting": "\u25cf STARTING",
            "running": "\u25b6 RUNNING",
            "complete": "\u2714 COMPLETE",
            "error": "\u2718 ERROR",
            "detached": "\u25cb DETACHED",
        }
        label = status_labels.get(self._status, self._status.upper())
        t = Text()
        t.append(label, style=f"bold {color}")
        return t

    def _pipeline_ribbon(self) -> Text:
        t = Text()
        t.append("Pipeline ", style=str(Theme.muted))
        for i, agent in enumerate(_AGENT_PIPELINE):
            if i > 0:
                t.append(" \u2192 ", style=str(Theme.tree_connector))
            color = _AGENT_COLORS.get(agent, Theme.secondary)
            t.append(agent, style=f"bold {color}")
        return t

    def render(self) -> Text:
        self.update_width()
        w = min(self._width - 2, 88)

        line = Text()

        line.append("\u256d", style=str(Theme.tree_connector))
        line.append("\u2500" * w, style=str(Theme.tree_connector))
        line.append("\u256e\n", style=str(Theme.tree_connector))

        line.append("\u2502", style=str(Theme.tree_connector))
        line.append(" ", style=str(Theme.tree_connector))
        display_id = self.mission_id[:20] if self.mission_id else "\u2014"
        line.append(display_id, style=f"bold {Theme.accent}")
        line.append(" ", style=str(Theme.tree_connector))
        if self.problem_description:
            desc = self.problem_description[:50]
            line.append(f"\u201c{desc}\u201d", style=str(Theme.body))
        line.append(" " * max(1, w - len(display_id) - len(self.problem_description[:50]) - 4))
        line.append(" ", style=str(Theme.tree_connector))
        line.append(self.elapsed_str, style=str(Theme.muted))
        line.append("\n", style=str(Theme.tree_connector))

        # Dataset info
        if self.dataset_name:
            line.append("\u2502", style=str(Theme.tree_connector))
            line.append(" ", style=str(Theme.tree_connector))
            line.append("Dataset", style=str(Theme.muted))
            line.append("  ", style=str(Theme.tree_connector))
            ds = self.dataset_name
            if self.num_rows:
                ds += f" \u00b7 {self.num_rows:,} rows"
            line.append(ds, style=str(Theme.body))
            line.append(" " * max(1, w - len(ds) - 10))
            line.append("\n", style=str(Theme.tree_connector))

        # Pipeline ribbon
        line.append("\u2502", style=str(Theme.tree_connector))
        line.append(" ", style=str(Theme.tree_connector))
        line.append_text(self._pipeline_ribbon())
        line.append(" " * max(1, w - 60))
        line.append("\n", style=str(Theme.tree_connector))

        # Status and active agent
        line.append("\u2502", style=str(Theme.tree_connector))
        line.append(" ", style=str(Theme.tree_connector))
        line.append_text(self._status_badge())
        if self._active_agent:
            agent_color = _AGENT_COLORS.get(self._active_agent, Theme.secondary)
            line.append("  ", style=str(Theme.tree_connector))
            line.append("Active: ", style=str(Theme.muted))
            line.append(self._active_agent, style=f"bold {agent_color}")
        line.append(" " * max(1, w - 30))
        line.append("\n", style=str(Theme.tree_connector))

        # Bottom border
        line.append("\u2570", style=str(Theme.tree_connector))
        line.append("\u2500" * w, style=str(Theme.tree_connector))
        line.append("\u256f", style=str(Theme.tree_connector))

        return line

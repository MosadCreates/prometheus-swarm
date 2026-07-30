from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from prometheus.ui.theme import Theme

AGENT_ORDER = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]

AGENT_COLORS = {
    "Scout": Theme.agent_scout,
    "Forge": Theme.agent_forge,
    "Furnace": Theme.agent_furnace,
    "Dissect": Theme.agent_dissect,
    "Arbiter": Theme.agent_arbiter,
    "Harbor": Theme.agent_harbor,
}

STATE_ICONS = {
    "pending": "\u25cb",
    "running": "\u25b6",
    "complete": "\u2714",
    "error": "\u2718",
    "disabled": "\u2014",
}

STATE_COLORS = {
    "pending": str(Theme.muted),
    "running": str(Theme.info),
    "complete": str(Theme.success),
    "error": str(Theme.error),
    "disabled": str(Theme.muted),
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

STATUS_LABELS = {
    "starting": "\u25cf STARTING",
    "running": "\u25b6 running",
    "complete": "\u2714 complete",
    "error": "\u2718 error",
    "cancelled": "\u25cb cancelled",
}

STATUS_COLORS = {
    "starting": Theme.warning,
    "running": Theme.info,
    "complete": Theme.success,
    "error": Theme.error,
    "cancelled": Theme.muted,
}


@dataclass
class HeaderBanner:
    mission_id: str = ""
    problem_description: str = ""
    dataset_name: str = ""
    num_rows: int = 0
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

    def _agent_spinner(self, tick: float) -> str:
        idx = int(tick * 1000 / 100) % len(_SPINNER_FRAMES)
        return _SPINNER_FRAMES[idx]

    def _pipeline_ribbon(self, agent_states: dict[str, str], tick: float) -> Text:
        t = Text()
        for i, agent in enumerate(AGENT_ORDER):
            if i > 0:
                t.append(" \u2500\u2500 ", style=str(Theme.tree_connector))

            state = agent_states.get(agent, "pending")
            if state == "running":
                icon = self._agent_spinner(tick)
            else:
                icon = STATE_ICONS.get(state, "\u25cb")
            color = STATE_COLORS.get(state, str(Theme.muted))
            agent_color = AGENT_COLORS.get(agent, Theme.secondary)

            t.append(icon, style=color)
            t.append(" ")
            t.append(agent, style=f"bold {agent_color}")
        return t

    def render(
        self,
        agent_states: dict[str, str] | None = None,
        status: str = "starting",
        elapsed_seconds: int = 0,
        tick: float = 0.0,
    ) -> Text:
        self.update_width()
        w = min(self._width - 2, 96)
        agent_states = agent_states or {}
        slug = self.mission_id[:20] if self.mission_id else "\u2014"
        elapsed = f"{elapsed_seconds // 60:02d}:{elapsed_seconds % 60:02d}"
        sc = STATUS_COLORS.get(status, Theme.secondary)
        status_label = STATUS_LABELS.get(status, status.upper())

        # Dataset string
        ds_parts = []
        if self.dataset_name:
            ds_parts.append(self.dataset_name)
        if self.num_rows:
            ds_parts.append(f"({self.num_rows:,} rows)")
        ds_str = "  ".join(ds_parts) if ds_parts else ""

        # ── Top border with slug and elapsed ──
        top = Text()
        top.append("\u250c", style=str(Theme.tree_connector))
        top.append("\u2500", style=str(Theme.tree_connector))
        inner_w = w - 2
        slug_end = len(slug) + 2
        right_content = f"  Elapsed  {elapsed}"
        top.append(slug, style=f"bold {Theme.accent}")
        pad = inner_w - slug_end - len(right_content)
        if pad > 0:
            top.append("\u2500" * pad, style=str(Theme.tree_connector))
        top.append(right_content, style=str(Theme.muted))
        top.append("\u2500", style=str(Theme.tree_connector))
        top.append("\u2510\n", style=str(Theme.tree_connector))

        # ── Line 1 — dataset + elapsed + status ──
        line1 = Text()
        line1.append("\u2502 ", style=str(Theme.tree_connector))
        status_styled = Text()
        status_styled.append(status_label, style=f"bold {sc}")
        right_part_len = len("  Elapsed  ") + len(elapsed) + len(status_label)
        ds_line = f"Dataset  {ds_str}" if ds_str else ""
        pad1 = inner_w - len(ds_line) - right_part_len
        if pad1 < 1:
            pad1 = 1
        line1.append(ds_line, style=str(Theme.body))
        line1.append(" " * pad1)
        line1.append(f"  Elapsed  {elapsed}  ", style=str(Theme.muted))
        line1.append_text(status_styled)
        line1.append(" \u2502\n", style=str(Theme.tree_connector))

        # ── Line 2 — pipeline ribbon ──
        line2 = Text()
        line2.append("\u2502 ", style=str(Theme.tree_connector))
        ribbon = self._pipeline_ribbon(agent_states, tick)
        ribbon_len = len(ribbon.plain)
        pad2 = inner_w - ribbon_len
        if pad2 < 1:
            pad2 = 1
        line2.append_text(ribbon)
        line2.append(" " * pad2)
        line2.append("\u2502\n", style=str(Theme.tree_connector))

        # ── Bottom border ──
        bottom = Text()
        bottom.append("\u2514", style=str(Theme.tree_connector))
        bottom.append("\u2500" * inner_w, style=str(Theme.tree_connector))
        bottom.append("\u2518", style=str(Theme.tree_connector))

        out = Text()
        out.append_text(top)
        out.append_text(line1)
        out.append_text(line2)
        out.append_text(bottom)
        return out

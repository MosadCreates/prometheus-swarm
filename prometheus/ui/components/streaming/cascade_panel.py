from __future__ import annotations

from rich.text import Text

from prometheus.ui.theme import Theme

LEVEL_ICONS = {
    "done": "\u25cf",
    "active": "\u25d0",
    "pending": "\u25cb",
    "error": "\u2718",
    "skipped": "\u2014",
}

LEVEL_COLORS = {
    "done": str(Theme.cascade_done),
    "active": str(Theme.cascade_active),
    "pending": str(Theme.cascade_pending),
    "error": str(Theme.cascade_error),
    "skipped": str(Theme.disabled),
}

LEVEL_LABELS = [
    "cached fingerprint",
    "deterministic rule",
    "compiled template",
    "LLM-assisted repair",
    "escalate",
]


class CascadePanel:
    def __init__(self) -> None:
        self._levels: list[dict[str, str]] = [{"state": "pending", "detail": ""} for _ in range(5)]

    def set_level_state(self, level: int, state: str, detail: str = "") -> None:
        if 0 <= level < 5:
            self._levels[level]["state"] = state
            if detail:
                self._levels[level]["detail"] = detail

    def reset(self) -> None:
        for lv in self._levels:
            lv["state"] = "pending"
            lv["detail"] = ""

    def render(self, indent: str = "   \u2502   ") -> Text:
        t = Text()
        t.append(f"{indent}Cascade\n", style=str(Theme.muted))
        for i, lv in enumerate(self._levels):
            state = lv["state"]
            icon = LEVEL_ICONS.get(state, "\u25cb")
            color = LEVEL_COLORS.get(state, str(Theme.cascade_pending))
            label = LEVEL_LABELS[i] if i < len(LEVEL_LABELS) else f"level {i}"
            detail = lv["detail"]

            t.append(f"{indent}\u251c\u2500\u2500 ", style=str(Theme.tree_connector))
            t.append(f"{icon} ", style=color)
            t.append(f"{i} ", style=str(Theme.muted))
            t.append(label, style=color)
            if detail:
                t.append(f" \u2014 {detail}", style=str(Theme.muted))
            t.append("\n", style=str(Theme.tree_connector))
        return t

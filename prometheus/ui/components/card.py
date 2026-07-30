from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rich.panel import Panel
from rich.text import Text

from prometheus.ui.theme import Theme


@dataclass
class StatusCard:
    """A small decision/status card rendered as a Rich Panel.

    Usage:
        card = StatusCard(
            title="Architecture",
            value="LightGBM",
            subtitle="Optimal for structured tabular data",
            status="ready",
        )
        console.print(card.render())
    """

    title: str
    value: str
    subtitle: str | None = None
    status: str = "ready"  # "ready", "active", "done", "failed"
    accent: Any = Theme.agent_forge

    def render(self) -> Panel:
        accent_str = str(self.accent)
        success_str = str(Theme.success)
        muted_str = str(Theme.muted)
        primary_str = str(Theme.primary)

        icon_map = {"ready": "\u25cf", "active": "\u25cf", "done": "\u2713", "failed": "\u2717"}
        color_map = {
            "ready": accent_str,
            "active": accent_str,
            "done": success_str,
            "failed": str(Theme.error),
        }
        icon = icon_map.get(self.status, "\u25cf")
        color = color_map.get(self.status, accent_str)

        t = Text()
        t.append(f"  {icon}  ", style=color)
        t.append(f"{self.title}", style=f"bold {primary_str}")
        t.append(f"  {self.value}", style=accent_str)
        if self.subtitle:
            t.append(f"\n     [{muted_str}]{self.subtitle}[/]")

        return Panel(
            t,
            border_style=color,
            padding=(0, 1),
            box=None,
        )

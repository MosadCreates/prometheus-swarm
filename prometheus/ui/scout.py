"""Live-updating Scout phase UI — premium activity panel, status header, progress bar."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from prometheus.ui.theme import Theme

_SCOUT_COLOR = str(Theme.agent_scout)
_SUCCESS_COLOR = str(Theme.success)
_ERROR_COLOR = str(Theme.error)
_MUTED_COLOR = str(Theme.muted)
_BORDER_COLOR = str(Theme.border)

_TOTAL_STEPS = 6


class ScoutUI:
    """Live-updating Scout phase display.

    Usage:
        with ScoutUI(console, job_id) as ui:
            ui.task("Loading dataset...")
            # ... backend work ...
            ui.task("Inspecting columns...")
            ui.complete()
    """

    def __init__(self, console: Console, job_id: str) -> None:
        self.console = console
        self.job_id = job_id
        self.tasks: list[dict[str, str]] = []
        self.status = "Preparing"
        self._start: float = 0.0
        self._live: Live | None = None

    def __enter__(self) -> ScoutUI:
        self._start = time.time()
        self._live = Live(
            self._build(),
            console=self.console,
            refresh_per_second=4,
            vertical_overflow="visible",
        )
        self._live.__enter__()
        return self

    def __exit__(self, *args: Any) -> None:
        if self._live is not None:
            try:
                self._live.__exit__(*args)
            except Exception:
                pass

    def task(self, message: str) -> None:
        """Mark previous running task complete, start a new one."""
        for t in reversed(self.tasks):
            if t["status"] == "running":
                t["status"] = "done"
                break
        self.tasks.append({"message": message, "status": "running"})
        self.status = message.rstrip(".").rstrip("...")
        self._refresh()

    def complete(self) -> None:
        """Mark current running task done, set status to Complete."""
        for t in self.tasks:
            if t["status"] == "running":
                t["status"] = "done"
        self.status = "Complete"
        self._refresh()

    def fail(self, reason: str) -> None:
        """Mark current running task failed, set error status."""
        for t in self.tasks:
            if t["status"] == "running":
                t["status"] = "failed"
        self.status = f"Failed — {reason}"
        self._refresh()

    def _refresh(self) -> None:
        if self._live is not None:
            try:
                self._live.update(self._build())
            except Exception:
                pass

    def _progress_pct(self) -> float:
        if not self.tasks:
            return 0.0
        done = sum(1 for t in self.tasks if t["status"] == "done")
        return min(done / _TOTAL_STEPS, 0.95)

    def _build(self) -> Panel:
        lines: list[str] = []

        # Status header
        lines.append(f"  [bold]Status[/]    [{_SCOUT_COLOR}]{self._esc(self.status)}[/]")
        lines.append(f"  [bold]Mission[/]   [{_MUTED_COLOR}]{self._esc(self.job_id)}[/]")

        elapsed = time.time() - self._start
        elapsed_str = (
            f"{int(elapsed)}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        )
        lines.append(f"  [bold]Elapsed[/]   [{_MUTED_COLOR}]{elapsed_str}[/]")
        lines.append("")

        # Progress bar (text-based, 20 chars)
        pct = self._progress_pct()
        filled = int(pct * 20)
        empty = 20 - filled
        bar = f"[{_SCOUT_COLOR}]{'█' * filled}[/][{_BORDER_COLOR}]{'░' * empty}[/]"
        lines.append(f"  {bar}  [{_SCOUT_COLOR}]{pct * 100:.0f}%[/]")
        lines.append("")

        # Activity list
        lines.append("  [bold]Activities[/]")
        lines.append("")

        for t in self.tasks:
            msg = self._esc(t["message"])
            if t["status"] == "done":
                lines.append(f"  [{_SUCCESS_COLOR}]✓[/]  {msg}")
            elif t["status"] == "running":
                lines.append(f"  [{_SCOUT_COLOR}]⟳[/]  {msg}")
            elif t["status"] == "failed":
                lines.append(f"  [{_ERROR_COLOR}]✗[/]  {msg}")

        return Panel(
            "\n".join(lines),
            title=f"[bold {_SCOUT_COLOR}]|\u25c6| Scout — Mission Intelligence Agent[/]",
            border_style=_SCOUT_COLOR,
            padding=(1, 2),
        )

    @staticmethod
    def _esc(text: str) -> str:
        """Escape rich markup characters."""
        return text.replace("[", "\\[").replace("]", "\\]")

from __future__ import annotations

from typing import Any

from prometheus.ui.theme import Theme


class Stepper:
    """Reusable progress stepper with active/completed/pending visual states.

    Usage:
        s = Stepper(["Step A", "Step B", "Step C"], active_color=Theme.agent_forge)
        s.advance()          # mark 0 done, advance to 1
        print(s.render())
        s.set_status(1, "failed")
        print(s.render())
    """

    def __init__(
        self,
        steps: list[str],
        active_color: Any = Theme.agent_forge,
    ) -> None:
        self.steps = steps
        self.active_color = str(active_color)
        self.done: set[int] = set()
        self.active: int = 0
        self._failed: int | None = None

    def advance(self) -> None:
        """Mark current step as done, advance active pointer."""
        if self._failed is not None:
            return
        if self.active < len(self.steps):
            self.done.add(self.active)
            self.active += 1

    def set_status(self, index: int, status: str) -> None:
        """Override a step's status: 'done', 'active', 'failed', 'pending'."""
        if status == "done":
            self.done.add(index)
            if index == self.active:
                self.active += 1
        elif status == "active":
            self.active = index
            self._failed = None
        elif status == "failed":
            self._failed = index
            self.done.discard(index)
        elif status == "pending":
            self.done.discard(index)
            if self._failed == index:
                self._failed = None
            if self.active == index:
                self.active = max(0, index - 1)

    @property
    def total(self) -> int:
        return len(self.steps)

    @property
    def is_complete(self) -> bool:
        return len(self.done) == len(self.steps) or self.active >= len(self.steps)

    def _status_at(self, i: int) -> str:
        if i == self._failed:
            return "failed"
        if i in self.done:
            return "done"
        if i == self.active:
            return "active"
        return "pending"

    def render(self) -> str:
        """Return the rendered stepper as a Rich-markup string."""
        lines: list[str] = []
        for i, label in enumerate(self.steps):
            s = self._status_at(i)
            if s == "done":
                lines.append(
                    f"  [{str(Theme.success)}]\u2713[/]  " f"[{str(Theme.success)}]{label}[/]"
                )
            elif s == "active":
                lines.append(
                    f"  [{self.active_color}]\u25cf[/]  " f"[bold {self.active_color}]{label}[/]"
                )
            elif s == "failed":
                lines.append(f"  [{str(Theme.error)}]\u2717[/]  " f"[{str(Theme.error)}]{label}[/]")
            else:
                lines.append(
                    f"  [{str(Theme.disabled)}]\u25cb[/]  " f"[{str(Theme.disabled)}]{label}[/]"
                )
        return "\n".join(lines)

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.theme import Theme

SPINNER_FRAMES = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]  # ◐ ◓ ◑ ◒
LABEL_WIDTH = 10
GAP = "  "


class MotionStep:
    """A single pipeline step with pending / active / done / failed states.

    Renders as::

        pending:  "  ○  Scout      Waiting..."
        active:   "  ⟳  Scout      Profiling 7,043 rows..."
        done:     "  ✓  Scout      Rows: 7,043 · Imbalance 1:3.5"
        failed:   "  ✗  Scout      File not found"
    """

    def __init__(self, label: str, color: str | Theme = Theme.muted) -> None:
        self.label = label
        self.color = str(color)
        self.status: str = "pending"
        self.value: str = ""

    def start(self, value: str = "") -> None:
        self.status = "active"
        self.value = value

    def update(self, value: str) -> None:
        self.status = "active"
        self.value = value

    def done(self, value: str = "") -> None:
        self.status = "done"
        if value:
            self.value = value

    def fail(self, value: str = "") -> None:
        self.status = "failed"
        if value:
            self.value = value

    def reset(self) -> None:
        self.status = "pending"
        self.value = ""

    def render(self, frame: int) -> Text:
        t = Text()
        status = self.status
        if status == "pending":
            t.append(f"{GAP}\u25cb  ", style=str(Theme.disabled))
            t.append(f"{self.label:<{LABEL_WIDTH}}", style=str(Theme.disabled))
            t.append(GAP, style=str(Theme.disabled))
            t.append(self.value or "Waiting", style=str(Theme.disabled))
        elif status == "active":
            spinner = SPINNER_FRAMES[frame % len(SPINNER_FRAMES)]
            t.append(f"{GAP}{spinner}  ", style=self.color)
            t.append(f"{self.label:<{LABEL_WIDTH}}", style=Style(bold=True, color=self.color))
            t.append(GAP, style=str(Theme.muted))
            t.append(self.value or "\u2026", style=str(Theme.muted))
        elif status == "done":
            t.append(f"{GAP}\u2713  ", style=str(Theme.success))
            t.append(f"{self.label:<{LABEL_WIDTH}}", style=self.color)
            t.append(GAP, style=str(Theme.muted))
            t.append(self.value, style=str(Theme.muted))
        elif status == "failed":
            t.append(f"{GAP}\u2717  ", style=str(Theme.error))
            t.append(f"{self.label:<{LABEL_WIDTH}}", style=self.color)
            t.append(GAP, style=str(Theme.muted))
            t.append(self.value or "Failed", style=str(Theme.muted))
        return t

    def render_plain(self) -> str:
        status = self.status
        if status == "pending":
            return f"  o  {self.label:<{LABEL_WIDTH}}  {self.value or 'Waiting'}"
        if status == "active":
            return f"  >  {self.label:<{LABEL_WIDTH}}  {self.value or '...'}"
        if status == "done":
            return f"  OK {self.label:<{LABEL_WIDTH}}  {self.value}"
        if status == "failed":
            return f"  XX {self.label:<{LABEL_WIDTH}}  {self.value or 'Failed'}"
        return ""


class MotionPipeline:
    """A plain-text pipeline view showing sequential phase steps.

    Previously wrapped ``rich.live.Live`` for animated spinner display, but
    Live's cursor-positioning logic (``position_cursor()``) produced persistent
    ghost "○ Waiting" rows whenever the step count changed (Dissect insertion)
    or any ``console.print()`` was called during the Live context.  The plain-
    text fallback is simpler and is never wrong: every line is written exactly
    once and never needs to be erased.

    Falls back to plain text when ``sys.stdout`` is not a TTY or when
    ``verbose=True``.

    Accepts both index (``int``) and label (``str``) for step identifiers::

        pipeline.start(0, "Loading dataset...")
        pipeline.done("Scout", "7,043 rows")   # label-based

    Usage::

        steps = [
            MotionStep("Scout", Theme.agent_scout),
            MotionStep("Forge", Theme.agent_forge),
        ]
        with MotionPipeline(console, steps) as pipeline:
            pipeline.start("Scout", "Loading dataset...")
            pipeline.done("Scout", "7,043 rows")
            pipeline.start("Forge", "Selecting architecture...")

    Steps can be inserted dynamically at runtime via ``insert()``::

        pipeline.insert(2, MotionStep("Dissect", Theme.agent_dissect))
        pipeline.start("Dissect", "Analyzing crash...")
    """

    def __init__(
        self,
        console: Console,
        steps: list[MotionStep],
        *,
        verbose: bool = False,
        log_path: str | None = None,
    ) -> None:
        self.console = console
        self.steps = steps
        self.verbose = verbose
        self._closed = False
        self._label_to_idx: dict[str, int] = {}
        self._rebuild_index()

        if log_path:
            import io

            self._log_file = io.open(log_path, "a", encoding="utf-8", buffering=1)
        else:
            self._log_file = None

    def __enter__(self) -> MotionPipeline:
        return self

    def __exit__(self, *args: Any) -> None:
        self._closed = True
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass

    # ── Public API ──────────────────────────────────────────────────────────

    def start(self, step_id: int | str, value: str = "") -> None:
        idx = self._resolve_index(step_id)
        self.steps[idx].start(value)
        self._emit(idx, action="start")

    def update(self, step_id: int | str, value: str) -> None:
        idx = self._resolve_index(step_id)
        self.steps[idx].update(value)
        self._emit(idx, action="update")

    def done(self, step_id: int | str, value: str = "") -> None:
        idx = self._resolve_index(step_id)
        self.steps[idx].done(value)
        self._emit(idx, action="done")

    def fail(self, step_id: int | str, value: str = "") -> None:
        idx = self._resolve_index(step_id)
        self.steps[idx].fail(value)
        self._emit(idx, action="fail")

    def insert(self, index: int, step: MotionStep) -> None:
        """Insert a step at *index*, shifting later steps right."""
        self.steps.insert(index, step)
        self._rebuild_index()
        # Plain text mode: no Live refresh needed

    def set_log_path(self, path: str) -> None:
        """Set or update the log file path after construction."""
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
        import io

        self._log_file = io.open(path, "a", encoding="utf-8", buffering=1)

    # ── Internals ───────────────────────────────────────────────────────────

    def _resolve_index(self, step_id: int | str) -> int:
        if isinstance(step_id, str):
            if step_id not in self._label_to_idx:
                raise KeyError(f"Step '{step_id}' not found. Available: {list(self._label_to_idx)}")
            return self._label_to_idx[step_id]
        if step_id < 0 or step_id >= len(self.steps):
            raise IndexError(
                f"Pipeline step index {step_id} out of range (0..{len(self.steps) - 1})"
            )
        return step_id

    def _rebuild_index(self) -> None:
        self._label_to_idx = {s.label: i for i, s in enumerate(self.steps)}

    def _emit(self, index: int, action: str = "update") -> None:
        if self._closed:
            return

        step = self.steps[index]
        plain = step.render_plain()

        if self._log_file is not None:
            try:
                self._log_file.write(f"{plain}\n")
            except Exception:
                pass

        # Suppress intermediate update calls in non-verbose mode to
        # keep the output concise (only start / done / fail are shown).
        if not self.verbose and action == "update":
            return
        try:
            self.console.print(plain, markup=False, highlight=False)
        except Exception:
            self.console.print(plain)

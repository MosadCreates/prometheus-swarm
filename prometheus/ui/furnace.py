"""Live-updating Furnace phase UI — training dashboard, metric evolution, stepper."""

from __future__ import annotations

import re
import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from prometheus.ui.components.stepper import Stepper
from prometheus.ui.theme import Theme

_FURNACE_COLOR = str(Theme.agent_furnace)
_FURNACE_GLYPH = "\u25c6"
_SUCCESS = str(Theme.success)
_ERROR = str(Theme.error)
_MUTED = str(Theme.muted)
_PRIMARY = str(Theme.primary)
_SECONDARY = str(Theme.secondary)
_WARNING = str(Theme.warning)
_BORDER = str(Theme.border)

_FURNACE_STEPS = [
    "Validating Inputs",
    "Preparing Workspace",
    "Docker Ready",
    "Container Started",
    "Training Model",
    "Saving Checkpoint",
    "Publishing Event",
]

_METRIC_PATTERN = re.compile(r"(AUC|ROC AUC|Accuracy|RMSE|MAE|F1)[:\s]*([\d.]+)", re.IGNORECASE)
_TRIAL_PATTERN = re.compile(r"Trial\s+(\d+)", re.IGNORECASE)
_BEST_PATTERN = re.compile(r"(Best|best)[:\s]*([\d.]+)")


def _esc(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _header_panel(job_id: str) -> Panel:
    """Cinematic launch header."""
    lines = [
        "",
        f"  [{_FURNACE_COLOR}]{_FURNACE_GLYPH} Furnace[/]",
        f"  [{_MUTED}]Training & Optimization Engine[/]",
        f"  [{_MUTED}]Mission  {_esc(job_id)}[/]",
        "",
    ]
    return Panel(
        "\n".join(lines),
        border_style=_FURNACE_COLOR,
        padding=(0, 2),
    )


def _handoff_panel() -> Panel:
    """Premium hand-off transition to Arbiter."""
    lines = [
        "",
        f"  [{_SUCCESS}]\u2713 Furnace completed successfully[/]",
        f"  [{_MUTED}]  Model optimized[/]",
        f"  [{_MUTED}]  Checkpoint finalized[/]",
        f"  [{_MUTED}]  Evaluation package prepared[/]",
        "",
        f"  [{_FURNACE_COLOR}]Handing mission to Arbiter ...[/]",
        "",
    ]
    return Panel(
        "\n".join(lines),
        border_style=_FURNACE_COLOR,
        padding=(1, 2),
    )


def _summary_panel(result: dict[str, Any], job_id: str) -> Panel:
    """Premium training summary dashboard."""
    total_epochs = result.get("total_epochs", result.get("total_trials", "?"))
    metric_val = result.get("best_metric", 0)
    metric_name = result.get("metric_name", "AUC").upper()
    training_time = result.get("training_time", 0)

    time_str = ""
    if training_time:
        if training_time > 60:
            mins = int(training_time // 60)
            secs = int(training_time % 60)
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{training_time:.0f}s"

    def section(title: str) -> str:
        return f"  [{_MUTED}]\u2501 {title}[/]"

    def item(label: str, value: str) -> str:
        return f"    [bold {_PRIMARY}]{label}[/]  [{_PRIMARY}]{_esc(value)}[/]"

    def sub(label: str, value: str) -> str:
        return f"    [{_MUTED}]{label}[/]  [{_MUTED}]{_esc(value)}[/]"

    parts: list[str] = [""]
    parts.append(section("Model"))
    parts.append(item("Status", "Completed"))
    if time_str:
        parts.append(item("Duration", time_str))
    parts.append("")

    parts.append(section("Performance"))
    parts.append(
        item(
            f"Best {metric_name}",
            f"{metric_val:.4f}" if isinstance(metric_val, (int, float)) else str(metric_val),
        )
    )
    parts.append(item("Trials", str(total_epochs)))
    parts.append("")

    parts.append(section("Artifacts"))
    parts.append(f"    [{_SUCCESS}]\u2713[/]  Checkpoint Saved")
    parts.append(f"    [{_SUCCESS}]\u2713[/]  Metrics Collected")
    parts.append(f"    [{_SUCCESS}]\u2713[/]  TRAINING_COMPLETE Published")
    parts.append("")

    parts.append(section("Environment"))
    parts.append(sub("Job", job_id))
    checkpoint = result.get("checkpoint_path", "")
    parts.append(sub("Checkpoint", checkpoint))

    return Panel(
        "\n".join(parts),
        title=f"[bold {_FURNACE_COLOR}]|{_FURNACE_GLYPH}| Furnace \u2014 Training Report[/]",
        border_style=_FURNACE_COLOR,
        padding=(1, 2),
    )


class FurnaceUI:
    """Live-updating Furnace phase display with stepper, training dashboard, and report.

    Usage:
        furnace = FurnaceUI(console, job_id)
        furnace.launch()
        # ... agent.run(progress_callback=furnace.step) ...
        furnace.summary(result)
        furnace.handoff()
    """

    def __init__(self, console: Console, job_id: str, model_name: str = "") -> None:
        self.console = console
        self.job_id = job_id
        self._stepper = Stepper(_FURNACE_STEPS, active_color=Theme.agent_furnace)
        self._model_name = model_name or "Model"
        self._live: Live | None = None
        self._phase: str = "launch"  # launch → stepper → training → done
        self._header_printed = False

        # Training state
        self._best_metric: float = 0.0
        self._prev_best: float = 0.0
        self._metric_name: str = "AUC"
        self._current_metric: float = 0.0
        self._trials: int = 0
        self._total_trials: int = 30
        self._container_status: str = "Launching"

    # ── Phase 1: Launch ─────────────────────────────────────────────────

    def launch(self) -> None:
        """Print cinematic header and start Live with stepper."""
        self._start = time.time()
        self.console.print()
        self.console.print(_header_panel(self.job_id))
        self.console.print()
        self._header_printed = True

        self._live = Live(
            self._build_stepper(),
            console=self.console,
            refresh_per_second=4,
            vertical_overflow="visible",
        )
        self._live.__enter__()

    # ── Phase 2: Stepper / Training updates ──────────────────────────────

    def step(self, message: str) -> None:
        """Called by the agent progress callback. Advances stepper or updates training."""
        if not self._header_printed:
            self.launch()

        msg = message.strip()

        # Detect transition to training phase
        if "started" in msg.lower() and "training" in msg.lower():
            self._stepper.advance()  # Container Started → advance
            self._stepper.advance()  # advance to Training Model
            self._phase = "training"
            self._container_status = "Running"
            self._refresh()
            return

        if "complete" in msg.lower():
            return

        # During training, handle metric/trial callbacks
        if self._phase == "training":
            self._on_training_msg(msg)
            return

        # Stepper phase — advance through setup steps
        self._stepper.advance()
        self._refresh()

    def _on_training_msg(self, msg: str) -> None:
        """Parse training log lines and update the live dashboard."""
        changed = False

        # Parse trial info
        trial_m = _TRIAL_PATTERN.search(msg)
        if trial_m:
            self._trials = int(trial_m.group(1))
            changed = True

        # Parse metric value
        metric_m = _METRIC_PATTERN.search(msg)
        if metric_m:
            name = metric_m.group(1).upper()
            val = float(metric_m.group(2))
            self._metric_name = name if name != "ROC AUC" else "AUC"
            self._current_metric = val

            # Track best metric
            old_best = self._best_metric
            if self._metric_name == "RMSE" or self._metric_name == "MAE":
                self._best_metric = val if self._best_metric == 0.0 else min(self._best_metric, val)
            else:
                self._best_metric = max(self._best_metric, val)

            if self._best_metric != old_best:
                self._prev_best = old_best
                changed = True

        # Parse best pattern (sometimes emitted separately)
        best_m = _BEST_PATTERN.search(msg)
        if best_m:
            val = float(best_m.group(2))
            if val != self._best_metric:
                self._prev_best = self._best_metric
                self._best_metric = val
                changed = True

        if changed:
            self._refresh()

    # ── Phase 3: Summary (static) ────────────────────────────────────────

    def summary(self, result: dict[str, Any]) -> None:
        """Stop Live and print the training report panel."""
        self._cleanup_live()
        self.console.print()
        self.console.print(_summary_panel(result, self.job_id))
        self.console.print()

    # ── Phase 4: Hand-off (static) ───────────────────────────────────────

    def handoff(self) -> None:
        """Print hand-off animation to Arbiter."""
        time.sleep(0.3)
        self.console.print(_handoff_panel())
        self.console.print()

    # ── Error ────────────────────────────────────────────────────────────

    def error(self, reason: str) -> None:
        """Display error panel."""
        self._cleanup_live()
        self.console.print()
        panel = Panel(
            f"[{_ERROR}]\u2717 |{_FURNACE_GLYPH}| Furnace training failed[/]\n"
            f"  [{_MUTED}]Job: {_esc(self.job_id)}[/]\n"
            f"  [{_MUTED}]Reason: {_esc(reason)}[/]",
            title="[bold]Furnace Error[/]",
            border_style=_ERROR,
            padding=(1, 2),
        )
        self.console.print(panel)
        self.console.print()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _cleanup_live(self) -> None:
        if self._live is not None:
            try:
                self._live.__exit__(None, None, None)
            except Exception:
                pass
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            try:
                r = self._build_training() if self._phase == "training" else self._build_stepper()
                self._live.update(r)
            except Exception:
                pass

    def _build_stepper(self) -> Panel:
        """Build the stepper panel (pre-training phase)."""
        elapsed = time.time() - self._start
        elapsed_str = (
            f"{int(elapsed)}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        )

        lines: list[str] = []
        lines.append(self._stepper.render())
        lines.append("")
        lines.append(f"  [{_MUTED}]Elapsed: {elapsed_str}[/]")

        return Panel(
            "\n".join(lines),
            title=f"[bold {_FURNACE_COLOR}]|{_FURNACE_GLYPH}| Furnace \u2014 Execution[/]",
            border_style=_FURNACE_COLOR,
            padding=(1, 2),
        )

    def _build_training(self) -> Panel:
        """Build the training dashboard (during training)."""
        elapsed = time.time() - self._start
        elapsed_str = self._format_elapsed(elapsed)
        pct = (self._trials / self._total_trials * 100) if self._total_trials else 0

        # Progress bar
        filled = int(pct / 100 * 20)
        empty = 20 - filled
        bar = f"[{_FURNACE_COLOR}]{'█' * filled}[/][{_BORDER}]{'░' * empty}[/]"

        lines: list[str] = []

        # Progress bar row
        lines.append(f"  {bar}  [{_FURNACE_COLOR}]{pct:.0f}%[/]")
        lines.append("")

        # Metric display
        improvement = ""
        if self._prev_best > 0 and self._best_metric > self._prev_best:
            delta = self._best_metric - self._prev_best
            improvement = f"  [{_SUCCESS}]\u2191 +{delta:.4f}[/]"
        elif self._prev_best > 0 and self._best_metric < self._prev_best:
            delta = self._prev_best - self._best_metric
            improvement = f"  [{_WARNING}]\u2193 -{delta:.4f}[/]"

        metric_color = _SUCCESS if self._best_metric >= self._prev_best > 0 else _PRIMARY
        lines.append(
            f"  [bold {_PRIMARY}]Best {self._metric_name}[/]  [{metric_color}]{self._best_metric:.4f}[/]{improvement}"
        )
        lines.append("")

        # Stats row
        lines.append(
            f"  [bold {_PRIMARY}]Trials[/]     [{_SECONDARY}]{self._trials} / {self._total_trials}[/]"
        )
        lines.append(f"  [bold {_PRIMARY}]Elapsed[/]    [{_SECONDARY}]{elapsed_str}[/]")
        status_color = _SUCCESS if self._container_status == "Running" else _FURNACE_COLOR
        lines.append(
            f"  [bold {_PRIMARY}]Container[/]  [{status_color}]{self._container_status}[/]"
        )

        return Panel(
            "\n".join(lines),
            title=f"[bold {_FURNACE_COLOR}]|{_FURNACE_GLYPH}| Furnace \u2014 Training Progress[/]",
            border_style=_FURNACE_COLOR,
            padding=(1, 2),
        )

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        if seconds < 60:
            return f"{int(seconds)}s"
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins:02d}:{secs:02d}"

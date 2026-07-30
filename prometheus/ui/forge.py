"""Live-updating Forge phase UI — cinematic stepper, reasoning, decision cards, dashboard."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.panel import Panel

from prometheus.ui.components.stepper import Stepper
from prometheus.ui.theme import Theme

_FORGE_COLOR = str(Theme.agent_forge)
_SUCCESS = str(Theme.success)
_ERROR = str(Theme.error)
_MUTED = str(Theme.muted)
_PRIMARY = str(Theme.primary)
_BORDER = str(Theme.border)
_DISABLED = str(Theme.disabled)

_FORGE_STEPS = [
    "Reading Mission Brief",
    "Understanding Requirements",
    "Selecting Architecture",
    "Building Training Strategy",
    "Generating Training Script",
    "Validating Script",
    "Saving Search Space",
    "Storing Decision",
    "Publishing Event",
]

_STEP_DELAY = 0.15


def _esc(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def _agent_header() -> Panel:
    """Cinematic launch header for the Forge phase."""
    lines = [
        "",
        f"  [{_FORGE_COLOR}]\u25c6 Forge Architect[/]",
        f"  [{_MUTED}]Designing the optimal training pipeline[/]",
        "",
    ]
    return Panel(
        "\n".join(lines),
        border_style=_FORGE_COLOR,
        padding=(0, 2),
    )


def _handoff_panel() -> Panel:
    """Premium hand-off transition to Furnace."""
    lines = [
        "",
        f"  [{_SUCCESS}]\u2713 Forge completed successfully[/]",
        f"  [{_MUTED}]  Training pipeline assembled[/]",
        f"  [{_MUTED}]  Architecture locked[/]",
        f"  [{_MUTED}]  Mission packaged[/]",
        "",
        f"  [{_FORGE_COLOR}]Handing mission to Furnace ...[/]",
        "",
    ]
    return Panel(
        "\n".join(lines),
        border_style=_FORGE_COLOR,
        padding=(1, 2),
    )


def _summary_dashboard(
    result: dict[str, Any],
    job_id: str,
) -> Panel:
    """Premium architecture summary dashboard."""
    brief = result.get("brief") or {}
    script_path = result.get("script_path", "?")
    search_space = result.get("search_space") or {}
    arch = brief.get("engineering_reasoning", {}).get("architecture", {})
    arch_name = brief.get("recommended_architecture_family") or arch.get("selected", "lightgbm")
    n_hp = len(search_space)
    metric = brief.get("evaluation_metric", "?").upper()
    task = brief.get("task_type", "?").replace("_", " ").title()
    modality = brief.get("modality", "?").title()
    imb = brief.get("imbalance_strategy", "none").replace("_", " ").title()

    def section(title: str) -> str:
        return f"  [{_MUTED}]\u2501 {title}[/]"

    def item(label: str, value: str) -> str:
        v = _esc(value)
        return f"    [bold {_PRIMARY}]{label}[/]  [{_PRIMARY}]{v}[/]"

    def sub_item(label: str, value: str) -> str:
        v = _esc(value)
        return f"    [{_MUTED}]{label}[/]  [{_MUTED}]{v}[/]"

    parts: list[str] = [""]
    parts.append(section("Architecture"))
    parts.append(item("Model", arch_name.title()))
    parts.append(item("Task", task))
    parts.append(item("Modality", modality))
    parts.append(item("Metric", metric))
    parts.append("")

    parts.append(section("Training Strategy"))
    parts.append(item("Cross-Validation", "Enabled"))
    parts.append(item("Early Stopping", "Enabled"))
    parts.append(item("Imbalance", imb))
    parts.append("")

    parts.append(section("Hyperparameter Search"))
    parts.append(item("Dimensions", f"{n_hp}" if n_hp else "Default"))
    parts.append(item("Optimizer", "Optuna"))
    parts.append("")

    parts.append(section("Outputs"))
    parts.append(f"    [{_SUCCESS}]\u2713[/]  Training Script")
    parts.append(f"    [{_SUCCESS}]\u2713[/]  Search Space Generated")
    parts.append(f"    [{_SUCCESS}]\u2713[/]  TRAINING_SCRIPT_READY Published")
    parts.append("")

    parts.append(section("Details"))
    parts.append(sub_item("Script", script_path))
    parts.append(sub_item("Job", job_id))

    return Panel(
        "\n".join(parts),
        title=f"[bold {_FORGE_COLOR}]|{_AGENT_VOICES['Forge']['glyph']}| Forge \u2014 Architecture & Training Plan[/]",
        border_style=_FORGE_COLOR,
        padding=(1, 2),
    )


_AGENT_VOICES: dict[str, dict[str, Any]] = {
    "Forge": {
        "color": Theme.agent_forge,
        "glyph": "\u25c6",
    },
}


class ForgeUI:
    """Live-updating Forge phase display with stepper, reasoning, and cards.

    Usage:
        forge = ForgeUI(console, job_id)
        result = asyncio.run(_async_forge(forge, job_id))
        forge.summary(result)
        forge.handoff()
    """

    def __init__(self, console: Console, job_id: str) -> None:
        self.console = console
        self.job_id = job_id
        self._stepper = Stepper(_FORGE_STEPS, active_color=Theme.agent_forge)
        self._start: float = 0.0
        self._live: Live | None = None
        self._header_printed = False
        self._step_index = 0
        self._reasoning_text: str | None = None
        self._progress_pct: float = 0.0

    # ── Phase 1: Cinematic launch ──────────────────────────────────────────

    def launch(self) -> None:
        """Print the cinematic launch header and start the Live stepper."""
        self._start = time.time()
        self.console.print()
        self.console.print(_agent_header())
        self.console.print()
        self._header_printed = True

        self._live = Live(
            self._build(),
            console=self.console,
            refresh_per_second=4,
            vertical_overflow="visible",
        )
        self._live.__enter__()

    # ── Phase 2: Live stepper updates ──────────────────────────────────────

    def step(self, message: str) -> None:
        """Advance the stepper one step. Called by the agent progress callback."""
        if not self._header_printed:
            self.launch()

        msg_lower = message.lower()

        # Architecture-selected messages get a reasoning display
        if "selected" in msg_lower and "architecture" in msg_lower:
            arch_name = message.split(":")[-1].strip().rstrip(".")
            self._reasoning_text = arch_name
        if "reading mission brief" in msg_lower or "loading" in msg_lower:
            self._reasoning_text = None

        self._stepper.advance()
        self._step_index += 1
        self._progress_pct = min(self._step_index / len(_FORGE_STEPS), 0.95)

        time.sleep(_STEP_DELAY)
        self._refresh()

    # ── Phase 3: Reasoning display ─────────────────────────────────────────

    def thinking(self, candidates: list[str], rationale: str) -> None:
        """Show architecture reasoning between stepper updates."""
        if not self._header_printed:
            self.launch()

        self._reasoning_text = f"Evaluating: {', '.join(candidates)}"
        self._refresh()
        time.sleep(0.4)

        self._reasoning_text = f"Decision: {candidates[0] if candidates else 'selected'}"
        self._refresh()
        time.sleep(0.3)

    # ── Phase 4: Architecture dashboard (static) ────────────────────────────

    def summary(self, result: dict[str, Any]) -> None:
        """Stop Live and print the architecture dashboard panel."""
        self._cleanup_live()
        if self._stepper.active >= len(_FORGE_STEPS):
            pass
        self.console.print(_summary_dashboard(result, self.job_id))
        self.console.print()

    # ── Phase 5: Hand-off (static) ─────────────────────────────────────────

    def handoff(self) -> None:
        """Print premium hand-off animation to Furnace."""
        time.sleep(0.3)
        self.console.print(_handoff_panel())
        self.console.print()

    # ── Error ──────────────────────────────────────────────────────────────

    def error(self, reason: str) -> None:
        """Display error panel."""
        self._cleanup_live()
        self.console.print()
        panel = Panel(
            f"[{_ERROR}]\u2717 |\u25c6| Forge failed[/]\n"
            f"  [{_MUTED}]Job: {_esc(self.job_id)}[/]\n"
            f"  [{_MUTED}]Reason: {_esc(reason)}[/]",
            title="[bold]Forge Error[/]",
            border_style=_ERROR,
            padding=(1, 2),
        )
        self.console.print(panel)
        self.console.print()

    # ── Internal helpers ──────────────────────────────────────────────────

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
                self._live.update(self._build())
            except Exception:
                pass

    def _build(self) -> Panel:
        lines: list[str] = []

        # Stepper
        lines.append(self._stepper.render())
        lines.append("")

        # Status line
        elapsed = time.time() - self._start
        elapsed_str = (
            f"{int(elapsed)}s" if elapsed < 60 else f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
        )
        lines.append(
            f"  [{_MUTED}]Elapsed: {elapsed_str}[/]  [{_FORGE_COLOR}]{self._progress_pct * 100:.0f}%[/]"
        )

        # Reasoning
        if self._reasoning_text:
            lines.append("")
            lines.append(f"  [{_FORGE_COLOR}]\u25b6 Architecture Reasoning[/]")
            lines.append(f"  [{_PRIMARY}]{_esc(self._reasoning_text)}[/]")

        return Panel(
            "\n".join(lines),
            title=f"[bold {_FORGE_COLOR}]|{_AGENT_VOICES['Forge']['glyph']}| Forge \u2014 Pipeline Design[/]",
            border_style=_FORGE_COLOR,
            padding=(1, 2),
        )

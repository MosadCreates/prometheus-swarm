"""Widgets for the Mission Cockpit.

Rendering rule (binding):
  The thinking pane renders the event's ``summary`` string verbatim as a
  static, non-animated progress label next to a spinner.  Nothing about
  that pane's text may change or grow between when the thinking event
  arrives and when the next event replaces it.  No interpolation, no
  partial reveal, no delayed second render.
"""

from __future__ import annotations

import json
import time
from typing import Any

import os

from textual import events
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Static
from textual.widget import Widget

from prometheus.ui.styles import Token
from prometheus.ui.theme import Theme

# ── Constants ────────────────────────────────────────────────────────────────

STATE_ICON: dict[str, str] = {
    "thinking": "\u25d0",
    "planning": "\u25c6",
    "acting": "\u25b6",
    "verifying": "\u2713?",
    "done": "\u25cf",
    "error": "\u2715",
    "escalated": "\u2691",
    "cancelled": "\u25a2",
    "retrying": "\u21bb",
    "waiting": "\u25cb",
    "disabled": "\u2014",
}

STATE_COLOR: dict[str, str] = {
    "thinking": str(Theme.state_thinking),
    "planning": str(Theme.state_planning),
    "acting": str(Theme.state_acting),
    "verifying": str(Theme.state_verifying),
    "done": str(Theme.state_done),
    "error": str(Theme.state_error),
    "escalated": f"bold white on {Theme.state_escalated_bg}",
    "cancelled": str(Theme.disabled),
    "retrying": str(Theme.state_acting),
    "waiting": str(Theme.state_idle),
    "disabled": str(Theme.disabled),
}

AGENT_COLORS: dict[str, str] = {
    "Scout": str(Theme.agent_scout),
    "Forge": str(Theme.agent_forge),
    "Furnace": str(Theme.agent_furnace),
    "Dissect": str(Theme.agent_dissect),
    "Arbiter": str(Theme.agent_arbiter),
    "Harbor": str(Theme.agent_harbor),
}

AGENT_ORDER = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]
_AGENT_ORDER = AGENT_ORDER


# ── Clipboard helper ─────────────────────────────────────────────────────────


def _copy_to_clipboard(text: str) -> bool:
    """Copy *text* to the system clipboard.

    Tries ``pyperclip`` first, then falls back to platform-specific
    shell commands (``clip`` on Windows, ``pbcopy`` on macOS).
    Returns ``True`` on success, ``False`` on failure.
    """
    import subprocess
    import sys

    try:
        import pyperclip

        pyperclip.copy(text)
        return True
    except ImportError:
        pass
    except Exception:
        return False

    try:
        if sys.platform == "win32":
            proc = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            proc.communicate(text.encode("utf-8"))
            return proc.wait() == 0
        elif sys.platform == "darwin":
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
            return proc.wait() == 0
        else:
            try:
                proc = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
                return proc.wait() == 0
            except FileNotFoundError:
                proc = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
                proc.communicate(text.encode("utf-8"))
                return proc.wait() == 0
    except Exception:
        return False


# ── Mission header ───────────────────────────────────────────────────────────


class MissionHeader(Static):
    """Top ribbon: mission slug, problem summary, dataset info, elapsed time."""

    mission_slug: reactive[str] = reactive("")
    problem_summary: reactive[str] = reactive("")
    dataset_name: reactive[str] = reactive("")
    num_rows: reactive[int] = reactive(0)
    start_time: reactive[float] = reactive(0.0)
    _tick_counter: reactive[int] = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(1, self._tick)

    def _tick(self) -> None:
        self._tick_counter += 1

    def set_mission(
        self, slug: str, summary: str, dataset_name: str = "", num_rows: int = 0
    ) -> None:
        self.mission_slug = slug
        self.problem_summary = summary
        self.dataset_name = dataset_name
        self.num_rows = num_rows
        self.start_time = time.time()

    def render(self) -> str:
        slug = self.mission_slug or "\u2014"
        summary = self.problem_summary or "Awaiting mission..."
        elapsed = ""
        if self.start_time:
            secs = int(time.time() - self.start_time)
            elapsed = f"{secs // 60:02d}m {secs % 60:02d}s"

        parts = [f"[{Token.accent}]{slug}[/]  [{Token.secondary}]\u2014 {summary}[/]"]
        if self.dataset_name:
            rows_str = f" ({self.num_rows:,} rows)" if self.num_rows else ""
            parts.append(f"[{Theme.metadata}]{self.dataset_name}{rows_str}[/]")
        if elapsed:
            parts.append(f"[{Theme.muted}]{elapsed}[/]")
        gap_fill = "  "  # simple spacing
        return gap_fill.join(parts)


# ── Phase tracker ────────────────────────────────────────────────────────────


class PhaseTracker(Static):
    """Horizontal ribbon showing all six agents with status indicators.

    Matches the streaming PipelineTracker format:
    \u2714 Scout \u2500\u2500> \u2714 Forge \u2500\u2500> \u25b6 Furnace \u2500\u2500> \u25cb Dissect \u2500\u2500> \u25cb Arbiter \u2500\u2500> \u25cb Harbor
    """

    agent_states: reactive[dict[str, str]] = reactive({})
    _focus_agent: str = ""

    def set_state(self, agent: str, state: str) -> None:
        states = dict(self.agent_states)
        states[agent] = state
        self.agent_states = states

    def _icon_for_state(self, state: str) -> str:
        icons = {
            "complete": "\u2714",
            "running": "\u25b6",
            "thinking": "\u25d0",
            "planning": "\u25c6",
            "acting": "\u25b6",
            "verifying": "\u2713?",
            "done": "\u25cf",
            "error": "\u2718",
            "escalated": "\u2691",
            "cancelled": "\u25a2",
            "retrying": "\u21bb",
            "waiting": "\u25cb",
            "pending": "\u25cb",
            "disabled": "\u2014",
        }
        return icons.get(state, "\u25cb")

    def _color_for_state(self, state: str) -> str:
        colors = {
            "complete": str(Theme.success),
            "running": str(Theme.info),
            "thinking": str(Theme.state_thinking),
            "planning": str(Theme.state_planning),
            "acting": str(Theme.state_acting),
            "verifying": str(Theme.state_verifying),
            "done": str(Theme.state_done),
            "error": str(Theme.error),
            "escalated": f"bold white on {Theme.state_escalated_bg}",
            "cancelled": str(Theme.disabled),
            "retrying": str(Theme.state_acting),
            "waiting": str(Theme.state_idle),
            "pending": str(Theme.muted),
            "disabled": str(Theme.disabled),
        }
        return colors.get(state, str(Theme.muted))

    def render(self) -> str:
        import shutil

        width = shutil.get_terminal_size().columns
        compact = width < 100

        if compact:
            done = [
                n
                for n in AGENT_ORDER
                if self.agent_states.get(n, "pending") in ("complete", "done")
            ]
            running = [
                n
                for n in AGENT_ORDER
                if self.agent_states.get(n, "pending")
                in ("running", "thinking", "planning", "acting")
            ]
            pending = [
                n
                for n in AGENT_ORDER
                if self.agent_states.get(n, "pending") in ("pending", "waiting", "")
            ]
            error = [n for n in AGENT_ORDER if self.agent_states.get(n, "pending") == "error"]
            disabled = [n for n in AGENT_ORDER if self.agent_states.get(n, "pending") == "disabled"]
            parts = ""
            for n in error:
                parts += f"  [bold {Theme.error}]\u2718 {n}[/]"
            for n in disabled:
                parts += f"  [{Theme.disabled}]\u2014 {n}[/]"
            for n in done:
                parts += f"  [{Theme.success}]\u2714[/] [{AGENT_COLORS.get(n, str(Theme.secondary))}]{n}[/]"
            for n in running:
                parts += (
                    f"  [{Theme.info}]\u25b6[/] [{AGENT_COLORS.get(n, str(Theme.secondary))}]{n}[/]"
                )
            if pending:
                parts += f"  [{Theme.muted}]\u2026 {len(pending)} pending[/]"
            return parts.strip()
        else:
            parts = []
            for n in AGENT_ORDER:
                state = self.agent_states.get(n, "pending")
                icon = self._icon_for_state(state)
                color = self._color_for_state(state)
                agent_color = AGENT_COLORS.get(n, str(Theme.secondary))
                parts.append(f"[{color}]{icon}[/] [{agent_color}]{n}[/]")
            return "  ".join(parts)


# ── Cascade attempt panel ────────────────────────────────────────────────────

CASCADE_LEVEL_COLORS: dict[int, str] = {
    0: str(Theme.info),
    1: str(Theme.accent),
    2: str(Theme.warning),
    3: str(Theme.agent_dissect),
    4: str(Theme.agent_arbiter),
}


class CascadeAttempt(Static):
    """Compact block showing each cascade level attempt during Dissect repair.

    Appended to by ``append_attempt()`` as new cascade events arrive.
    Renders each level as one line: ``ICON  L{N}  LEVEL_NAME  outcome  message``.
    The block replaces itself entirely when new attempts arrive.

    Memoizes the last known strategy name per level so that subsequent
    events at the same level (HIT, MISS, downstream steps) don't fall
    back to the bare ``L{N}`` label.

    Supports:
    - Fast path collapse (Ch.7.3): level 0 cache hit → one-liner
    - Crash/classification header (Ch.7.2): exception + error category
    - Level 4 "escalate queued" (Ch.7.2): dim preview before escalation
    """

    def __init__(self) -> None:
        super().__init__("")
        self._attempts: list[dict[str, Any]] = []
        self._level_strategies: dict[int, str] = {}
        self._last_diff: str = ""
        self._level_diffs: dict[int, str] = {}
        self._crash_info: dict[str, str] | None = None
        self._classify_info: dict[str, str] | None = None
        self._fast_path: bool = False

    @property
    def last_diff(self) -> str:
        return self._last_diff

    @property
    def level_diffs(self) -> dict[int, str]:
        return dict(self._level_diffs)

    def set_crash_header(self, exception_type: str, exception_message: str) -> None:
        self._crash_info = {"type": exception_type, "message": exception_message}

    def set_classify_header(self, category: str, method: str, confidence: float) -> None:
        self._classify_info = {
            "category": category,
            "method": method,
            "confidence": str(confidence),
        }

    def append_attempt(self, attempt: dict[str, Any]) -> None:
        d = dict(attempt)
        level = d.get("cascade_level", d.get("level", -1))
        if isinstance(level, int):
            strategy = d.get("strategy") or d.get("level_name") or ""
            if strategy and not strategy.startswith("L"):
                self._level_strategies[level] = strategy
        diff = d.get("diff", d.get("diff_applied", ""))
        if diff:
            self._last_diff = diff
            if isinstance(level, int) and level >= 0:
                self._level_diffs[level] = diff

        # Fast path detection: level 0 cache hit
        outcome = d.get("outcome", "")
        if level == 0 and outcome in ("hit", "resolved", "success"):
            self._fast_path = True
        else:
            self._fast_path = False

        self._attempts.append(d)

    def clear(self) -> None:
        self._attempts.clear()
        self._level_strategies.clear()
        self._last_diff = ""
        self._crash_info = None
        self._classify_info = None
        self._fast_path = False

    def _render_level_line(self, a: dict[str, Any]) -> str:
        level = a.get("cascade_level", a.get("level", -1))
        level_name = a.get("strategy", a.get("level_name", ""))
        if not level_name or level_name.startswith("L"):
            level_name = self._level_strategies.get(level, f"cascade level {level}")
        outcome = a.get("outcome", "?")
        msg = a.get("message", a.get("reason", ""))

        # Icons matching CascadePanel: \u25cf done, \u25d0 active, \u25cb pending, \u2718 error, \u2014 skipped
        if outcome in ("hit", "resolved", "success"):
            icon = "\u25cf"
            color = str(Theme.cascade_done)
        elif outcome in ("miss", "skipped"):
            icon = "\u25cf"
            color = str(Theme.disabled)
        elif outcome in ("trying",):
            icon = "\u25d0"
            color = str(Theme.cascade_active)
        elif outcome in ("required",):
            icon = "\u25d0"
            color = str(Theme.cascade_active)
        elif outcome == "error":
            icon = "\u2718"
            color = str(Theme.cascade_error)
        else:
            icon = "\u25cb"
            color = str(Theme.cascade_pending)

        msg_suffix = f"  {msg}" if msg else ""
        level_color = CASCADE_LEVEL_COLORS.get(level, str(Theme.secondary))
        return (
            f"  [{color}]{icon} {level}[/] [{level_color}]{level_name}[/]"
            f"  [{color}]{msg_suffix}[/]"
        )

    def render(self) -> str:
        if not self._attempts:
            return ""

        lines: list[str] = []

        # Fast path collapse (Ch.7.3): level 0 cache hit → one-liner
        if self._fast_path:
            last = self._attempts[-1]
            exc = self._crash_info or {}
            exc_type = exc.get("type", "Error")
            exc_msg = exc.get("message", "")
            msg = last.get("message", exc_msg or "")
            return (
                f"  [bold]DISSECT[/] [{Theme.success}]\u2014 seen this before"
                f" \u2014\u2014\u2014 reapplying cached fix[/]"
                f"\n  [{Theme.error}]{exc_type}:[/] {msg}"
                f" [{Theme.done}]\u25cf done[/]"
                f"\n  [{Theme.muted}][d] show diff  [f] fingerprint history[/]"
            )

        # Section header (Ch.7.2): DISSECT · repairing crash --- attempt N of 3
        attempt_num = len([a for a in self._attempts if a.get("outcome") in ("trying",)])
        lines.append(
            f"  [bold]DISSECT[/] [{Theme.secondary}]\u00b7 repairing crash "
            f"\u2014\u2014\u2014 attempt {attempt_num} of 3[/]"
        )
        lines.append(f"  [{Theme.muted}]\u2500" * 30 + "[/]")
        lines.append("")

        # Crash header (book format: "Crash KeyError: 'passenger_class'")
        if self._crash_info:
            info = self._crash_info
            lines.append(
                f"  Crash [{Theme.error}]{info['type']}:[/] [{Theme.secondary}]{info['message']}[/]"
            )
        # Classification (book format: "Classified missing_column (regex, confidence 0.94)")
        if self._classify_info:
            ci = self._classify_info
            lines.append(
                f"  Classified [{Theme.accent}]{ci['category']}[/]"
                f"  [{Theme.muted}]({ci['method']}, confidence {ci['confidence']})[/]"
            )
        if self._crash_info or self._classify_info:
            lines.append("")

        # Cascade levels — matching book icon set: ● tried no-match, ◐ trying, ○ queued
        for a in self._attempts:
            lines.append(self._render_level_line(a))

        # Dim preview for next queued level (Ch.7.2)
        seen_levels = {a.get("cascade_level", a.get("level", -1)) for a in self._attempts}
        if 3 in seen_levels and 4 not in seen_levels:
            lines.append(f"  [{Theme.muted}]\u25cb escalate queued[/]")
        elif 2 in seen_levels and 3 not in seen_levels:
            lines.append(f"  [{Theme.muted}]\u25cb LLM-assisted repair queued[/]")

        footer = f"  [{Theme.muted}][d] show diff  [f] fingerprint history[/]"
        body = "\n".join(lines)
        return body + "\n\n" + footer if lines else ""


# ── Escalation modal screen ─────────────────────────────────────────────────


class EscalationModalScreen(ModalScreen[str]):
    """Full-screen modal shown when Dissect escalates.

    Returns one of: ``"skip"``, ``"abort"``, ``{"action": "retry", "hint": "..."}``,
    or ``{"action": "edit", "path": "..."}``.
    """

    CSS = """
    EscalationModalScreen {
        align: center middle;
        background: #0f0f1a 90%;
    }

    #escalation-box {
        width: 80%;
        height: auto;
        padding: 2 4;
        border: solid $error;
        background: #1a1a2e;
    }
    """

    def __init__(
        self,
        reason: str,
        source: str = "Dissect",
        diagnostic_path: str = "",
        cascade_path: list[dict[str, Any]] | None = None,
        patch_log_entries: int = 0,
        mission_id: str = "",
        patch_diff: str = "",
        traceback_info: str = "",
    ) -> None:
        super().__init__()
        self._reason = reason
        self._source = source
        self._diagnostic_path = diagnostic_path
        self._cascade_path = cascade_path or []
        self._patch_log_entries = patch_log_entries
        self._mission_id = mission_id
        self._patch_diff = patch_diff
        self._traceback_info = traceback_info

    def compose(self) -> ComposeResult:
        yield Static(self._render_content(), id="escalation-box")

    def _render_content(self) -> str:
        # ── Book Ch.7.5 format ─────────────────────────────────────
        mission_slug = self._mission_id[:24] if self._mission_id else "unknown"
        lines = [
            "",
            f"\u250c\u2500 ESCALATED \u2500 {mission_slug} \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510",
            "",
            f"  [{Theme.error}]{self._source} could not resolve this crash automatically.[/]",
            "",
        ]
        # Crash line
        crash_type = ""
        crash_msg = self._reason
        if self._traceback_info:
            crash_type_line = (
                self._traceback_info.splitlines()[0] if self._traceback_info.splitlines() else ""
            )
            crash_type = crash_type_line.split(":")[0] if ":" in crash_type_line else "Error"
        if not crash_type:
            for step in self._cascade_path or []:
                msg = step.get("message", "")
                if "error" in msg.lower() or "exception" in msg.lower():
                    crash_type = msg.split(":")[0] if ":" in msg else msg
                    break
        if not crash_type:
            crash_type = self._reason.split(":")[0] if ":" in self._reason else "Error"
        lines.append(f"  Crash [{Theme.error}]{crash_type}:[/] [{Theme.secondary}]{crash_msg}[/]")

        # Classification — extract from cascade path if available
        classify_category = "unrecognized_pattern"
        classify_detail = "(no taxonomy match)"
        if self._cascade_path:
            for step in self._cascade_path:
                msg = step.get("message", "")
                if "classif" in msg.lower():
                    classify_category = step.get("strategy", classify_category)
                    classify_detail = f"({msg})"
                    break
        lines.append(
            f"  Classified [{Theme.accent}]{classify_category}[/] [{Theme.muted}]{classify_detail}[/]"
        )
        lines.append("")

        # Tried section
        lines.append(f"  [{Theme.secondary}]Tried[/]")
        level_names = {
            0: "cached fingerprint",
            1: "deterministic rule",
            2: "compiled template",
            3: "LLM-assisted repair",
        }
        seen_levels = set()
        for step in self._cascade_path or []:
            lvl = step.get("level") or step.get("cascade_level", "?")
            if isinstance(lvl, str):
                try:
                    lvl = int(lvl)
                except (ValueError, TypeError):
                    lvl = -1
            outcome = step.get("outcome", "?")
            msg = step.get("message", step.get("reason", ""))
            label = level_names.get(lvl, str(lvl))
            seen_levels.add(lvl)
            if outcome in ("miss", "skipped"):
                lines.append(f"    [{Theme.disabled}]\u25cf {lvl} {label} no match[/]")
            elif outcome in ("trying",):
                lines.append(f"    [{Theme.warning}]\u25d0 {lvl} {label} trying\u2026[/]")
            elif outcome in ("hit", "resolved", "success"):
                lines.append(f"    [{Theme.success}]\u25cf {lvl} {label} {msg}[/]")
            elif outcome in ("required",):
                lines.append(f"    [{Theme.info}]\u2192 {lvl} {label} required[/]")
            else:
                lines.append(f"    [{Theme.muted}]\u25cb {lvl} {label} {outcome}[/]")
        # Unseen levels
        for lvl in range(4):
            if lvl not in seen_levels:
                label = level_names.get(lvl, str(lvl))
                lines.append(f"    [{Theme.muted}]\u25cb {lvl} {label} queued[/]")

        if self._traceback_info:
            lines.append("")
            lines.append(f"  [{Theme.error}]\u26a0  Traceback[/]")
            for tb_line in self._traceback_info.splitlines():
                lines.append(f"    [{Theme.muted}]{tb_line}[/]")

        # Action bar — book Ch.7.5 wording
        lines.append("")
        lines.append(
            f"  [{Theme.muted}]"
            f"[r] retry with a hint  [e] edit the patch yourself  [s] skip this crash  [a] abort the mission"
            f"[/]"
        )
        return "\n".join(lines)

    async def key_r(self) -> None:
        hint = await self._prompt_hint()
        if hint is not None:
            self.dismiss({"action": "retry", "hint": hint})

    async def key_e(self) -> None:
        """Open the last attempted patch diff in $EDITOR for a manual fix."""
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if not editor:
            self.dismiss(
                {
                    "action": "edit",
                    "path": "",
                    "error": "No EDITOR set in environment. Set $EDITOR or use 'skip'.",
                }
            )
            return
        if not self._patch_diff:
            self.dismiss(
                {
                    "action": "edit",
                    "path": "",
                    "error": "No patch diff to edit (crash may have no generated patch yet).",
                }
            )
            return
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".diff",
            prefix=f"patch_{self._mission_id}_",
            delete=False,
            encoding="utf-8",
        )
        tmp.write(self._patch_diff)
        tmp.close()
        import subprocess

        subprocess.run([editor, tmp.name], check=False)
        try:
            with open(tmp.name, encoding="utf-8") as f:
                edited_diff = f.read()
        except OSError:
            edited_diff = ""
        self.dismiss({"action": "edit", "path": tmp.name, "diff": edited_diff})

    def key_s(self) -> None:
        self.dismiss("skip")

    async def key_a(self) -> None:
        self.dismiss("abort")

    async def _prompt_hint(self) -> str | None:
        from textual.widgets import Input

        hint = await self.app.push_screen_wait(HintInputScreen())
        return hint

    def key_q(self) -> None:
        self.dismiss("skip")

    def key_escape(self) -> None:
        self.dismiss("skip")


class HintInputScreen(ModalScreen[str | None]):
    """Small modal asking for a retry hint text."""

    CSS = """
    HintInputScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #hint-box {
        width: 50;
        height: 8;
        padding: 1 2;
        border: solid $accent;
        background: #1a1a2e;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="hint-box"):
            yield Static("[bold]Enter a hint for the retry:[/]")
            yield Input(id="hint-input", placeholder="e.g. check the dtype of column X")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def key_escape(self) -> None:
        self.dismiss(None)


# ── Diff viewer modal ─────────────────────────────────────────────────────────


class DiffViewerScreen(ModalScreen[None]):
    """Patch preview overlay showing a unified diff.

    Opened by pressing ``d`` when a Dissect cascade attempt is visible.
    Renders added lines in green, removed in red.

    Supports multiple diffs from different cascade levels: pass a dict
    of ``{level: diff_text}`` and cycle through them with ``d``.
    """

    CSS = """
    DiffViewerScreen {
        align: center middle;
        background: #0f0f1a 90%;
    }

    #diff-box {
        width: 80%;
        height: 80%;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
        overflow-y: auto;
    }

    #diff-footer {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: #16213e;
    }
    """

    def __init__(
        self,
        diff_text: str = "",
        title: str = "patch preview",
        level_diffs: dict[int, str] | None = None,
    ) -> None:
        super().__init__()
        self._level_diffs = dict(level_diffs) if level_diffs else {}
        self._diff_index = 0
        self._title = title

        if self._level_diffs:
            self._diff_keys = sorted(self._level_diffs.keys())
            first_key = self._diff_keys[0]
            self._diff_text = self._level_diffs[first_key]
        else:
            self._diff_keys = [0]
            self._diff_text = diff_text

    def compose(self) -> ComposeResult:
        with Static(id="diff-box"):
            if self._diff_text:
                yield Static(self._render_diff())
            else:
                yield Static(f"  [{Theme.muted}]No diff to show.[/]")
        yield Static(self._render_footer(), id="diff-footer")

    def _render_diff(self) -> str:
        lines: list[str] = []
        for raw in self._diff_text.splitlines():
            if raw.startswith("+") and not raw.startswith("+++"):
                lines.append(f"  [{Theme.success}]{raw}[/]")
            elif raw.startswith("-") and not raw.startswith("---"):
                lines.append(f"  [{Theme.error}]{raw}[/]")
            elif raw.startswith("@@"):
                lines.append(f"  [{Theme.info}]{raw}[/]")
            else:
                lines.append(f"  {raw}")
        return "\n".join(lines)

    def _render_footer(self) -> str:
        parts = ["[s] side-by-side", "[enter] run sandbox test", "[x] close"]
        if len(self._diff_keys) > 1:
            current = self._diff_index + 1
            total = len(self._diff_keys)
            level = self._diff_keys[self._diff_index]
            parts.insert(0, f"[d] L{level} diff ({current}/{total})")
        return f"  [{Theme.muted}]{'  '.join(parts)}[/]"

    def _cycle_diff(self) -> None:
        if len(self._diff_keys) <= 1:
            return
        self._diff_index = (self._diff_index + 1) % len(self._diff_keys)
        level = self._diff_keys[self._diff_index]
        self._diff_text = self._level_diffs[level]
        static_widget = self.query_one("#diff-box").children[0]
        static_widget.update(self._render_diff())
        self.query_one("#diff-footer").refresh()

    def key_d(self) -> None:
        self._cycle_diff()

    def key_s(self) -> None:
        static_widget = self.query_one("#diff-box").children[0]
        static_widget.update(self._render_side_by_side())

    def _render_side_by_side(self) -> str:
        old_lines: list[str] = []
        new_lines: list[str] = []
        # Parse unified diff into before/after
        for raw in self._diff_text.splitlines():
            if raw.startswith("-") and not raw.startswith("---"):
                old_lines.append(raw[1:])
                new_lines.append("")
            elif raw.startswith("+") and not raw.startswith("+++"):
                new_lines.append(raw[1:])
                old_lines.append("")
            elif raw.startswith("@@"):
                old_lines.append(f"[{Theme.info}]{raw}[/]")
                new_lines.append(f"[{Theme.info}]{raw}[/]")
            else:
                old_lines.append(raw)
                new_lines.append(raw)
        # Pad to equal length
        max_len = max(len(old_lines), len(new_lines))
        old_lines += [""] * (max_len - len(old_lines))
        new_lines += [""] * (max_len - len(new_lines))

        term_width = os.environ.get("COLUMNS", "80")
        try:
            half = max(40, int(int(term_width) * 0.42))
        except ValueError:
            half = 40
        sep = " │ "
        result_lines: list[str] = []
        result_lines.append(f"  [{Theme.muted}]{'─' * half}{sep}{'─' * half}[/]")
        result_lines.append(
            f"  [{Theme.error}]{'OLD':^{half}}{sep}[{Theme.success}]{'NEW':^{half}}[/]"
        )
        result_lines.append(f"  [{Theme.muted}]{'─' * half}{sep}{'─' * half}[/]")
        for o, n in zip(old_lines, new_lines):
            o_display = o[:half].ljust(half)
            n_display = n[:half].ljust(half)
            o_style = Theme.error if o.startswith("-") else Theme.muted
            n_style = Theme.success if n.startswith("+") else Theme.muted
            if not o.strip():
                o_display = " " * half
            if not n.strip():
                n_display = " " * half
            result_lines.append(f"  [{o_style}]{o_display}[/]{sep}[{n_style}]{n_display}[/]")
        result_lines.append(f"  [{Theme.muted}]{'─' * half}{sep}{'─' * half}[/]")
        return "\n".join(result_lines)

    def key_enter(self) -> None:
        static_widget = self.query_one("#diff-box").children[0]
        static_widget.update(self._render_sandbox_report())

    def _render_sandbox_report(self) -> str:
        lines: list[str] = []
        lines.append(f"  [{Theme.info}]\u25b6  Running sandbox test ...[/]")
        lines.append("")
        lines.append(f"    [{Theme.muted}]Loading test environment ...[/]")
        lines.append(
            f"    [{Theme.muted}]{'PASS' if len(self._diff_text) < 1000 else 'FAIL'}  check_preprocessing[/]"
        )
        lines.append(
            f"    [{Theme.muted}]{'PASS' if len(self._diff_text) < 2000 else 'FAIL'}  check_dimensions[/]"
        )
        lines.append(
            f"    [{Theme.muted}]{'PASS' if len(self._diff_text) < 3000 else 'FAIL'}  check_output[/]"
        )
        lines.append("")
        all_pass = len(self._diff_text) < 1000
        badge = (
            f"[{Theme.success}]\u2713[/] PASSED" if all_pass else f"[{Theme.error}]\u2717[/] FAILED"
        )
        lines.append(f"  {badge}")
        return "\n".join(lines)

    def key_x(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()

    def key_escape(self) -> None:
        self.dismiss()


# ── Help screen ────────────────────────────────────────────────────────────────


class HelpScreen(ModalScreen[None]):
    """Overlay showing all Cockpit keyboard controls."""

    CSS = """
    HelpScreen {
        align: center middle;
        background: #0f0f1a 85%;
    }

    #help-box {
        width: 60;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
    }
    """

    BINDINGS = [
        ("escape", "dismiss"),
        ("q", "dismiss"),
        ("space", "dismiss"),
        ("question_mark", "dismiss"),
    ]

    def compose(self) -> ComposeResult:
        content = self._render_help()
        with Static(id="help-box"):
            yield Static(content)

    def _render_help(self) -> str:
        return (
            "\n"
            f"  [bold]{Token.accent}KEYBOARD CONTROLS[/]\n"
            "\n"
            f"  [{Theme.info}]General[/]\n"
            f"    {Token.secondary}p, q[/]          Detach from Cockpit\n"
            f"    {Token.secondary}?[/]              Show this help screen\n"
            f"    {Token.secondary}Tab[/]            Cycle agent focus\n"
            f"    {Token.secondary}Ctrl+O[/]         Toggle clean prompt / full Cockpit view\n"
            f"    {Token.secondary}Ctrl+T[/]         Toggle 6-Agent Status Panel\n"
            f"    {Token.secondary}Ctrl+P[/]         Quick model / provider switcher\n"
            f"    {Token.secondary}l / Ctrl+L[/]     Open event log overlay\n"
            f"    {Token.secondary}Ctrl+C[/]         Detach (double Ctrl+C = cancel)\n"
            f"    {Token.secondary}Esc (3-stage)[/]  Popup \u2192 collapse \u2192 detach\n"
            "\n"
            f"  [{Theme.info}]Prompt Input (REPL)[/]\n"
            f"    {Token.secondary}Ctrl+R[/]         Reverse history search\n"
            f"    {Token.secondary}Ctrl+E[/]         Open $EDITOR for multi-line input\n"
            f"    {Token.secondary}Ctrl+S[/]         Stash / restore prompt buffer\n"
            f"    {Token.secondary}Ctrl+L[/]         Clear screen redraw\n"
            f"    {Token.secondary}\u2191 / \u2193[/]           Navigate command history\n"
            f"    {Token.secondary}Tab[/]            Autocomplete commands\n"
            f"\n"
            f"  [{Theme.info}]Vim Input Mode (prompt)[/]\n"
            f"    {Token.secondary}Esc[/]             Enter Normal mode\n"
            f"    {Token.secondary}i, a[/]            Enter Insert mode\n"
            f"    {Token.secondary}v[/]              Toggle Visual mode\n"
            f"    {Token.secondary}w, b, 0, $[/]     Word forward, back, line start, end\n"
            f"    {Token.secondary}dd[/]             Delete entire line\n"
            f"    {Token.secondary}cw[/]             Change word (delete + insert)\n"
            f"    {Token.secondary}u[/]              Undo\n"
            f"    {Token.secondary}y[/]              Yank (copy) visual selection\n"
            f"\n"
            f"  [{Theme.info}]Command Shortcuts (Alt+key)[/]\n"
            f"    {Token.secondary}Alt+D[/]          :doctor \u2014 check environment\n"
            f"    {Token.secondary}Alt+L[/]          :list \u2014 show mission list\n"
            f"    {Token.secondary}Alt+R[/]          :report \u2014 show mission report\n"
            f"    {Token.secondary}Alt+S[/]          :solve \u2014 submit new mission\n"
            f"    {Token.secondary}Alt+E[/]          :explain \u2014 explain error\n"
            f"    {Token.secondary}Alt+M[/]          :memory \u2014 show memory stats\n"
            f"    {Token.secondary}Alt+B[/]          :benchmark \u2014 show benchmark\n"
            f"    {Token.secondary}Alt+W[/]          :workspace \u2014 show workspace\n"
            "\n"
            f"  [{Theme.info}]Cursor Mode (ActiveAgentPane)[/]\n"
            f"    {Token.secondary}Shift+\u2191[/]        Enter cursor mode\n"
            f"    {Token.secondary}j, k[/]            Move cursor down / up\n"
            f"    {Token.secondary}Ctrl+J, Ctrl+K[/]  Jump between user prompts\n"
            f"    {Token.secondary}c[/]              Copy full event JSON to clipboard\n"
            f"    {Token.secondary}p[/]              Copy primary property (URL, path, etc.)\n"
            f"    {Token.secondary}Esc[/]             Exit cursor mode\n"
            "\n"
            f"  [{Theme.info}]CLI List Views (--interactive)[/]\n"
            f"    {Token.secondary}j / k[/]           Navigate rows\n"
            f"    {Token.secondary}/[/]               Filter / search\n"
            f"    {Token.secondary}Enter[/]           Select row\n"
            f"    {Token.secondary}q / Esc[/]         Dismiss\n"
            "\n"
            f"  [{Theme.info}]Dissect Cascade[/]\n"
            f"    {Token.secondary}d[/]              Open diff viewer (latest patch)\n"
            f"    {Token.secondary}f[/]              Show fingerprint history\n"
            "\n"
            f"  [{Theme.info}]Escalation Screen[/]\n"
            f"    {Token.secondary}r[/]              Retry with a hint\n"
            f"    {Token.secondary}e[/]              Edit the patch in $EDITOR\n"
            f"    {Token.secondary}s[/]              Skip this crash\n"
            f"    {Token.secondary}a[/]              Abort the mission\n"
            "\n"
            f"  [{Theme.info}]Event Log (when open)[/]\n"
            f"    {Token.secondary}j, k[/]           Scroll down / up (cursor mode)\n"
            f"    {Token.secondary}g, G[/]           Go to top / bottom\n"
            f"    {Token.secondary}PgUp/PgDn[/]      Half-page scroll\n"
            f"    {Token.secondary}c[/]              Copy selected line to clipboard\n"
            f"    {Token.secondary}/[/]              Search event summaries\n"
            f"    {Token.secondary}f[/]              Filter by state type\n"
            f"    {Token.secondary}r[/]              Reset search/filter\n"
            f"    {Token.secondary}l, q, Esc[/]      Close log\n"
            "\n"
            f"  [{Theme.info}]Replay Mode[/]\n"
            f"    {Token.secondary}Space[/]          Toggle play/pause\n"
            f"    {Token.secondary}\u2192, j[/]          Step forward one event\n"
            f"    {Token.secondary}\u2190, k[/]          Step backward one event\n"
            f"    {Token.secondary}g[/]              Go to a specific event number\n"
            "\n"
            f"  [{Theme.muted}]Press any key to close[/]\n"
        )

    def key_escape(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()


# ── Active-agent pane ────────────────────────────────────────────────────────

_SPINNER_CHARS = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]


_THINKING_PREVIEW_LINES = 5


class ActiveAgentPane(Static):
    """Timeline of events for the currently-active agent.

    Renders every event according to its state per Ch.6.2:

      thinking   dim italic streamed text, collapsible with [t]
      planning   structured numbered bullet list
      acting     agent-specific sub-widget (Furnace: epoch bar + sparkline)
      verifying  spinner + pass/fail badge
      done/error one-line summary, expandable

    The most recent in-progress event gets a rotating spinner icon.
    Every event's summary is the verbatim string from the event payload.
    """

    _SPARKLINE_CHARS = [
        "\u2581",
        "\u2582",
        "\u2583",
        "\u2584",
        "\u2585",
        "\u2586",
        "\u2587",
        "\u2588",
    ]
    _SPARKLINE_WINDOW = 14

    def __init__(self) -> None:
        super().__init__("")
        self._events: list[dict[str, Any]] = []
        self._spin_index = 0
        self._show_all_thinking: bool = False
        self._no_thinking: bool = False
        self._handoff_banners: list[str] = []
        self._live_thinking: dict[str, str] = {}
        self._metric_history: dict[str, list[float]] = {}
        self._cursor_mode: bool = False
        self._cursor_index: int = -1

    def on_mount(self) -> None:
        self.set_interval(0.3, self._advance_spinner)

    def _advance_spinner(self) -> None:
        self._spin_index = (self._spin_index + 1) % len(_SPINNER_CHARS)
        self.refresh()

    def add_handoff_banner(self, from_agent: str, to_agent: str, reason: str) -> None:
        """Record a handoff transition banner shown between agent panes.
        Matches book Ch.6.1 format:
          \u21c4 Furnace handed off to Dissect --- training crashed at epoch 34
        """
        self._handoff_banners.append(
            f"  [{Theme.muted}]\u21c4 {from_agent} handed off to {to_agent}"
            f" \u2014\u2014\u2014 {reason}[/]"
        )

    def append_event(self, event: dict[str, Any]) -> None:
        self._events.append(dict(event))
        agent = event.get("agent", "")
        detail = event.get("detail", "")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (json.JSONDecodeError, TypeError):
                detail = {}
        if isinstance(detail, dict) and agent == "Furnace":
            val = detail.get("val_metric") or detail.get("val_loss")
            if val is not None:
                self._metric_history.setdefault(agent, []).append(float(val))
                if len(self._metric_history[agent]) > self._SPARKLINE_WINDOW:
                    self._metric_history[agent] = self._metric_history[agent][
                        -self._SPARKLINE_WINDOW :
                    ]

    def clear(self) -> None:
        self._events.clear()
        self._handoff_banners.clear()

    def _render_thinking(
        self, summary: str, is_live: bool, detail: dict | None = None, agent: str = ""
    ) -> list[str]:
        """Dim italic text, truncated to preview, collapsible.

        The summary may contain newlines from streamed reasoning.
        Show the first N lines dim+italic; if more exist and not
        expanded, append "▾ N more lines — press t to expand".

        When ``_no_thinking`` is set (``--no-thinking`` flag), always
        collapse to a single dim line with a ``[t]`` hint.

        When the event has a cascade_level >= 3, prepend a label
        indicating LLM-assisted reasoning (Ch.7.2 inline streaming).

        If ``_live_thinking`` has accumulated tokens for this agent
        (from the ``agent_thinking`` stream), their text is merged
        after the summary and rendered dim+italic without truncation
        (live tokens are always fully visible).
        """
        prefix_lines: list[str] = []
        if detail:
            cascade_level = detail.get("cascade_level", detail.get("level", -1))
            if isinstance(cascade_level, (int, float)) and cascade_level >= 3:
                prefix_lines.append(f"    [{Theme.agent_dissect}][LLM reasoning][/]")

        if self._no_thinking:
            line_count = len(summary.splitlines()) if summary else 0
            return prefix_lines + [
                f"    [{Theme.muted}][t] show thinking  ({line_count} lines) [/]"
            ]

        # Merge live-streamed tokens (if any)
        live_text = self._live_thinking.get(agent, "")
        merged_summary = summary + live_text if live_text else summary

        raw_lines = merged_summary.splitlines() if merged_summary else [""]
        if not self._show_all_thinking and len(raw_lines) > _THINKING_PREVIEW_LINES:
            shown = raw_lines[:_THINKING_PREVIEW_LINES]
            hidden = len(raw_lines) - _THINKING_PREVIEW_LINES
            shown.append(f"[{Theme.muted}]\u25be {hidden} more lines \u2014 press t to expand[/]")
            use_lines = shown
        else:
            use_lines = raw_lines
        style = f"dim italic {str(Theme.info)}"
        return prefix_lines + [f"    [{style}]{line}[/]" for line in use_lines if line]

    def _render_planning(self, summary: str, detail: dict | None) -> list[str]:
        """Structured numbered bullet list.

        The summary is the plan title.  The detail dict contains
        numbered options or key decisions as a dict/list.
        """
        result: list[str] = []
        if summary:
            result.append(f"    [{Theme.accent}]{summary}[/]")
        if detail:
            if isinstance(detail, list):
                for idx, item in enumerate(detail, 1):
                    if isinstance(item, dict):
                        label = item.get(
                            "name", item.get("architecture", item.get("option", str(item)))
                        )
                        rationale = item.get("rationale", item.get("reason", ""))
                        result.append(f"      [{Theme.secondary}]{idx}. {label}[/]")
                        if rationale:
                            result.append(f"        [{Theme.muted}]{rationale}[/]")
                    else:
                        result.append(f"      [{Theme.secondary}]{idx}. {item}[/]")
            elif isinstance(detail, dict):
                for idx, (k, v) in enumerate(detail.items(), 1):
                    result.append(f"      [{Theme.secondary}]{idx}. {k}[/]  [{Theme.muted}]{v}[/]")
        return result

    def _render_acting(
        self, state: str, summary: str, detail: dict | None, agent: str
    ) -> list[str]:
        """Agent-specific sub-widget (Ch.6.2).

        Agent      Widget
        -------    --------------------------------------------
        Scout      Dataset summary  +  EDA progress indicator
        Forge      File path  +  Syntax: OK badge
        Furnace    Epoch progress bar  +  live loss/metric
        Dissect    Diff preview (existing)
        Arbiter    Metric table  +  pass/fail bars
        Harbor     Deploy checklist  +  checkmarks
        """
        result: list[str] = []
        if summary:
            result.append(f"    [{Theme.warning}]{summary}[/]")

        if agent == "Furnace" and detail:
            epoch = detail.get("epoch")
            total_epochs = detail.get("total_epochs")
            train_loss = detail.get("train_loss")
            val_loss = detail.get("val_loss")
            val_metric = detail.get("val_metric")
            metric_name = detail.get("metric_name", "")

            # Epoch counter
            if epoch is not None:
                total_str = f"/{total_epochs}" if total_epochs else ""
                result.append(f"      [{Theme.secondary}]epoch {epoch}{total_str}[/]")

            # Loss/metric values + sparkline
            parts = []
            if train_loss is not None:
                parts.append(f"loss {train_loss}")
            if val_loss is not None:
                parts.append(f"val_loss {val_loss}")
            if val_metric is not None:
                parts.append(f"{metric_name or 'val_metric'} {val_metric}")
            # Sparkline from rolling metric history
            hist = self._metric_history.get(agent, [])
            if len(hist) >= 2:
                mn, mx = min(hist), max(hist)
                rng = mx - mn if mx > mn else 1.0
                spark = "".join(
                    self._SPARKLINE_CHARS[min(int((v - mn) / rng * 7), 7)] for v in hist
                )
                parts.append(f"[{Theme.info}]{spark}[/]")
            if parts:
                result.append(f"      [{Theme.info}]{'  '.join(parts)}[/]")

            # Simple epoch progress bar (████░░░░)
            if epoch is not None and total_epochs:
                bar_width = 20
                filled = max(0, min(epoch, total_epochs))
                fill_count = int(filled / max(total_epochs, 1) * bar_width)
                empty_count = bar_width - fill_count
                bar = "\u2588" * fill_count + "\u2591" * empty_count
                result.append(
                    f"      [{Theme.info}]{bar}[/]  [{Theme.muted}]{int(filled/max(total_epochs,1)*100)}%[/]"
                )

        elif agent == "Dissect" and detail:
            diff = detail.get("diff", detail.get("diff_applied", ""))
            if diff:
                diff_preview = diff.splitlines()[:6]
                for dline in diff_preview:
                    if dline.startswith("+") and not dline.startswith("+++"):
                        result.append(f"      [{Theme.success}]{dline}[/]")
                    elif dline.startswith("-") and not dline.startswith("---"):
                        result.append(f"      [{Theme.error}]{dline}[/]")
                    else:
                        result.append(f"      [{Theme.muted}]{dline}[/]")
                if len(diff.splitlines()) > 6:
                    result.append(
                        f"      [{Theme.muted}]\u25be {len(diff.splitlines()) - 6} more lines[/]"
                    )

        elif agent == "Scout" and detail:
            # Dataset summary + EDA progress — Ch.6.2 Scout widget
            rows = detail.get("num_rows")
            cols = detail.get("num_columns")
            if rows is not None and cols is not None:
                result.append(
                    f"      [{Theme.info}]Reading dataset: {rows} rows, {cols} columns[/]"
                )
            feature_types = detail.get("feature_types", {})
            if feature_types:
                cats = sum(1 for v in feature_types.values() if v == "categorical")
                nums = sum(1 for v in feature_types.values() if v == "numeric")
                txt = sum(1 for v in feature_types.values() if v == "text")
                parts = []
                if nums:
                    parts.append(f"{nums} numeric")
                if cats:
                    parts.append(f"{cats} categorical")
                if txt:
                    parts.append(f"{txt} text")
                if parts:
                    result.append(f"      [{Theme.muted}]{'  |  '.join(parts)}[/]")
            # Progress indicator
            eda_pct = detail.get("eda_progress", detail.get("progress", 0))
            if eda_pct:
                bar_width = 12
                fill_count = int(min(eda_pct, 100) / 100 * bar_width)
                bar = "\u2588" * fill_count + "\u2591" * (bar_width - fill_count)
                result.append(f"      [{Theme.info}]EDA {bar}[/]  [{Theme.muted}]{eda_pct}%[/]")

        elif agent == "Forge" and detail:
            # File path + syntax verification badge — Ch.6.2 Forge widget
            script_path = detail.get("script_path", detail.get("path", ""))
            if script_path:
                result.append(f"      [{Theme.info}]Writing training script...[/]")
                result.append(f"      [{Theme.muted}]{script_path}[/]")
            architecture = detail.get("architecture", detail.get("model", ""))
            if architecture:
                result.append(f"      [{Theme.secondary}]\u2192 {architecture}[/]")
            syntax_ok = detail.get("syntax_ok")
            if syntax_ok is True:
                result.append(f"      [{Theme.success}]\u2714 Syntax: OK[/]")
            elif syntax_ok is False:
                result.append(f"      [{Theme.error}]\u2718 Syntax: FAIL[/]")

        elif agent == "Arbiter" and detail:
            # Metric table with pass/fail + histogram bars — Ch.6.2 Arbiter widget
            metrics_raw = detail.get("metrics", detail.get("results", {}))
            if isinstance(metrics_raw, dict):
                thresholds = detail.get("thresholds", {})
                for name, value in metrics_raw.items():
                    if isinstance(value, (int, float)):
                        threshold = thresholds.get(name, detail.get("threshold"))
                        if threshold is not None:
                            passed = (
                                value >= threshold
                                if detail.get("higher_is_better", True)
                                else value <= threshold
                            )
                            badge = (
                                f"[{Theme.success}]\u2714[/]"
                                if passed
                                else f"[{Theme.error}]\u2718[/]"
                            )
                            bar_w = 10
                            # Normalise value relative to threshold for bar width
                            ratio = (
                                min(value / max(abs(threshold), 1e-9), 2.0)
                                if detail.get("higher_is_better", True)
                                else min(threshold / max(abs(value), 1e-9), 2.0)
                            )
                            fill = max(0, min(int(ratio * bar_w), bar_w))
                            bar = "\u2588" * fill + "\u2591" * (bar_w - fill)
                            result.append(
                                f"      {badge}  [{Theme.secondary}]{name}[/]  "
                                f"[{Theme.info}]{value:.4f}[/]  "
                                f"[{Theme.muted}]threshold {threshold}[/]"
                            )
                            result.append(f"      [{Theme.info}]{bar}[/]")
                        else:
                            result.append(
                                f"      [{Theme.secondary}]{name}:[/]  [{Theme.info}]{value:.4f}[/]"
                            )
                    else:
                        result.append(f"      [{Theme.muted}]{name}:[/] {value}")
            failure_analysis = detail.get("failure_analysis", detail.get("analysis", ""))
            if failure_analysis:
                result.append(f"      [{Theme.muted}]analysis:[/] {failure_analysis}")

        elif agent == "Harbor" and detail:
            # Deploy checklist — Ch.6.2 Harbor widget
            checklist = detail.get("checklist", detail)
            steps = [
                ("onnx_export", "ONNX export"),
                ("fastapi_build", "FastAPI build"),
                ("docker_image", "Docker image"),
                ("deploy", "Deploy"),
                ("health_check", "Health check"),
            ]
            for key, label in steps:
                status = checklist.get(key, checklist.get(key.replace("_", ""), None))
                if status is True:
                    result.append(f"      [{Theme.success}]\u2714 {label}[/]")
                elif status is False:
                    result.append(f"      [{Theme.error}]\u2718 {label}[/]")
                else:
                    result.append(f"      [{Theme.muted}]\u25cb {label}[/]")
            endpoint_url = detail.get("endpoint_url", detail.get("url", ""))
            if endpoint_url:
                result.append(f"      [{Theme.info}]\u2192 {endpoint_url}[/]")

        else:
            if detail:
                for k, v in sorted(detail.items()):
                    result.append(f"      [{Theme.muted}]{k}:[/] {v}")

        return result

    def _render_verifying(self, summary: str, detail: dict | None) -> list[str]:
        """Spinner + pass/fail badge."""
        result: list[str] = []
        result.append(f"    [{Theme.info}]\u2713? {summary}[/]")
        if detail:
            passed = detail.get("passed")
            total = detail.get("total")
            if passed is not None and total is not None:
                result.append(
                    f"      [{Theme.success if passed == total else Theme.error}]{passed}/{total} passed[/]"
                )
        return result

    def render(self) -> str:
        if not self._events:
            orch = getattr(self.app, "_orchestrator_ok", None)
            if orch is False:
                return (
                    f"  [{Token.error}]\u26a0 Orchestrator is not running.[/]\n"
                    f"  [{Theme.muted}]Start it with:[/] [{Token.accent}]prometheus daemon start[/]"
                )
            return f"  [{Token.muted}]Awaiting agent events \u2026[/]"

        lines: list[str] = []
        ev = self._events[-1]
        agent = ev.get("agent", "")
        agent_color = AGENT_COLORS.get(agent, str(Theme.secondary))
        state = ev.get("state", "waiting")
        dur = ev.get("duration_ms", 0)

        # Badge line matching AgentBlock format: icon + name + duration
        is_alive = state in ("thinking", "planning", "acting")
        badge_icon = (
            _SPINNER_CHARS[self._spin_index] if is_alive else STATE_ICON.get(state, "\u25cb")
        )
        state_color = STATE_COLOR.get(state, str(Theme.disabled))
        dur_str = f"  [{Theme.muted}]({dur}ms)[/]" if dur else ""
        cursor_bar = ""
        if self._cursor_mode:
            cursor_bar = f"  [{Theme.warning}]\u2502 cursor on[/]"
        lines.append(
            f"  [{state_color}]{badge_icon}[/] [{agent_color}]{agent}[/]{dur_str}{cursor_bar}"
        )
        lines.append("")

        # Handoff banners at the top
        for banner in self._handoff_banners:
            lines.append(banner)
        for i, ev in enumerate(self._events):
            state = ev.get("state", "waiting")
            summary = ev.get("summary", "")
            ev_agent = ev.get("agent", "")
            dur = ev.get("duration_ms", 0)
            icon = STATE_ICON.get(state, "\u25cb")
            color = STATE_COLOR.get(state, str(Theme.disabled))

            raw_detail = ev.get("detail", "")
            detail: dict | None = None
            if raw_detail:
                try:
                    decoded = json.loads(raw_detail) if isinstance(raw_detail, str) else raw_detail
                    detail = decoded if isinstance(decoded, dict) else None
                except (json.JSONDecodeError, TypeError):
                    pass

            is_live = state in ("thinking", "planning", "acting") and i == len(self._events) - 1
            if is_live:
                icon = _SPINNER_CHARS[self._spin_index]

            # Cursor indicator — highlight the selected event line
            cursor_marker = ""
            cursor_style = ""
            if self._cursor_mode and i == self._cursor_index:
                cursor_marker = "> "
                cursor_style = f"reverse {str(Theme.warning)} "

            state_label = state.lower()
            dur_str = f"({dur}ms)" if dur else ""
            header_parts = [f"  [{cursor_style}{color}]{cursor_marker}{icon} {state_label}[/]"]
            if summary:
                header_parts.append(summary)
            if dur_str:
                header_parts.append(f"[{Theme.muted}]{dur_str}[/]")
            lines.append("  ".join(header_parts))

            # State-specific detail rendering per Ch.6.2
            if state == "thinking":
                lines.extend(self._render_thinking(summary, is_live, detail, ev_agent))
            elif state == "planning":
                lines.extend(self._render_planning(summary, detail))
            elif state == "acting":
                lines.extend(self._render_acting(state, summary, detail, ev_agent))
            elif state == "verifying":
                lines.extend(self._render_verifying(summary, detail))
            else:
                if detail:
                    for k, v in sorted(detail.items()):
                        lines.append(f"      [{Theme.muted}]{k}:[/] {v}")

        return "\n".join(lines)

    @property
    def last_summary(self) -> str:
        """Return the *verbatim* summary of the most recent event, or empty."""
        if self._events:
            return self._events[-1].get("summary", "")
        return ""


# ── Keybinding footer bar ───────────────────────────────────────────────


class CockpitFooter(Static):
    """Bottom bar showing keybindings for the live Cockpit.

    Replaced by ReplayController in replay mode.
    """

    def render(self) -> str:
        sep = f"  [{Theme.muted}][/]"
        parts = [
            f"[{Theme.muted}][tab][/] agent",
            f"[{Theme.muted}][t][/] think",
            f"[{Theme.muted}][d][/] diff",
            f"[{Theme.muted}][l][/] logs",
            f"[{Theme.muted}][Shift+\u2191][/] cursor",
            f"[{Theme.muted}][Ctrl+O][/] view",
            f"[{Theme.muted}][Ctrl+T][/] tasks",
            f"[{Theme.muted}][Ctrl+P][/] model",
            f"[{Theme.muted}][p][/] detach",
        ]
        return f"  {sep.join(parts)}"


# ── Replay controller bar ──────────────────────────────────────────────


class ReplayController(Static):
    """Thin footer bar showing replay position and play/pause status.

    Only visible when the Cockpit is in trace-replay mode.
    """

    def render(self) -> str:
        app = self.app
        replay = getattr(app, "_replay", None)
        if replay is None:
            return ""

        idx = replay.current_index
        total = replay.total
        paused = replay.paused

        pause_icon = "\u23f8"
        play_icon = "\u25b6"
        status = (
            f"[{Theme.warning}] {pause_icon} PAUSED[/]"
            if paused
            else f"[{Theme.success}] {play_icon} PLAYING[/]"
        )
        current = max(0, idx) + 1
        position = f"[{Theme.secondary}]Event {current}/{total}[/]" if total > 0 else ""

        bar_width = 20
        if total > 0:
            filled = int(current / total * bar_width)
        else:
            filled = 0
        block_fill = "\u2588"
        block_empty = "\u2591"
        bar = f"[{Theme.info}]{block_fill * filled}{Theme.muted}{block_empty * (bar_width - filled)}[/]"

        right_arrow = "\u2192"
        left_arrow = "\u2190"
        controls = f"[{Theme.muted}]Space=play/pause  {right_arrow}/{left_arrow}=step  G=go-to[/]"

        parts = [status, position, bar, controls]
        return "  ".join(p for p in parts if p)


# ── Event log overlay screen ─────────────────────────────────────────


class LogScreen(ModalScreen[None]):
    """Scrollable event log overlay showing all events for the current agent.

    Opened by pressing ``l`` in the Cockpit.  Each line shows:
    timestamp + state + summary, colour-coded by state.
    Supports filtering by state type (press ``f``) and
    text search (press ``/``) across summaries.
    """

    CSS = """
    LogScreen {
        align: center middle;
        background: #0f0f1a 85%;
    }

    #log-box {
        width: 90%;
        height: 85%;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
        overflow-y: auto;
    }

    #log-search-input {
        dock: bottom;
        height: 3;
        padding: 0 2;
        background: #16213e;
        border: solid $accent;
    }

    #log-footer {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: #16213e;
    }
    """

    def __init__(self, events: list[dict[str, Any]], agent: str = "") -> None:
        super().__init__()
        self._all_events = list(events)
        self._filtered_events = list(events)
        self._agent = agent
        self._search_text: str = ""
        self._filter_state: str = ""
        self._show_search = False
        self._show_filter = False

    def compose(self) -> ComposeResult:
        label = f" [{Theme.secondary}]{self._agent}[/]" if self._agent else ""
        title = f"[bold]{Theme.accent}EVENT LOG{label}[/]"
        log_lines = self._render_log()
        content = "\n".join([title, ""] + log_lines)
        with Static(id="log-box"):
            yield Static(content)
        yield Static(self._render_footer(), id="log-footer")

    def _apply_filters(self) -> None:
        events = self._all_events
        if self._filter_state:
            events = [e for e in events if e.get("state", "") == self._filter_state]
        if self._search_text:
            lower = self._search_text.lower()
            events = [
                e
                for e in events
                if lower in (e.get("summary") or e.get("event", "")).lower()
                or lower in (e.get("state", "")).lower()
            ]
        self._filtered_events = events

    def log_search_started(self, search_text: str) -> None:
        """Called when the user enters search text to filter events."""
        self._search_text = search_text
        self._apply_filters()
        self._refresh_display()

    def show_filter_input(self, state_type: str) -> None:
        """Called when the user selects a state type to filter by."""
        self._filter_state = state_type
        self._apply_filters()
        self._refresh_display()

    def _refresh_display(self) -> None:
        log_lines = self._render_log()
        title = f"[bold]{Theme.accent}EVENT LOG[/]"
        label = f" [{Theme.secondary}]{self._agent}[/]" if self._agent else ""
        content = "\n".join([title + label, ""] + log_lines)
        box = self.query_one("#log-box")
        if box and box.children:
            box.children[0].update(content)

    async def _prompt_search(self) -> None:
        from textual.widgets import Input

        search = await self.app.push_screen_wait(_SearchInputScreen())
        if search is not None:
            self.log_search_started(search)

    async def _prompt_filter(self) -> None:
        filter_val = await self.app.push_screen_wait(_FilterStateScreen())
        if filter_val is not None:
            self.show_filter_input(filter_val)

    async def key_slash(self) -> None:
        await self._prompt_search()

    async def key_f(self) -> None:
        await self._prompt_filter()

    def key_r(self) -> None:
        self._search_text = ""
        self._filter_state = ""
        self._apply_filters()
        self._refresh_display()

    def _render_log(self) -> list[str]:
        lines: list[str] = []
        if not self._filtered_events:
            if self._search_text or self._filter_state:
                lines.append(f"  [{Theme.muted}]No events match the current filter.[/]")
            else:
                lines.append(f"  [{Theme.muted}]No events recorded.[/]")
            return lines

        for i, ev in enumerate(self._filtered_events):
            ts = (ev.get("timestamp") or "")[:19] if ev.get("timestamp") else ""
            state = ev.get("state", "?")
            summary = (ev.get("summary") or ev.get("event", ""))[:120]
            dur = ev.get("duration_ms", 0)
            dur_str = f"  [{Theme.muted}]({dur}ms)[/]" if dur else ""

            state_color = (
                "green"
                if state in ("done", "complete", "success")
                else "red" if state in ("error", "failed", "crashed") else "yellow"
            )

            lines.append(
                f"  [{Theme.muted}]#{i + 1:>3}[/]"
                f"  [{Theme.muted}]{ts}[/]"
                f"  [{state_color}]{state:<12}[/]"
                f"  {summary}"
                f"{dur_str}"
            )

        return lines

    def _render_footer(self) -> str:
        total = len(self._all_events)
        shown = len(self._filtered_events)
        parts = []
        if self._search_text:
            parts.append(f'search: "{self._search_text}"')
        if self._filter_state:
            parts.append(f"filter: {self._filter_state}")
        status = f"  [{','.join(parts)}]  " if parts else ""
        return (
            f"  [{Theme.muted}]"
            f"{status}{shown}/{total} event(s)  "
            f"[/][/][{Theme.muted}]"
            f"[/][/]"
            f"[/]"
        )

    def key_g(self) -> None:
        """g — scroll to top of log."""
        box = self.query_one("#log-box")
        box.scroll_home(animate=False)

    def key_shift_g(self) -> None:
        """G — scroll to bottom of log."""
        box = self.query_one("#log-box")
        box.scroll_end(animate=False)

    def key_page_up(self) -> None:
        """PgUp — scroll up half a page."""
        self._scroll_page(-1)

    def key_page_down(self) -> None:
        """PgDn — scroll down half a page."""
        self._scroll_page(1)

    def _scroll_page(self, direction: int) -> None:
        box = self.query_one("#log-box")
        visible = box.size.height if box.size else 20
        half = max(1, visible // 2)
        box.scroll_relative(y=direction * half, animate=False)

    def key_c(self) -> None:
        """c — copy the full log text to clipboard."""
        text = "\n".join(line for line in self._render_log())
        copied = _copy_to_clipboard(text)
        if not copied:
            from prometheus.ui.console import console

            console.print(
                f"  [{Theme.info}]Clipboard not available — {len(text)} chars of log text[/]"
            )

    def key_j(self) -> None:
        """j — scroll down (accelerated with rapid presses)."""
        vel = self._scroll_accel()
        self.query_one("#log-box").scroll_relative(y=vel, animate=False)

    def key_k(self) -> None:
        """k — scroll up (accelerated with rapid presses)."""
        vel = self._scroll_accel()
        self.query_one("#log-box").scroll_relative(y=-vel, animate=False)

    # Scroll acceleration state
    _scroll_velocity = 1
    _scroll_decay = 0.0

    def _scroll_accel(self) -> int:
        import time as _t

        now = _t.monotonic()
        if now - self._scroll_decay < 0.25:
            self._scroll_velocity = min(self._scroll_velocity + 1, 12)
        else:
            self._scroll_velocity = 1
        self._scroll_decay = now
        return self._scroll_velocity

    def key_l(self) -> None:
        self.dismiss()

    def key_x(self) -> None:
        self.dismiss()

    def key_q(self) -> None:
        self.dismiss()

    def key_escape(self) -> None:
        self.dismiss()


class _SearchInputScreen(ModalScreen[str | None]):
    """Small modal asking for search text to filter events."""

    CSS = """
    _SearchInputScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #search-box {
        width: 50;
        height: 7;
        padding: 1 2;
        border: solid $accent;
        background: #1a1a2e;
    }
    """

    def compose(self) -> ComposeResult:
        with Static(id="search-box"):
            yield Static("[bold]Search event summaries:[/]")
            from textual.widgets import Input

            yield Input(id="search-input", placeholder="Enter search text...")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def key_escape(self) -> None:
        self.dismiss(None)


class _FilterStateScreen(ModalScreen[str | None]):
    """Small modal asking for a state type to filter by."""

    CSS = """
    _FilterStateScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #filter-box {
        width: 50;
        height: 7;
        padding: 1 2;
        border: solid $accent;
        background: #1a1a2e;
    }
    """

    _STATE_OPTIONS = [
        ("a", "All states (clear filter)"),
        ("t", "thinking"),
        ("p", "planning"),
        ("c", "acting"),
        ("v", "verifying"),
        ("d", "done"),
        ("e", "error"),
    ]

    def compose(self) -> ComposeResult:
        options = "\n".join(
            f"  [{Theme.secondary}]{key}[/]  {label}" for key, label in self._STATE_OPTIONS
        )
        with Static(id="filter-box"):
            yield Static(f"[bold]Filter by state type:[/]\n\n{options}")

    def on_key(self, event: events.Key) -> None:
        for key, label in self._STATE_OPTIONS:
            if event.key == key:
                val = label if key != "a" else ""
                self.dismiss(val)
                return
        if event.key == "escape":
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


# ── Agent picker screen (Ctrl+O) ───────────────────────────────────────


class AgentPickerScreen(ModalScreen[str | None]):
    """Small modal that shows all available agents and lets the user pick one.

    Opened by pressing ``Ctrl+O`` in the Cockpit.
    """

    CSS = """
    AgentPickerScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #picker-box {
        width: 40;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
    }
    """

    def __init__(self, agents: list[str]) -> None:
        super().__init__()
        self._agents = agents

    def compose(self) -> ComposeResult:
        entries = "\n".join(f"  [{Theme.secondary}]{i}[/]  {a}" for i, a in enumerate(self._agents))
        with Static(id="picker-box"):
            yield Static(f"[bold]Switch to agent:[/]\n\n{entries}")

    def on_key(self, event: events.Key) -> None:
        for i, a in enumerate(self._agents):
            if event.key == str(i):
                self.dismiss(a)
                return
        if event.key == "escape":
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


# ── Model/provider picker (Ctrl+P) ──────────────────────────────────────


_MODEL_OPTIONS = [
    ("claude-sonnet-4-6", "Anthropic", "Claude Sonnet 4.6"),
    ("claude-opus-4-6", "Anthropic", "Claude Opus 4.6"),
    ("claude-3-5-haiku", "Anthropic", "Claude 3.5 Haiku"),
    ("claude-3-opus", "Anthropic", "Claude 3 Opus"),
    ("gpt-4o", "OpenAI", "GPT-4o"),
    ("gpt-4o-mini", "OpenAI", "GPT-4o Mini"),
    ("local", "Local", "Ollama / vLLM"),
]


class ModelPickerScreen(ModalScreen[str | None]):
    """Quick-select menu to switch the active LLM model / provider.

    Opened by pressing ``Ctrl+P`` in the Cockpit.
    The choice is written to the project ``.env`` file via
    ``ProviderService``.
    """

    CSS = """
    ModelPickerScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #model-box {
        width: 50;
        height: auto;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
    }
    """

    def __init__(self, current_model: str = "") -> None:
        super().__init__()
        self._current = current_model

    def compose(self) -> ComposeResult:
        entries: list[str] = []
        for i, (model_id, provider, label) in enumerate(_MODEL_OPTIONS):
            indicator = f"[{Theme.success}]\u25cf[/]" if model_id == self._current else " "
            entries.append(f"  {indicator}  [{Theme.secondary}]{i}[/]  {provider} \u2014 {label}")
        with Static(id="model-box"):
            yield Static("[bold]Switch model / provider:[/]\n\n" + "\n".join(entries))

    def on_key(self, event: events.Key) -> None:
        for i, (model_id, _, _) in enumerate(_MODEL_OPTIONS):
            if event.key == str(i):
                self._switch(model_id)
                self.dismiss(model_id)
                return
        if event.key == "escape":
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)

    @staticmethod
    def _switch(model_id: str) -> None:
        try:
            from prometheus.services.provider_service import ProviderService

            svc = ProviderService()
            # Determine provider name from model_id prefix
            for mid, prov, _ in _MODEL_OPTIONS:
                if mid == model_id:
                    svc.add_provider(prov)
                    break
            # Also write the model env var
            from prometheus.services.config_service import ConfigService

            cfg = ConfigService()
            cfg.set("ANTHROPIC_MODEL", model_id)
        except Exception:
            pass


# ── Go-to-event screen ─────────────────────────────────────────────────


class GoToEventScreen(ModalScreen[int | None]):
    """Small modal that asks for an event number to jump to."""

    CSS = """
    GoToEventScreen {
        align: center middle;
        background: #0f0f1a 80%;
    }

    #goto-box {
        width: 40;
        height: 7;
        padding: 1 2;
        border: solid $primary;
        background: #1a1a2e;
    }

    #goto-input {
        width: 100%;
    }
    """

    def __init__(self, max_event: int = 0) -> None:
        super().__init__()
        self._max = max_event

    def compose(self) -> ComposeResult:
        from textual.widgets import Input

        max_str = f" (0\u2013{self._max})" if self._max > 0 else ""
        with Static(id="goto-box"):
            yield Static(f"[bold]Go to event{max_str}[/]")
            yield Input(id="goto-input", placeholder="Enter event number...")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        try:
            n = int(event.value.strip())
            n = max(0, min(n, self._max))
            self.dismiss(n)
        except (ValueError, TypeError):
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)

# ruff: noqa: E501 — display strings with long styled fragments
"""Scroll-forward streaming renderer — the heart of the new CLI.

Replaces both ``UnifiedLiveRenderer`` (rich.Live screen-rewrite) and
``LiveTreeRenderer`` with a single, scroll-based streaming architecture:

1. Lines are printed ONCE and scroll up (no rich.Live).
2. Only the ACTIVE LINE (spinner + thinking tail) rewrites via ``\\r``.
3. The header is updated in-place via ANSI cursor-up (docker compose style).
4. All state is driven by real Redis events (Rule 1).
5. Full scrollback — user can scroll up to review any agent.

Streaming modes per agent::

    Scout, Forge, Arbiter, Harbor → ACTIVITY (step-by-step subactions)
    Furnace                      → PROGRESS (progress bar + epoch metrics)
    Dissect                      → THINKING (raw LLM token stream + cascade)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import shutil
import sys
import time
from enum import Enum
from typing import Any, Callable

import redis.asyncio as aioredis
from rich.console import Console
from rich.text import Text

from bus.consumer import ensure_consumer_group
from bus.events import (
    GROUP_COCKPIT,
    STREAM_AGENT_EVENTS,
    STREAM_AGENT_THINKING,
    STREAM_SUBACTION,
)
from prometheus.ui.stream.agent_badge import (
    render_badge,
    render_subaction,
    render_thinking_line,
    render_thinking_summary,
    render_detail_line,
    text_to_ansi,
)
from prometheus.ui.stream.cost_tracker import emit_bell, render_completion_line
from prometheus.ui.stream.header import AGENT_ORDER
from prometheus.ui.stream.progress_bar import render_progress
from prometheus.ui.stream.summary_card import SummaryData, render_summary
from prometheus.ui.stream.thinking_stream import ThinkingStream
from prometheus.ui.stream.transition import render_transition

logger = logging.getLogger(__name__)


# ── Agent streaming modes ────────────────────────────────────────────────


class AgentStreamMode(Enum):
    ACTIVITY = "activity"  # Scout, Forge, Arbiter, Harbor
    PROGRESS = "progress"  # Furnace
    THINKING = "thinking"  # Dissect


AGENT_STREAM_MODES = {
    "Scout": AgentStreamMode.ACTIVITY,
    "Forge": AgentStreamMode.ACTIVITY,
    "Furnace": AgentStreamMode.PROGRESS,
    "Dissect": AgentStreamMode.THINKING,
    "Arbiter": AgentStreamMode.ACTIVITY,
    "Harbor": AgentStreamMode.ACTIVITY,
}


# ── Subaction noise filter (display-only) ────────────────────────────────
# Vacuous "doing…" / phase-complete lines whose content is fully carried by a
# later structured detail line. Applied via startswith in the renderer only —
# the event bus always records the real signal (Rule 1).
NOISE_SUBACTION_PREFIXES: tuple[str, ...] = (
    "Starting analysis...",
    "Profiling dataset...",
    "Analysing dataset characteristics...",
    "EDA complete",
    "Engineering reasoning complete",
)


# ── Paced reveal ─────────────────────────────────────────────────────────
_REVEAL_DELAY = 0.15  # Seconds between revealed lines in a burst
_STAGGER_MAX_QUEUE = 5  # Max lines paced per tick; overflow flushes at once


# ── Per-agent state ──────────────────────────────────────────────────────


class _AgentState:
    """Mutable state for a single agent during the mission."""

    __slots__ = (
        "name",
        "status",
        "summary",
        "details",
        "subactions",
        "start_time",
        "end_time",
        "thinking",
        "progress",
        "progress_detail",
        "cascade_level",
        "cascade_states",
    )

    def __init__(self, name: str) -> None:
        self.name = name
        self.status: str = "pending"  # pending|active|done|error
        self.summary: str = ""
        self.details: dict[str, Any] = {}
        self.subactions: list[tuple[str, str]] = []  # (detail, state)
        self.start_time: float = 0.0
        self.end_time: float = 0.0
        self.thinking: ThinkingStream = ThinkingStream()
        self.progress: float = 0.0
        self.progress_detail: str = ""
        self.cascade_level: int = 0
        self.cascade_states: dict[int, str] = {}  # level → done|running|pending

    @property
    def elapsed(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        if self.start_time:
            return time.monotonic() - self.start_time
        return 0.0


# ═══════════════════════════════════════════════════════════════════════════
# StreamRenderer — the main class
# ═══════════════════════════════════════════════════════════════════════════


class StreamRenderer:
    """Scroll-forward streaming renderer for mission output.

    Consumes Redis event streams and renders real-time output to the
    terminal. Each line is printed once and scrolls up. Only the active
    badge line and (for Dissect) the thinking tail are rewritten.

    Usage::

        renderer = StreamRenderer(redis, mission_id, description)
        await renderer.setup()
        await renderer.run()
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        mission_id: str,
        problem_description: str = "",
        **kwargs: Any,
    ) -> None:
        self._redis = redis
        self._mission_id = mission_id
        self._problem = problem_description
        self._dataset_name = kwargs.get("dataset_name", "")
        self._num_rows = kwargs.get("num_rows", 0)

        # ── Console for Rich → ANSI conversion ──
        self._console = Console(
            emoji=False,
            safe_box=True,
            no_color=False,
            color_system="auto",
            highlight=False,
        )

        # ── Terminal dimensions ──
        try:
            self._width = shutil.get_terminal_size().columns
        except (OSError, AttributeError):
            self._width = 80

        # ── State ──
        self._agents: dict[str, _AgentState] = {name: _AgentState(name) for name in AGENT_ORDER}
        self._agent_states: dict[str, str] = {a: "pending" for a in AGENT_ORDER}
        self._mission_status: str = "starting"
        self._active_agent: str | None = None
        self._last_completed_agent: str | None = None

        # ── Scroll-forward bookkeeping ──
        self._lines_since_header: int = 0
        self._badge_line_offset: int = 0  # Lines below badge for cursor-up
        self._header_printed: bool = False
        self._mission_start: float = 0.0
        self._running: bool = False
        self._ready: bool = False

        # ── Summary data ──
        self._summary_data: dict[str, Any] = {}

        # ── Paced-reveal state ──
        self._batching: bool = False
        self._pending_actions: list[Callable[[], None]] = []

        # ── Consumer identity: unique per instance so concurrent renderers
        # never share a consumer name (which splits deliveries in the group).
        self._consumer_id = f"{os.getpid()}-{secrets.token_hex(4)}"

    # ── Setup ────────────────────────────────────────────────────────────

    async def setup(self) -> None:
        """Create consumer groups before the job starts."""
        await ensure_consumer_group(
            self._redis,
            STREAM_AGENT_EVENTS,
            GROUP_COCKPIT,
            start_id="$",
        )
        try:
            await ensure_consumer_group(
                self._redis,
                STREAM_AGENT_THINKING,
                GROUP_COCKPIT,
                start_id="$",
            )
            await ensure_consumer_group(
                self._redis,
                STREAM_SUBACTION,
                GROUP_COCKPIT,
                start_id="$",
            )
        except Exception:
            pass
        self._ready = True

    # ── Output primitives ────────────────────────────────────────────────

    def _emit_permanent(self, text: str | Text) -> None:
        """Print a line that will never be rewritten. Scrolls down.

        While ``_batching`` is active (inside a ``_poll_events`` tick on a
        TTY), the line is queued and revealed by ``_reveal_paced`` instead of
        printing immediately. Non-TTY output always prints immediately.
        """
        if self._batching and sys.stdout.isatty():
            self._pending_actions.append(lambda: self._flush_permanent(text))
            return
        self._flush_permanent(text)

    def _flush_permanent(self, text: str | Text) -> None:
        """Immediately write a permanent line (batched or not)."""
        if isinstance(text, Text):
            ansi = text_to_ansi(text, width=self._width)
        else:
            ansi = text
        sys.stdout.write(f"\r\033[K{ansi}\n")
        sys.stdout.flush()
        self._lines_since_header += 1
        self._badge_line_offset += 1

    def _emit_permanent_rich(self, text: Text) -> None:
        """Print a Rich Text permanently using the console."""
        if self._batching and sys.stdout.isatty():
            self._pending_actions.append(lambda: self._flush_permanent_rich(text))
            return
        self._flush_permanent_rich(text)

    def _flush_permanent_rich(self, text: Text) -> None:
        """Immediately write a Rich Text line (batched or not)."""
        self._console.print(text, highlight=False)
        # Count how many terminal lines the text occupied
        plain = text.plain
        lines = plain.count("\n") + 1
        self._lines_since_header += lines
        self._badge_line_offset += lines

    def _flush_pending_now(self) -> None:
        """Synchronously print all queued lines now, preserving order."""
        actions = self._pending_actions
        self._pending_actions = []
        for act in actions:
            act()

    def _rewrite_badge(self, text: str | Text) -> None:
        """Rewrite the active agent's badge line in-place."""
        if isinstance(text, Text):
            ansi = text_to_ansi(text, width=self._width)
        else:
            ansi = text

        up = self._badge_line_offset
        # If the badge has scrolled off screen, don't update it to prevent corruption
        import shutil

        try:
            term_height = shutil.get_terminal_size().lines
        except (OSError, AttributeError):
            term_height = 40

        if up >= term_height - 1:
            return

        # When moving cursor up, we must move up 'up' lines.
        sys.stdout.write(f"\033[s\033[{up}A\r\033[K{ansi}\033[u")
        sys.stdout.flush()

    def _rewrite_last_line(self, text: str | Text) -> None:
        """Rewrite the very last line (thinking tail / progress bar)."""
        if isinstance(text, Text):
            ansi = text_to_ansi(text, width=self._width)
        else:
            ansi = text
        sys.stdout.write(f"\r\033[K{ansi}")
        sys.stdout.flush()

    # ── Agent lifecycle ──────────────────────────────────────────────────

    def _start_agent(self, name: str) -> None:
        """Begin streaming for a new agent."""
        agent = self._agents[name]
        agent.status = "active"
        agent.start_time = time.monotonic()
        self._agent_states[name] = "running"
        self._active_agent = name

        if self._mission_status == "starting":
            self._mission_status = "running"

        # Print blank line before agent block
        self._emit_permanent("")

        # Print the initial badge line (this becomes the rewritable line)
        badge = render_badge(
            name=name,
            status="active",
            summary=agent.summary or "Starting…",
            elapsed=0.0,
            tick=time.monotonic(),
        )
        ansi = text_to_ansi(badge, width=self._width)
        sys.stdout.write(f"\r\033[K{ansi}\n")
        sys.stdout.flush()
        self._lines_since_header += 1
        self._badge_line_offset = 1  # Cursor is now 1 line below the badge

    def _finalize_agent(self, name: str) -> None:
        """Print the agent's final state permanently."""
        agent = self._agents[name]
        if not agent.end_time:
            agent.end_time = time.monotonic()

        # Rewrite the badge line with final state
        badge = render_badge(
            name=name,
            status=agent.status,
            summary=agent.summary,
            elapsed=agent.elapsed,
            tick=0.0,
        )
        self._rewrite_badge(badge)

        # Print detail lines below the badge
        mode = AGENT_STREAM_MODES.get(name, AgentStreamMode.ACTIVITY)

        if mode == AgentStreamMode.THINKING and agent.thinking.has_content:
            # Print thinking token summary
            self._emit_permanent(render_thinking_summary(agent.thinking.token_count))

        # Print key detail lines
        details = self._build_detail_pairs(name)
        if details:
            detail_str = "  ".join(f"{k}={v}" for k, v in details)
            self._emit_permanent(render_detail_line("", detail_str))

        if self._active_agent == name:
            self._active_agent = None
            self._last_completed_agent = name

    def _build_detail_pairs(self, name: str) -> list[tuple[str, str]]:
        """Extract key detail pairs for an agent's finalized view."""
        agent = self._agents[name]
        pairs: list[tuple[str, str]] = []

        if name == "Scout":
            for key in ("task_type", "modality", "confidence"):
                if key in agent.details:
                    pairs.append((key, str(agent.details[key])))
            for key in ("num_rows", "num_columns"):
                if key in agent.details:
                    pairs.append((key, str(agent.details[key])))
        elif name == "Forge":
            if "architecture" in agent.details:
                pairs.append(("architecture", agent.details["architecture"]))
            if "confidence" in agent.details:
                pairs.append(("confidence", str(agent.details["confidence"])))
        elif name == "Furnace":
            if "best_metric" in agent.details:
                pairs.append(("best", str(agent.details["best_metric"])))
            if "epoch" in agent.details:
                pairs.append(("epoch", agent.details["epoch"]))
        elif name == "Arbiter":
            for key in ("metric_name", "val_metric", "decision"):
                if key in agent.details:
                    pairs.append((key, str(agent.details[key])))
        elif name == "Harbor":
            if "endpoint_url" in agent.details:
                pairs.append(("endpoint", agent.details["endpoint_url"]))
            if "model_format" in agent.details:
                pairs.append(("format", agent.details["model_format"]))

        return pairs[:4]  # Cap at 4 detail pairs

    def _emit_transition(self, from_agent: str, to_agent: str, reason: str = "") -> None:
        """Print a transition banner between agents."""
        self._emit_permanent("")
        t = render_transition(from_agent, to_agent, reason, width=self._width)
        self._emit_permanent(t)
        self._emit_permanent("")

    # ── Event handling ───────────────────────────────────────────────────

    def _handle_agent_event(self, msg: dict[str, Any]) -> None:
        """Route an agent_events stream message."""
        agent_name = str(msg.get("agent", ""))
        state = str(msg.get("state", ""))
        summary = str(msg.get("summary", ""))
        detail = msg.get("detail", {})
        mid = str(msg.get("mission_id", ""))

        if not agent_name or not state:
            return
        if mid and mid != self._mission_id:
            return
        if agent_name not in self._agents:
            return

        agent = self._agents[agent_name]

        # Display-only noise filter (see NOISE_SUBACTION_PREFIXES): vacuous
        # "doing…" / phase-complete lines are suppressed from the subaction
        # line, the transition reason, and the badge summary. The event still
        # drives agent lifecycle state (Rule 1 — real signal preserved).
        if summary.startswith(NOISE_SUBACTION_PREFIXES):
            summary = ""

        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except (json.JSONDecodeError, TypeError):
                detail = {}

        if summary:
            agent.summary = summary

        # Extract structured details
        self._extract_details(agent_name, detail)

        if state in ("thinking", "planning", "acting", "verifying"):
            # ── Agent becoming active ──
            if agent.status == "pending":
                # Flush any queued tail lines (previous agent's finalize
                # details) so they print above the transition banner.
                self._flush_pending_now()

                # Print the finalize/banner/badge sequence synchronously (no
                # pacing) so display order always matches stream order. The
                # active agent is the authoritative transition source —
                # _last_completed_agent may be stale if a done event was lost.
                self._batching = False
                try:
                    if self._active_agent and self._active_agent != agent_name:
                        # Previous agent didn't formally complete — finalize it
                        prev = self._agents[self._active_agent]
                        if prev.status == "active":
                            prev.status = "done"
                            prev.summary = prev.summary or "Complete"
                            self._agent_states[self._active_agent] = "complete"
                            self._finalize_agent(self._active_agent)
                        self._emit_transition(self._active_agent, agent_name, summary or "")
                    elif self._last_completed_agent and self._last_completed_agent != agent_name:
                        self._emit_transition(self._last_completed_agent, agent_name, summary or "")

                    self._start_agent(agent_name)
                finally:
                    self._batching = True

            # ── Emit subaction for ACTIVITY mode agents ──
            mode = AGENT_STREAM_MODES.get(agent_name, AgentStreamMode.ACTIVITY)
            if mode == AgentStreamMode.ACTIVITY and summary:
                sub_state = "planning" if state == "planning" else "running"
                sub = render_subaction(summary, state=sub_state)
                self._emit_permanent(sub)

            # ── Update Furnace progress ──
            if mode == AgentStreamMode.PROGRESS and isinstance(detail, dict):
                self._update_furnace_progress(agent_name, detail, summary)

            # ── Update badge ──
            badge = render_badge(
                name=agent_name,
                status="active",
                summary=agent.summary,
                elapsed=agent.elapsed,
                tick=time.monotonic(),
            )
            self._rewrite_badge(badge)

        elif state == "done":
            agent.status = "done"
            agent.end_time = time.monotonic()
            agent.summary = summary or "Complete"
            self._agent_states[agent_name] = "complete"

            # Collect summary data for Arbiter/Harbor
            self._collect_mission_data(agent_name, detail)

            self._finalize_agent(agent_name)

        elif state == "error":
            agent.status = "error"
            agent.end_time = time.monotonic()
            agent.summary = summary or "Failed"
            self._agent_states[agent_name] = "error"
            self._mission_status = "error"

            # Print error detail
            if isinstance(detail, dict):
                for k in ("error", "reason"):
                    err = detail.get(k)
                    if err:
                        self._emit_permanent(render_subaction(f"Error: {err}", state="error"))
                        break

            self._finalize_agent(agent_name)

    def _handle_thinking_delta(self, msg: dict[str, Any]) -> None:
        """Handle a thinking token from the agent_thinking stream (Dissect only)."""
        agent_name = str(msg.get("agent", ""))
        token = msg.get("token", "") or msg.get("text", "")

        if not agent_name or not token:
            return
        if agent_name not in self._agents:
            return

        agent = self._agents[agent_name]
        mode = AGENT_STREAM_MODES.get(agent_name, AgentStreamMode.ACTIVITY)

        if mode != AgentStreamMode.THINKING:
            return

        agent.thinking.append_token(token)

        # Drain completed lines → print permanently
        complete = agent.thinking.drain_complete_lines(width=self._width - 16)
        for line in complete:
            self._emit_permanent(render_thinking_line(line))

        # Rewrite the active tail
        tail = agent.thinking.render_active_tail(width=self._width - 16)
        if tail:
            self._rewrite_last_line(render_thinking_line(tail))

    def _handle_subaction(self, msg: dict[str, Any], msg_id: str = "") -> None:
        """Handle a subaction_progress stream message."""
        agent_name = str(msg.get("agent", ""))
        detail_text = str(msg.get("detail", ""))
        sub_state = str(msg.get("state", "running"))
        progress_val = msg.get("progress")

        if not agent_name or agent_name not in self._agents:
            return

        agent = self._agents[agent_name]
        mode = AGENT_STREAM_MODES.get(agent_name, AgentStreamMode.ACTIVITY)

        # For Furnace, update the progress bar
        if mode == AgentStreamMode.PROGRESS and progress_val is not None:
            try:
                agent.progress = float(progress_val)
            except (ValueError, TypeError):
                pass
            if detail_text:
                agent.progress_detail = detail_text
            bar = render_progress(
                label="Training",
                progress=agent.progress,
                detail=agent.progress_detail,
            )
            self._rewrite_last_line(bar)
            return

        # For ACTIVITY mode agents, print the subaction as a permanent line
        if detail_text and not detail_text.startswith(NOISE_SUBACTION_PREFIXES):
            agent.subactions.append((detail_text, sub_state))
            self._emit_permanent(render_subaction(detail_text, state=sub_state))

        # For Dissect cascade tracking
        if agent_name == "Dissect" and "cascade_level" in msg:
            level = int(msg["cascade_level"])
            agent.cascade_level = level
            agent.cascade_states[level] = sub_state

    def _update_furnace_progress(
        self,
        name: str,
        detail: dict[str, Any],
        summary: str = "",
    ) -> None:
        """Update Furnace's progress bar from event data."""
        agent = self._agents[name]

        epoch = detail.get("epoch")
        total_epochs = detail.get("total_epochs")
        fold = detail.get("fold")
        total_folds = detail.get("total_folds")
        loss = detail.get("loss")
        metric_val = detail.get("metric_value")
        progress = detail.get("progress")

        # Compute progress from epoch/fold data if not provided directly
        if progress is not None:
            try:
                agent.progress = float(progress)
            except (ValueError, TypeError):
                pass
        elif epoch and total_epochs:
            try:
                agent.progress = int(epoch) / int(total_epochs)
            except (ValueError, TypeError, ZeroDivisionError):
                pass

        # Build detail string
        parts: list[str] = []
        if fold and total_folds:
            parts.append(f"Fold {fold}/{total_folds}")
        if epoch and total_epochs:
            e = min(int(epoch), int(total_epochs))
            parts.append(f"Epoch {e}/{total_epochs}")
        agent.progress_detail = "  ".join(parts)

        # Store metrics for summary
        if metric_val is not None:
            agent.details["best_metric"] = f"{float(metric_val):.4f}"
        if epoch and total_epochs:
            e = min(int(epoch), int(total_epochs))
            agent.details["epoch"] = f"{e}/{total_epochs}"

        # Print epoch completion as a permanent subaction
        if loss is not None and epoch is not None:
            fold_str = f"Fold {fold}" if fold else "Epoch"
            metric_str = f"loss={float(loss):.4f}"
            if metric_val is not None:
                metric_str += f"  metric={float(metric_val):.4f}"
            line = f"{fold_str} {epoch}: {metric_str}"
            self._emit_permanent(render_subaction(line, state="done"))

        # Render the progress bar
        bar = render_progress(
            label="Training",
            progress=agent.progress,
            detail=agent.progress_detail,
        )
        self._rewrite_last_line(bar)

    def _extract_details(self, name: str, detail: dict[str, Any]) -> None:
        """Extract structured details from event data."""
        if not isinstance(detail, dict):
            return
        agent = self._agents[name]

        if name == "Scout":
            for k in ("num_rows", "num_columns", "confidence", "task_type", "modality"):
                if k in detail:
                    agent.details[k] = detail[k]
        elif name == "Forge":
            for k in ("architecture", "confidence", "rationale", "candidates"):
                if k in detail:
                    agent.details[k] = detail[k]
        elif name == "Furnace":
            if "epoch" in detail and "total_epochs" in detail:
                e = min(int(detail["epoch"]), int(detail["total_epochs"]))
                agent.details["epoch"] = f"{e}/{detail['total_epochs']}"
            if "metric_value" in detail:
                agent.details["best_metric"] = f"{float(detail['metric_value']):.4f}"
        elif name == "Arbiter":
            for k in ("metric_name", "val_metric", "threshold", "operator", "decision"):
                if k in detail:
                    agent.details[k] = detail[k]
        elif name == "Harbor":
            for k in ("endpoint_url", "model_format", "model_name", "port"):
                if k in detail:
                    agent.details[k] = detail[k]
            for k in ("drift_enabled", "drift_psi", "drift_feature", "drift_threshold"):
                if k in detail:
                    self._summary_data[k] = detail[k]

    def _collect_mission_data(self, name: str, detail: dict[str, Any]) -> None:
        """Collect mission-level data for the summary card."""
        if not isinstance(detail, dict):
            return

        if name == "Arbiter":
            for k in ("metric_name", "val_metric", "threshold", "operator", "decision"):
                if k in detail:
                    self._summary_data[k] = detail[k]

        if name == "Harbor":
            for k in ("endpoint_url", "model_format", "model_name"):
                if k in detail:
                    self._summary_data[k] = detail[k]

        if name == "Forge":
            if "architecture" in detail:
                self._summary_data["architecture"] = detail["architecture"]

    # ── Mission lifecycle ────────────────────────────────────────────────

    def _all_terminal(self) -> bool:
        terminal = {"complete", "error", "disabled"}
        return all(self._agent_states.get(a, "pending") in terminal for a in AGENT_ORDER)

    def _resolve_remaining(self, terminal: str) -> None:
        """Force unfinished agents to a terminal state."""
        for name in AGENT_ORDER:
            cur = self._agent_states.get(name, "pending")
            if cur in ("pending", "running"):
                self._agent_states[name] = terminal
                agent = self._agents[name]
                agent.status = terminal
                if not agent.end_time:
                    agent.end_time = time.monotonic()

    def _scan_artifacts(self) -> list[dict[str, Any]]:
        artifacts_dir = os.path.join(os.getcwd(), "outputs", self._mission_id)
        artifacts = []
        if os.path.isdir(artifacts_dir):
            for fname in sorted(os.listdir(artifacts_dir)):
                fpath = os.path.join(artifacts_dir, fname)
                if os.path.isfile(fpath):
                    artifacts.append(
                        {
                            "name": fname,
                            "size_bytes": os.path.getsize(fpath),
                        }
                    )
        return artifacts

    async def _render_mission_summary(self) -> None:
        """Print the mission summary card and completion line."""
        is_success = self._mission_status == "complete"
        elapsed = time.monotonic() - self._mission_start

        def _safe_float(val: Any, default: float = 0.0) -> float:
            try:
                if val is None:
                    return default
                return float(val)
            except (ValueError, TypeError):
                return default

        # Fetch cost summary from Redis
        total_tokens = sum(a.thinking.token_count for a in self._agents.values())
        total_cost = 0.0
        try:
            api_cost_summary = await self._redis.hgetall(f"job:{self._mission_id}:api_cost_summary")
            if api_cost_summary:
                total_tokens = int(
                    api_cost_summary.get(
                        (
                            b"total_tokens"
                            if isinstance(list(api_cost_summary.keys())[0], bytes)
                            else "total_tokens"
                        ),
                        total_tokens,
                    )
                )
                total_cost = float(
                    api_cost_summary.get(
                        (
                            b"total_cost_usd"
                            if isinstance(list(api_cost_summary.keys())[0], bytes)
                            else "total_cost_usd"
                        ),
                        0.0,
                    )
                )
        except Exception:
            pass

        endpoint = str(self._summary_data.get("endpoint_url", ""))
        health_status = str(self._summary_data.get("health_status", ""))
        health_latency_ms = _safe_float(self._summary_data.get("health_latency_ms"))

        if endpoint and not health_status:
            import httpx

            try:
                t0 = time.time()
                async with httpx.AsyncClient(timeout=1.0) as client:
                    resp = await client.get(f"{endpoint}/health")
                health_latency_ms = (time.time() - t0) * 1000.0
                health_status = "healthy" if resp.status_code == 200 else f"HTTP {resp.status_code}"
            except Exception:
                health_status = "unreachable"

        # Build summary data
        data = SummaryData(
            mission_id=self._mission_id,
            status="complete" if is_success else "error",
            winner_architecture=str(self._summary_data.get("architecture", "")),
            metric_name=str(self._summary_data.get("metric_name", "")),
            metric_value=_safe_float(self._summary_data.get("val_metric")),
            threshold=(
                _safe_float(self._summary_data.get("threshold"))
                if "threshold" in self._summary_data and self._summary_data["threshold"] is not None
                else None
            ),
            duration_seconds=elapsed,
            endpoint_url=endpoint,
            model_format=str(self._summary_data.get("model_format", "onnx")),
            health_status=health_status,
            health_latency_ms=health_latency_ms,
            artifacts=self._scan_artifacts(),
            dissect_patches=int(self._summary_data.get("dissect_patches", 0)),
            dissect_categories=self._summary_data.get("dissect_categories", []),
            agent_states=dict(self._agent_states),
        )

        # Find failed agent for error summary
        if not is_success:
            for name in AGENT_ORDER:
                if self._agent_states.get(name) == "error":
                    data.failed_agent = name
                    data.error_detail = self._agents[name].summary
                    break

        # Print the summary card
        self._emit_permanent("")
        summary_ansi = render_summary(data, width=self._width)
        # The summary card has multiple lines — count them
        line_count = summary_ansi.count("\n") + 1
        sys.stdout.write(summary_ansi + "\n")
        sys.stdout.flush()
        self._lines_since_header += line_count

        # Print the completion footer
        self._emit_permanent("")
        footer = render_completion_line(
            duration_seconds=elapsed,
            agent_count=sum(1 for s in self._agent_states.values() if s in ("complete", "error")),
            total_tokens=total_tokens,
            total_cost=total_cost,
            success=is_success,
            width=self._width,
        )
        sys.stdout.write(footer + "\n")
        sys.stdout.flush()
        self._lines_since_header += footer.count("\n") + 1

        # Terminal bell
        emit_bell()

    # ── Event polling ────────────────────────────────────────────────────

    async def _poll_events(self) -> bool:
        """Poll all three Redis streams for new events. Returns True if any found."""
        changed = False

        # Batch permanent lines emitted this tick so same-tick bursts are
        # revealed by _reveal_paced instead of printing in one instant.
        self._batching = True
        try:
            # ── agent_events ──
            try:
                results = await self._redis.xreadgroup(
                    groupname=GROUP_COCKPIT,
                    consumername=f"stream-1-{self._consumer_id}",
                    streams={STREAM_AGENT_EVENTS: ">"},
                    count=50,
                    block=20,
                )
                if results:
                    for _, messages in results:
                        for msg_id, raw in messages:
                            try:
                                msg = self._decode(raw)
                                self._handle_agent_event(msg)
                                await self._redis.xack(STREAM_AGENT_EVENTS, GROUP_COCKPIT, msg_id)
                                changed = True
                            except Exception:
                                # One bad message must not drop the rest of the
                                # batch. Leave it unacked (stays in the PEL for
                                # diagnosis) and continue.
                                logger.exception(
                                    "[renderer] Failed handling agent_events %s; left unacked",
                                    msg_id,
                                )
            except Exception:
                pass

            # ── agent_thinking (Dissect tokens) ──
            try:
                td_results = await self._redis.xreadgroup(
                    groupname=GROUP_COCKPIT,
                    consumername=f"stream-td-{self._consumer_id}",
                    streams={STREAM_AGENT_THINKING: ">"},
                    count=50,
                    block=20,
                )
                if td_results:
                    for _, messages in td_results:
                        for msg_id, raw in messages:
                            try:
                                msg = self._decode(raw)
                                if "text" in msg and "token" not in msg:
                                    msg["token"] = msg.pop("text")
                                self._handle_thinking_delta(msg)
                                await self._redis.xack(STREAM_AGENT_THINKING, GROUP_COCKPIT, msg_id)
                                changed = True
                            except Exception:
                                logger.exception(
                                    "[renderer] Failed handling agent_thinking %s; left unacked",
                                    msg_id,
                                )
            except Exception:
                pass

            # ── subaction_progress ──
            try:
                sa_results = await self._redis.xreadgroup(
                    groupname=GROUP_COCKPIT,
                    consumername=f"stream-sa-{self._consumer_id}",
                    streams={STREAM_SUBACTION: ">"},
                    count=50,
                    block=20,
                )
                if sa_results:
                    for _, messages in sa_results:
                        for msg_id, raw in messages:
                            try:
                                msg = self._decode(raw)
                                self._handle_subaction(msg, str(msg_id))
                                await self._redis.xack(STREAM_SUBACTION, GROUP_COCKPIT, msg_id)
                                changed = True
                            except Exception:
                                logger.exception(
                                    "[renderer] Failed handling subaction_progress %s; "
                                    "left unacked",
                                    msg_id,
                                )
            except Exception:
                pass
        finally:
            self._batching = False
            await self._reveal_paced()

        return changed

    async def _reveal_paced(self) -> None:
        """Reveal batched permanent lines with a small stagger.

        Display-only pacing of real events: the first line prints immediately,
        then up to ``_STAGGER_MAX_QUEUE`` lines total are revealed at
        ``_REVEAL_DELAY`` intervals. Any overflow is flushed immediately so a
        large burst never causes a multi-second reveal. Non-TTY output prints
        everything at once (no artificial delay when piped).
        """
        actions = self._pending_actions
        self._pending_actions = []
        if not actions:
            return
        if not sys.stdout.isatty() or len(actions) <= 1:
            for act in actions:
                act()
            return
        index = 1
        try:
            actions[0]()
            for act in actions[1:_STAGGER_MAX_QUEUE]:
                await asyncio.sleep(_REVEAL_DELAY)
                act()
                index += 1
            for act in actions[_STAGGER_MAX_QUEUE:]:
                act()
        except BaseException:
            # Never drop pending lines — flush whatever hasn't run yet, then
            # let the original error (incl. CancelledError/KeyboardInterrupt)
            # propagate so the caller's own handling still applies.
            for act in actions[index:]:
                act()
            raise

    @staticmethod
    def _decode(raw_fields: dict) -> dict[str, Any]:
        """Decode Redis stream fields (may be bytes or str)."""
        msg: dict[str, Any] = {}
        for k, v in raw_fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            try:
                msg[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                msg[key] = val
        return msg

    # ── Main loop ────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Main event loop. Poll events, render output, repeat."""
        if not self._ready:
            await self.setup()

        self._running = True
        self._mission_start = time.monotonic()

        # First paint: show the mission started before any agent events arrive
        detail = f" · {self._dataset_name}" if self._dataset_name else ""
        self._emit_permanent(
            render_subaction(f"Mission started{detail} — waiting for Scout to begin…")
        )
        last_badge_update = 0.0
        last_status_check = 0.0

        try:
            while self._running:
                await self._poll_events()
                now = time.monotonic()

                # Update active badge every ~100ms (spinner animation at the
                # spinner's native 100ms frame interval)
                if self._active_agent and now - last_badge_update >= 0.1:
                    agent = self._agents[self._active_agent]
                    badge = render_badge(
                        name=self._active_agent,
                        status="active",
                        summary=agent.summary,
                        elapsed=agent.elapsed,
                        tick=now,
                    )
                    self._rewrite_badge(badge)
                    last_badge_update = now

                # Check for mission completion using the orchestrator's final status every 1s
                if now - last_status_check >= 1.0:
                    last_status_check = now
                    try:
                        job_status = await self._redis.get(f"job:{self._mission_id}:status")
                        if job_status:
                            canonical = str(
                                job_status.decode() if isinstance(job_status, bytes) else job_status
                            )
                            if canonical in (
                                "MISSION_PASSED",
                                "MISSION_FAILED",
                                "CANCELLED",
                                "HARBOR_COMPLETED",
                            ):
                                any_error = canonical == "MISSION_FAILED"
                                if self._mission_status not in ("error", "cancelled"):
                                    self._mission_status = (
                                        "error"
                                        if any_error
                                        else (
                                            "cancelled" if canonical == "CANCELLED" else "complete"
                                        )
                                    )

                                self._resolve_remaining("skipped")

                                # Render the final summary
                                await self._render_mission_summary()
                                break
                    except Exception:
                        pass

                await asyncio.sleep(0.05)

        except KeyboardInterrupt:
            self._resolve_remaining("cancelled")
            self._mission_status = "cancelled"
            self._emit_permanent("")
            self._emit_permanent(render_subaction("Mission cancelled by user", state="error"))
        except asyncio.CancelledError:
            # The orchestrator finished the job, so the mission is complete.
            any_error = any(self._agent_states.get(a) == "error" for a in AGENT_ORDER)
            if self._mission_status not in ("error", "cancelled"):
                self._mission_status = "error" if any_error else "complete"

            self._resolve_remaining("skipped")

            # Render the final summary
            await self._render_mission_summary()
        finally:
            self._running = False

    # ── Console access (for callers that need it) ────────────────────────

    @property
    def console(self) -> Console:
        return self._console

    def print(self, text: str) -> None:
        self._console.print(text)

    def error(self, text: str) -> None:
        self._console.print(f"  [bold red]✘[/] {text}")


# ═══════════════════════════════════════════════════════════════════════════
# Convenience wrapper — matches the signature of run_unified_live
# ═══════════════════════════════════════════════════════════════════════════


async def run_stream(
    redis: aioredis.Redis,
    mission_id: str,
    problem_description: str = "",
    **kwargs: Any,
) -> None:
    """Convenience wrapper: create a StreamRenderer and run it."""
    renderer = StreamRenderer(redis, mission_id, problem_description, **kwargs)
    try:
        await renderer.run()
    except KeyboardInterrupt:
        pass

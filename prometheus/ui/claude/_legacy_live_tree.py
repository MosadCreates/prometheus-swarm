# ruff: noqa: E501 — display strings with long styled fragments
"""Live tree renderer — Claude Code-style streaming TUI for Prometheus Swarm.

Matches the exact visual style of Claude Code's teammate spinner tree:
  ├─ ● Scout: Profiling dataset…  · 0 tokens
  │  └ ● EDA complete
  ╞═ @Forge: Generating training script…  · 128 tokens
  │  └ ✔ Architecture: lightgbm
  └─ ✔ Furnace: Training complete (0 crashes)
     └ ✔ Epoch 10/10 — auc_roc: 0.8921

All visible state is driven by real Redis Stream events — no timers,
no hardcoded sequences, no fake progress.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import time
from collections import deque
from dataclasses import dataclass, field
from io import StringIO
from typing import Any

import redis.asyncio as aioredis
from rich.console import Console
from rich.style import Style
from rich.text import Text

from bus.consumer import ensure_consumer_group
from bus.events import (
    GROUP_COCKPIT,
    STREAM_AGENT_EVENTS,
    STREAM_AGENT_THINKING,
    STREAM_SUBACTION,
)
from prometheus.ui.claude.agent_colors import AGENT_COLORS

# ── Spinner frames (braille dots + sweep, bidirectional) ──
_BRAILLE_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_SPINNER_FRAMES = [*_BRAILLE_FRAMES, *_BRAILLE_FRAMES[::-1]]
_SPINNER_INTERVAL = 100  # ms per frame

# ── Tree connector characters (single-stroke, Claude Code style) ──
_TREE_PIPE = "│"
_TREE_MID = "├──"
_TREE_END = "└──"
_TREE_CONT = "│   "

# ── Symbols ──
_DOT = "●"
_CHECK = "✔"
_CROSS = "✘"
_POINTER = "▸"
_BULLET = "·"
_ELIPS = "…"
_TEARDROP = "𐄂"
_PARAM = "\u23bf"
_SEP = "─"
_WHITE_CIRCLE = "○"

# ── Colors (ANSI / RGB) ──
_COLOR_BRIGHT = "#ECECEC"
_COLOR_DIM = "#8E8E93"
_COLOR_DIM_ITALIC = Style(dim=True, italic=True)
_COLOR_SUCCESS = "#5FD75F"
_COLOR_ERROR = "#D75F5F"
_COLOR_BORDER = Style(color="#2A2A2A", dim=True)

# ── Layout constants ──
_PAD_LEFT = 3
_INDENT = " " * _PAD_LEFT

# ── Agent pipeline order ──
_AGENT_PIPELINE = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]

# ── Animation ──
_THINKING_DELAY_MS = 3000
_THINKING_GLOW_PERIOD_S = 2.0


@dataclass
class SubactionNode:
    detail: str = ""
    detail_data: dict[str, Any] | None = None
    progress: float = 0.0
    state: str = "running"


@dataclass
class AgentNode:
    name: str
    status: str = "pending"  # pending | active | done | error
    summary: str = ""
    subactions: list[SubactionNode] = field(default_factory=list)
    thinking_tokens: deque[str] = field(default_factory=lambda: deque(maxlen=120))
    token_count: int = 0
    is_last: bool = False
    seen: bool = False
    start_time: float = 0.0
    end_time: float = 0.0


def _lerp_color(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> str:
    r = int(a[0] + (b[0] - a[0]) * t)
    g = int(a[1] + (b[1] - a[1]) * t)
    b = int(a[2] + (b[2] - a[2]) * t)
    return f"rgb({r},{g},{b})"


def _sine_opacity(time_ms: float, period_s: float, delay_ms: float = 0) -> float:
    elapsed = max(0, time_ms - delay_ms) / 1000
    return (math.sin(elapsed * math.pi * 2 / period_s) + 1) / 2


class LiveTreeRenderer:
    """Consumes agent_events + thinking_delta + subaction_progress streams
    and renders a Claude Code-style live tree via rich.Live."""

    def __init__(
        self,
        redis: aioredis.Redis,
        mission_id: str,
        problem_description: str = "",
    ) -> None:
        self._redis = redis
        self._mission_id = mission_id
        self._problem = problem_description

        self._running = False
        self._agents: dict[str, AgentNode] = {
            name: AgentNode(name=name) for name in _AGENT_PIPELINE
        }
        self._agent_order: list[str] = []
        self._seen_agents: set[str] = set()
        self._tick: float = 0.0
        self._last_seq: dict[str, int] = {}
        self._mission_start = time.monotonic()
        self._summary_data: dict[str, Any] = {}

        self._console = Console(emoji=False, safe_box=True, no_color=False, color_system="auto")
        self._width = shutil.get_terminal_size().columns

    # ── public entry point ──

    async def run(self) -> None:
        await ensure_consumer_group(self._redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")

        self._running = True
        self._is_first_render = True
        self._finalized_agents: set[str] = set()
        self._printed_sub_count: dict[str, int] = {}
        self._spinner_active = False
        self._stop_requested = False
        self._last_transition_time = 0.0

        try:
            while self._running and not self._stop_requested:
                await self._poll_events()
                self._render_frame()
                self._is_first_render = False
                if self._pipeline_should_stop():
                    self._stop_requested = True
                await asyncio.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self._cleanup()
            self._console.print()
            self._console.print(self._render_final_summary())

    def _pipeline_should_stop(self) -> bool:
        """Decide if the live tree should stop rendering.

        Rules (in order):
          1. Harbor done/error → stop immediately (pipeline finished).
          2. Pre-Harbor agent error → stop immediately (critical failure).
          3. All 6 agents terminal + no active + 3s grace → stop (edge guard).
        """
        harbor = self._agents.get("Harbor")
        if harbor and harbor.seen and harbor.status in ("done", "error"):
            return True

        for name in ("Scout", "Forge", "Furnace", "Arbiter", "Dissect"):
            node = self._agents.get(name)
            if node and node.seen and node.status == "error":
                return True

        seen = [n for n in self._agents.values() if n.seen]
        if len(seen) == len(_AGENT_PIPELINE):
            has_active = any(n.status == "active" for n in seen)
            all_terminal = all(n.status in ("done", "error") for n in seen)
            if not has_active and all_terminal:
                if self._last_transition_time == 0.0:
                    self._last_transition_time = time.monotonic()
                elif time.monotonic() - self._last_transition_time > 3.0:
                    return True
            else:
                self._last_transition_time = 0.0

        return False

    def _find_active_agent(self) -> str | None:
        for name in reversed(_AGENT_PIPELINE):
            n = self._agents[name]
            if n.seen and n.status == "active":
                return name
        return None

    def _write_spinner_line(self, out, name: str) -> None:
        """Write (or overwrite) the bottom spinner line for a given agent."""
        node = self._agents[name]
        spinner = self._get_spinner_char()
        dur_str = ""
        if node.start_time > 0:
            d = time.monotonic() - node.start_time
            dur_str = f"  {_BULLET} {int(d // 60):02d}m {int(d % 60):02d}s"

        is_last = name == _AGENT_PIPELINE[-1]
        conn = _TREE_END if is_last else _TREE_MID
        color = AGENT_COLORS.get(name, "#8E8E93")
        summary = node.summary or f"Working{_ELIPS}"

        badge_ansi = self._build_text(
            Text(
                f" {name} ",
                style=Style(bgcolor=color, bold=True, color="#FFFFFF"),
            )
        )
        out.write(f"\r\x1b[K{_INDENT}{conn} {spinner}{badge_ansi}  {summary}{dur_str}")

    def _finalize_and_advance(self, out, name: str) -> None:
        """Replace the current spinner line with a finalized agent line,
        print its subactions, then advance cursor past them."""
        node = self._agents[name]
        is_last = name == _AGENT_PIPELINE[-1]
        conn = _TREE_END if is_last else _TREE_MID

        # Build the finalized line (same format as _build_agent_line but inline)
        color = AGENT_COLORS.get(name, "#8E8E93")
        if node.status == "done":
            summary_styled = Text(f"{node.summary}", style=_COLOR_SUCCESS)
        elif node.status == "error":
            summary_styled = Text(f"{node.summary}", style=_COLOR_ERROR)
        else:
            summary_styled = Text(f"{node.summary}", style=_COLOR_DIM)

        dur = ""
        if node.start_time > 0 and node.end_time > 0:
            d = node.end_time - node.start_time
            dur = f"  {_BULLET} {int(d // 60):02d}m {int(d % 60):02d}s"

        line = Text()
        line.append(f"{_INDENT}{conn} ", style=_COLOR_DIM)
        badge = Text(f" {name} ", style=Style(bgcolor=color, bold=True, color="#FFFFFF"))
        line.append(badge)
        line.append("  ", style=_COLOR_DIM)
        line.append(summary_styled)
        if dur:
            line.append(Text(dur, style=_COLOR_DIM))
        line.append("\n")

        out.write("\r\x1b[K")
        out.write(self._build_text(line))

        for sub in node.subactions:
            sub_line = self._build_subaction_line(name, sub)
            out.write(sub_line)

        self._finalized_agents.add(name)

    def _render_frame(self) -> None:
        """Single render pass — handles everything from header to spinner.
        Design:
        - Header printed once on first render.
        - Newly-done agents: replace the bottom spinner line in-place with a
          finalized line + subactions, then start the next agent's spinner.
        - Subactions for the active agent: push past spinner with \\n,
          print subactions, rewrite spinner below.
        - Steady-state: just update the spinner character via \\r.
        """
        out = self._console.file

        # ── 1. Header (once) ──
        if self._is_first_render:
            out.write(self._build_text(self._render_header()))
            out.write(
                self._build_text(
                    Text(
                        f"{_INDENT}{_SEP * min(self._width - _PAD_LEFT, 60)}\n",
                        style=_COLOR_BORDER,
                    )
                )
            )

        # ── 2. Finalize newly-done agents ──
        newly_done = [
            name
            for name in _AGENT_PIPELINE
            if self._agents[name].seen
            and self._agents[name].status in ("done", "error")
            and name not in self._finalized_agents
        ]
        if newly_done:
            for name in newly_done:
                self._finalize_and_advance(out, name)
            active = self._find_active_agent()
            if active:
                self._write_spinner_line(out, active)
                self._spinner_active = True
            else:
                self._spinner_active = False
            out.flush()
            return

        # ── 3. Print new subactions for the active agent ──
        active = self._find_active_agent()
        if active:
            node = self._agents[active]
            printed = self._printed_sub_count.get(active, 0)
            has_new_sub = printed < len(node.subactions)
            if has_new_sub:
                if self._spinner_active:
                    out.write("\n")
                for sub in node.subactions[printed:]:
                    out.write(self._build_subaction_line(active, sub))
                self._printed_sub_count[active] = len(node.subactions)
                self._write_spinner_line(out, active)
                self._spinner_active = True
                out.flush()
                return

        # ── 4. Steady-state — update spinner char ──
        if self._spinner_active and active:
            self._write_spinner_line(out, active)
        else:
            self._spinner_active = False
        out.flush()

    def _build_text(self, renderable: Text) -> str:
        """Render a Rich Text object to a plain ANSI string via a temp console."""
        buf = StringIO()
        tmp = Console(
            file=buf,
            width=self._width,
            color_system=self._console.color_system,
            force_terminal=self._console.is_terminal,
            emoji=False,
            highlight=False,
        )
        tmp.print(renderable, end="")
        return buf.getvalue()

    def _build_subaction_line(self, agent: str, sub: SubactionNode) -> str:
        """Render a subaction line indented under its agent with ⎿ param bracket."""
        line = Text()
        pipe_prefix = f"{_INDENT}{_TREE_CONT}"
        line.append(pipe_prefix, style=_COLOR_DIM)
        line.append(f"{_PARAM} ", style=_COLOR_DIM)
        if sub.state == "error":
            line.append(Text(sub.detail, style=_COLOR_ERROR))
        elif sub.state == "done":
            line.append(Text(sub.detail, style=_COLOR_DIM))
        else:
            line.append(Text(sub.detail, style=_COLOR_DIM_ITALIC))
        line.append("\n")
        return self._build_text(line)

    # ── event polling ──

    async def _poll_events(self) -> bool:
        changed = False

        # 1. Agent state events
        try:
            results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="live-tree-1",
                streams={STREAM_AGENT_EVENTS: ">"},
                count=10,
                block=100,
            )
            if results:
                for _, messages in results:
                    for msg_id, raw in messages:
                        msg = self._decode(raw)
                        self._handle_agent_event(msg)
                        await self._redis.xack(STREAM_AGENT_EVENTS, GROUP_COCKPIT, msg_id)
                        changed = True
        except Exception:
            pass

        # 2. Thinking tokens
        try:
            td_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="live-tree-td",
                streams={STREAM_AGENT_THINKING: ">"},
                count=20,
                block=50,
            )
            if td_results:
                for _, messages in td_results:
                    for msg_id, raw in messages:
                        msg = self._decode(raw)
                        if "text" in msg and "token" not in msg:
                            msg["token"] = msg.pop("text")
                        self._handle_thinking_delta(msg)
                        await self._redis.xack(STREAM_AGENT_THINKING, GROUP_COCKPIT, msg_id)
                        changed = True
        except Exception:
            pass

        # 3. Subaction progress
        try:
            sa_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="live-tree-sa",
                streams={STREAM_SUBACTION: ">"},
                count=10,
                block=50,
            )
            if sa_results:
                for _, messages in sa_results:
                    for msg_id, raw in messages:
                        msg = self._decode(raw)
                        self._handle_subaction(msg)
                        await self._redis.xack(STREAM_SUBACTION, GROUP_COCKPIT, msg_id)
                        changed = True
        except Exception:
            pass

        self._tick += 0.05

        return changed

    def _decode(self, raw_fields: dict) -> dict[str, Any]:
        msg: dict[str, Any] = {}
        for k, v in raw_fields.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            try:
                msg[key] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                msg[key] = val
        return msg

    # ── event handlers ──

    # Human-readable detail keys that should be rendered as subaction lines
    _READABLE_DETAIL_KEYS = {
        "error",
        "reason",
        "result",
        "decision",
        "metric",
        "metric_name",
        "metric_value",
        "value",
        "architecture",
        "strategy",
        "endpoint_url",
        "model_format",
        "task",
        "task_type",
        "modality",
        "confidence",
        "outcome",
        "num_rows",
        "num_columns",
        "class_imbalance",
        "evaluation_metric",
        "threshold",
        "num_samples",
        "accuracy",
        "f1",
        "precision",
        "recall",
        "auc_roc",
        "rmse",
        "mae",
        "r2",
    }

    def _format_detail_value(self, k: str, v: Any) -> str:
        if k == "error" or k == "reason":
            return f"Error: {v}"
        if k == "result":
            return f"Result: {v}"
        if k == "decision":
            return f"Decision: {v}"
        if k == "metric_value" or k == "value":
            return f"Value: {float(v):.4f}" if isinstance(v, (int, float)) else f"Value: {v}"
        if k == "metric" or k == "metric_name":
            return f"Metric: {v}"
        if k == "architecture":
            return f"Architecture: {v}"
        if k == "strategy":
            return f"Strategy: {v}"
        if k == "endpoint_url":
            return f"Endpoint: {v}"
        if k == "confidence":
            return f"Confidence: {v}"
        if k == "modality":
            return f"Modality: {v}"
        if k == "task_type":
            return f"Task: {v}"
        if k == "num_rows":
            return f"{v} rows"
        if k == "num_columns":
            return f"{v} features"
        if k == "class_imbalance":
            return (
                f"Imbalance: {float(v):.1f}:1" if isinstance(v, (int, float)) else f"Imbalance: {v}"
            )
        if k == "evaluation_metric":
            return f"Metric: {v}"
        if k == "threshold":
            return f"Threshold: {v}"
        if k == "num_samples":
            return f"Samples: {v}"
        if k in ("accuracy", "f1", "precision", "recall", "auc_roc"):
            return (
                f"{k.title()}: {float(v):.4f}"
                if isinstance(v, (int, float))
                else f"{k.title()}: {v}"
            )
        if k in ("rmse", "mae", "r2"):
            return (
                f"{k.upper()}: {float(v):.4f}"
                if isinstance(v, (int, float))
                else f"{k.upper()}: {v}"
            )
        return f"{k}: {v}"

    def _handle_agent_event(self, msg: dict[str, Any]) -> None:
        agent = str(msg.get("agent", ""))
        state = str(msg.get("state", ""))
        summary = str(msg.get("summary", ""))
        detail = msg.get("detail", {})
        mid = str(msg.get("mission_id", ""))
        seq = int(msg.get("seq", 0))

        if not agent or not state:
            return
        if mid and mid != self._mission_id:
            return
        if agent not in self._agents:
            return

        node = self._agents[agent]
        self._last_seq[agent] = seq

        if state == "thinking":
            if not node.seen:
                node.seen = True
                node.status = "active"
                node.start_time = time.monotonic()
                self._track_agent(agent)
            node.summary = summary or node.summary

        elif state == "planning":
            if not node.seen:
                node.seen = True
                node.status = "active"
                node.start_time = time.monotonic()
                self._track_agent(agent)
            node.summary = summary or node.summary

        elif state == "acting":
            if not node.seen:
                node.seen = True
                node.status = "active"
                node.start_time = time.monotonic()
                self._track_agent(agent)
            node.summary = summary or node.summary

        elif state == "verifying":
            if not node.seen:
                node.seen = True
                node.status = "active"
                node.start_time = time.monotonic()
                self._track_agent(agent)
            node.summary = f"Verifying: {summary}" if summary else node.summary

        elif state == "done":
            node.status = "done"
            node.end_time = time.monotonic()
            node.summary = summary or "Complete"
            if detail:
                for k in self._READABLE_DETAIL_KEYS:
                    v = detail.get(k)
                    if v is not None and isinstance(v, (str, int, float)):
                        node.subactions.append(
                            SubactionNode(
                                detail=self._format_detail_value(k, v),
                                detail_data=detail,
                                state="done",
                            )
                        )

            if agent == "Harbor":
                self._collect_summary(detail)
                asyncio.ensure_future(self._delayed_stop(0.8))

        elif state == "error":
            node.status = "error"
            node.end_time = time.monotonic()
            node.summary = summary or "Failed"
            for k in ("error", "reason"):
                err = detail.get(k)
                if err:
                    node.subactions.append(SubactionNode(detail=f"Error: {err}", state="error"))
                    break
            # Stop on critical errors, but not Harbor (self-test is non-fatal)
            if agent != "Harbor":
                self._running = False

    def _handle_thinking_delta(self, msg: dict[str, Any]) -> None:
        agent = str(msg.get("agent", ""))
        token = str(msg.get("token", ""))
        if agent in self._agents and token:
            node = self._agents[agent]
            node.thinking_tokens.append(token)
            node.token_count += 1

    def _handle_subaction(self, msg: dict[str, Any]) -> None:
        agent = str(msg.get("agent") or "")
        detail = str(msg.get("detail") or "")
        progress = float(msg.get("progress") or 0.0)
        state = str(msg.get("state") or "running")

        if agent in self._agents and detail:
            node = self._agents[agent]
            if node.subactions and node.subactions[-1].detail == detail:
                node.subactions[-1].progress = progress
                node.subactions[-1].state = state
            else:
                node.subactions.append(SubactionNode(detail=detail, progress=progress, state=state))

    def _track_agent(self, agent: str) -> None:
        if agent not in self._seen_agents:
            self._seen_agents.add(agent)
            self._agent_order.append(agent)

    def _collect_summary(self, detail: dict[str, Any]) -> None:
        self._summary_data = dict(detail)

    async def _delayed_stop(self, delay: float) -> None:
        await asyncio.sleep(delay)
        self._running = False

    # ── rendering helpers ──

    def _render_header(self) -> Text:
        """Build the mission header line (printed once at the top)."""
        duration = time.monotonic() - self._mission_start
        dur_str = f"{int(duration // 60):02d}:{int(duration % 60):02d}"
        header_parts = []
        header_parts.append(Text(f"{_INDENT}{_POINTER} ", style=_COLOR_BRIGHT))
        header_parts.append(Text(f"Mission {self._mission_id[:12]}{_ELIPS}  ", style=_COLOR_BRIGHT))
        header_parts.append(Text(f"[{dur_str}]", style=_COLOR_DIM))
        line = Text.assemble(*header_parts)
        line.append("\n")
        return line

    def _get_spinner_char(self) -> str:
        frame = int(self._tick * 1000 / _SPINNER_INTERVAL) % len(_SPINNER_FRAMES)
        return _SPINNER_FRAMES[frame]

    def _render_shimmer_text(self, text: str, time_ms: float) -> Text:
        """Apply glimmer effect — a shimmer highlight sweeps across the message."""
        shimmer_speed = 200  # ms per step
        msg_width = len(text)
        cycle_length = msg_width + 20
        cycle_pos = int(time_ms / shimmer_speed)
        glimmer_idx = msg_width + 10 - (cycle_pos % cycle_length)

        result = Text()
        for j, ch in enumerate(text):
            dist = abs(j - glimmer_idx)
            if dist <= 1:
                result.append(ch, style=Style(color="#FFFFFF"))
            else:
                result.append(ch, style=_COLOR_BRIGHT)
        return result

    def _cleanup(self) -> None:
        self._console.print()

    def _extract_detail_value(self, agent_name: str, key: str) -> str:
        """Extract a raw detail value from an agent's subaction events."""
        node = self._agents.get(agent_name)
        if not node:
            return ""
        for sub in node.subactions:
            data = getattr(sub, "detail_data", None)
            if data and isinstance(data, dict) and key in data:
                val = data[key]
                if val is None:
                    continue
                if isinstance(val, (int, float)):
                    if isinstance(val, float):
                        return f"{val:.4f}"
                    return str(val)
                return str(val)
        return ""

    def _render_final_summary(self) -> Text:
        result = Text()
        width = min(self._width - _PAD_LEFT, 60)
        duration = time.monotonic() - self._mission_start
        mins, secs = divmod(int(duration), 60)

        finished = all(
            n.status == "done" or n.status == "error" for n in self._agents.values() if n.seen
        )
        has_error = finished and any(n.status == "error" for n in self._agents.values())

        # Extract key info
        arch_name = self._extract_from_subactions("Forge", "architecture")
        endpoint = self._summary_data.get("endpoint_url", "")
        task_type = self._extract_from_subactions("Scout", "Task") or self._extract_detail_value(
            "Scout", "task_type"
        )
        modality = self._extract_from_subactions("Scout", "Modality") or self._extract_detail_value(
            "Scout", "modality"
        )

        rows = self._extract_detail_value("Scout", "num_rows")
        cols = self._extract_detail_value("Scout", "num_columns")

        dec = self._extract_detail_value("Arbiter", "decision")
        primary_metric = self._extract_from_subactions(
            "Arbiter", "Metric"
        ) or self._extract_detail_value("Arbiter", "metric")
        primary_val = self._extract_detail_value("Arbiter", "value")
        threshold_val = self._extract_detail_value("Arbiter", "threshold")
        num_samples_val = self._extract_detail_value("Arbiter", "num_samples")

        # All extra metrics (not the primary one)
        extra_metrics: dict[str, str] = {}
        for mkey in ("accuracy", "f1", "precision", "recall", "auc_roc", "rmse", "mae", "r2"):
            if mkey != primary_metric.lower():
                v = self._extract_detail_value("Arbiter", mkey)
                if v:
                    extra_metrics[mkey] = v

        # Dissect patches count
        dissect_node = self._agents.get("Dissect")
        dissect_count = 0
        if dissect_node:
            dissect_count = sum(
                1
                for s in dissect_node.subactions
                if "Patched" in s.detail or "Repair" in s.detail or "cascade" in s.detail
            )

        harbor_node = self._agents.get("Harbor")
        model_format = self._extract_detail_value("Harbor", "model_format") or "onnx"

        # ── Result line ──
        result.append(f"\n{_INDENT}{_SEP * width}\n", style=_COLOR_BORDER)
        if has_error:
            result.append(
                f"{_INDENT}{_CROSS}  Mission failed  ·  {mins}m {secs}s\n\n", style=_COLOR_ERROR
            )
        elif finished:
            result.append(
                f"{_INDENT}{_CHECK}  Mission complete  ·  {mins}m {secs}s\n\n", style=_COLOR_SUCCESS
            )
        else:
            result.append(
                f"{_INDENT}{_POINTER}  Mission detached  ·  {mins}m {secs}s\n\n", style=_COLOR_DIM
            )

        label_style = Style(color=_COLOR_DIM)
        value_style = Style(color=_COLOR_BRIGHT)
        border_style = Style(color=_COLOR_BORDER)

        # ── Harbor deployment card (box-drawing) ──
        if harbor_node and harbor_node.status == "done" and endpoint:
            result.append(f"{_INDENT}", style=border_style)
            badge = Text(
                f" {_CHECK} Harbor ",
                style=Style(
                    bgcolor=AGENT_COLORS.get("Harbor", "#EC4899"), bold=True, color="#FFFFFF"
                ),
            )
            result.append(badge)
            result.append(Text("\n", style=border_style))

            # Probe /health for live status
            health_status = "—"
            health_latency = "—"
            try:
                import httpx

                probe_start = time.monotonic()
                r = httpx.get(f"{endpoint}/health", timeout=3.0)
                probe_elapsed = time.monotonic() - probe_start
                health_latency = f"{probe_elapsed*1000:.0f}ms"
                health_status = "Healthy" if r.status_code == 200 else f"HTTP {r.status_code}"
            except Exception:
                health_status = "Unreachable"
                health_latency = "—"

            col1_w = 12

            def val_line(label: str, val: str) -> Text:
                t = Text()
                t.append(f"{_INDENT} ", style=border_style)
                t.append(f"{' ' * (col1_w - len(label))}{label}", style=label_style)
                t.append(" ", style=border_style)
                t.append(val, style=value_style)
                t.append("\n")
                return t

            result.append(
                val_line("Model", arch_name.title() if arch_name else primary_metric.upper())
            )
            result.append(val_line("Format", model_format))
            result.append(val_line("Endpoint", endpoint))
            result.append(val_line("Health", f"{health_status} ({health_latency})"))

            cmd = f"Invoke-RestMethod -Uri {endpoint}/predict -Method POST -Body '{{\"features\":[]}}' -ContentType 'application/json'"
            result.append(Text(f"{_INDENT} ", style=border_style))
            result.append(Text("  ", style=label_style))
            result.append(Text("Shell ", style=label_style))
            result.append(Text(cmd, style=Style(color="#5FD7FF")))
            result.append(Text("\n"))
        else:
            # ── Compact agent-per-line summary ──
            for name in _AGENT_PIPELINE:
                node = self._agents[name]
                if not node.seen:
                    continue
                color = AGENT_COLORS.get(name, "#8E8E93")
                icon = (
                    _CHECK
                    if node.status == "done"
                    else _CROSS if node.status == "error" else _TEARDROP
                )
                s = (
                    _COLOR_SUCCESS
                    if node.status == "done"
                    else _COLOR_ERROR if node.status == "error" else _COLOR_DIM
                )
                dur = (
                    f"  ·  {int(node.end_time - node.start_time)}s"
                    if node.start_time > 0 and node.end_time > 0
                    else ""
                )
                result.append(Text(f"{_INDENT}  {icon} ", style=s))
                result.append(
                    Text(f" {name} ", style=Style(bgcolor=color, bold=True, color="#FFFFFF"))
                )
                result.append(Text(f"  {node.summary}{dur}\n", style=s))

        # ── Mission Summary card ──
        result.append(f"\n{_INDENT}", style=border_style)
        badge = Text(" Summary ", style=Style(bgcolor="#2C3E50", bold=True, color="#FFFFFF"))
        result.append(badge)
        result.append(Text("\n", style=border_style))

        # Row 1: dataset info
        row1_parts = []
        if rows:
            row1_parts.append(f"{rows} rows")
        if cols:
            row1_parts.append(f"{cols} features")
        if num_samples_val:
            row1_parts.append(f"{num_samples_val} test samples")
        if row1_parts:
            result.append(Text(f"{_INDENT}  ", style=label_style))
            result.append(Text("Dataset      ", style=label_style))
            result.append(Text(", ".join(row1_parts), style=value_style))
            result.append(Text("\n"))

        # Row 2: task
        result.append(Text(f"{_INDENT}  ", style=label_style))
        result.append(Text("Task         ", style=label_style))
        task_parts = []
        if task_type:
            task_parts.append(task_type.title())
        if modality:
            task_parts.append(modality.title())
        if arch_name:
            task_parts.append(arch_name.title())
        result.append(Text(" → ".join(task_parts) if task_parts else "—", style=value_style))
        result.append(Text("\n"))

        # Row 3: evaluation
        if primary_metric or primary_val or dec:
            result.append(Text(f"{_INDENT}  ", style=label_style))
            result.append(Text("Evaluation   ", style=label_style))
            eval_parts = []
            if primary_metric and primary_val:
                eval_parts.append(f"{primary_metric.upper()} = {primary_val}")
            elif primary_val:
                eval_parts.append(f"Value = {primary_val}")
            for mk, mv in extra_metrics.items():
                eval_parts.append(f"{mk.upper()} = {mv}")
            if threshold_val:
                eval_parts.append(f"Threshold = {threshold_val}")
            if dec:
                eval_parts.append(f"→ {dec}")
            result.append(Text("  ".join(eval_parts), style=value_style))
            result.append(Text("\n"))

        # Row 4: dissect patches
        if dissect_count > 0:
            result.append(Text(f"{_INDENT}  ", style=label_style))
            result.append(Text("Auto-heal    ", style=label_style))
            result.append(
                Text(
                    f"{dissect_count} crash{'s' if dissect_count != 1 else ''} repaired by Dissect",
                    style=value_style,
                )
            )
            result.append(Text("\n"))

        # Row 5: artifacts (scan outputs/{job_id}/)
        artifacts_dir = os.path.join(os.getcwd(), "outputs", self._mission_id)
        artifact_items = []
        if os.path.isdir(artifacts_dir):
            for fname in sorted(os.listdir(artifacts_dir)):
                fpath = os.path.join(artifacts_dir, fname)
                if os.path.isfile(fpath):
                    size = os.path.getsize(fpath)
                    if size < 1024:
                        size_str = f"{size}B"
                    elif size < 1024 * 1024:
                        size_str = f"{size/1024:.0f}KB"
                    else:
                        size_str = f"{size/1024/1024:.1f}MB"
                    artifact_items.append(f"  {_WHITE_CIRCLE} {fname} ({size_str})")
        if artifact_items:
            result.append(Text(f"{_INDENT}  ", style=label_style))
            result.append(Text("Artifacts    ", style=label_style))
            result.append(
                Text("\n").join(
                    Text(f"{_INDENT}  {' ' * 12}{a}", style=value_style) for a in artifact_items
                )
            )
            result.append(Text("\n"))

        # Row 6: next steps
        result.append(Text(f"{_INDENT}  ", style=label_style))
        result.append(Text("Next steps   ", style=label_style))
        next_steps = []
        if endpoint:
            next_steps.append(f"curl {endpoint}/predict")
            next_steps.append(f"prometheus mission report {self._mission_id}")
        else:
            next_steps.append("prometheus mission logs --tail")
            next_steps.append("prometheus doctor")
        result.append(Text("  ·  ".join(next_steps), style=Style(color="#5FD7FF")))
        result.append(Text("\n"))

        result.append(f"{_INDENT}{_SEP * width}", style=_COLOR_BORDER)
        return result

    def _extract_from_subactions(self, agent_name: str, key: str) -> str:
        """Search an agent's subactions for a formatted value by key prefix.

        The subaction detail strings are formatted by _format_detail_value(),
        e.g. key="architecture" produces "Architecture: lightgbm".
        This strips the prefix and returns just the value.
        """
        node = self._agents.get(agent_name)
        if not node:
            return ""
        label = key.replace("_", " ").title()
        for sub in node.subactions:
            detail = sub.detail
            if detail.startswith(f"{label}: "):
                return detail[len(f"{label}: ") :]
            if detail.startswith(f"{label} "):
                return detail[len(f"{label} ") :]
        return ""


async def run_live_tree(
    redis: aioredis.Redis,
    mission_id: str,
    problem_description: str = "",
) -> None:
    renderer = LiveTreeRenderer(redis, mission_id, problem_description)
    try:
        await renderer.run()
    except KeyboardInterrupt:
        pass

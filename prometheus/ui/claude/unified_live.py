from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import os
import threading
import time
from typing import Any

import redis.asyncio as aioredis
from pynput import keyboard
from rich.console import Console
from rich.live import Live
from rich.text import Text

from bus.consumer import ensure_consumer_group
from bus.events import (
    GROUP_COCKPIT,
    STREAM_AGENT_EVENTS,
    STREAM_AGENT_THINKING,
    STREAM_SUBACTION,
)
from prometheus.ui.claude.agent_colors import AGENT_COLORS
from prometheus.ui.components.streaming.agent_block import AgentBlock, SubactionNode
from prometheus.ui.components.streaming.header_banner import HeaderBanner, AGENT_ORDER
from prometheus.ui.components.streaming.mission_summary import MissionSummaryCard
from prometheus.ui.components.streaming.transition_banner import render_transition
from prometheus.ui.detail_types import (
    dict_to_detail,
    ScoutDatasetDetail,
    ScoutDataQualityDetail,
    ScoutTaskDetail,
    ForgeArchitectureDetail,
    ForgeCandidatesDetail,
    ForgeRationaleDetail,
    FurnaceEpochDetail,
    ArbiterMetricsDetail,
    ArbiterDecisionDetail,
    HarborEndpointDetail,
)
from prometheus.ui.theme import Theme

logger = logging.getLogger(__name__)

_PAD_LEFT = 3
_INDENT = " " * _PAD_LEFT

# Duration to show ephemeral transition banners (seconds)
_TRANSITION_DURATION = 2.0


class UnifiedLiveRenderer:
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

        # ── Single source of truth ───────────────────────────────────────
        self._lock = threading.Lock()
        self._agent_states: dict[str, str] = {a: "pending" for a in AGENT_ORDER}
        self._mission_status: str = "starting"
        # "starting" | "running" | "complete" | "error" | "cancelled"

        self._running = False
        self._stop_requested = False
        self._tick: float = 0.0
        self._mission_start = time.monotonic()
        self._first_render_time = 0.0
        self._last_event_time = 0.0
        self._no_event_timeout_reached = False
        self._last_seq: dict[str, int] = {}
        self._seen_subactions: set[str] = set()

        # Agent blocks — owned by the renderer, mutated only on main event loop
        self._agent_blocks: dict[str, AgentBlock] = {
            name: AgentBlock(name=name) for name in AGENT_ORDER
        }
        self._last_active_agent: str | None = None

        # Ephemeral transition (shown briefly between agent handoffs)
        self._current_transition: str | None = None
        self._transition_expires: float = 0.0

        # Keyboard expand/collapse
        self._key_queue: deque[str] = deque()
        self._focused_idx: int = -1
        self._keyboard_listener: keyboard.Listener | None = None

        # Summary data
        self._summary_data: dict[str, Any] = {}
        self._mission_summary: MissionSummaryCard | None = None
        self._summary_pushed = False
        self._harbor_probed = False

        self._console = Console(emoji=False, safe_box=True, no_color=False, color_system="auto")
        try:
            self._width = os.get_terminal_size().columns
        except (OSError, AttributeError):
            self._width = 80

        self._header_banner = HeaderBanner(
            mission_id=mission_id,
            problem_description=problem_description,
            dataset_name=self._dataset_name,
            num_rows=self._num_rows,
        )
        self._ready = False

    async def setup(self) -> None:
        """Create consumer groups before job starts.

        Must be called before run(). Prevents race where events
        are published before the renderer begins consuming.
        """
        await ensure_consumer_group(self._redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")
        try:
            await ensure_consumer_group(
                self._redis, STREAM_AGENT_THINKING, GROUP_COCKPIT, start_id="$"
            )
            await ensure_consumer_group(self._redis, STREAM_SUBACTION, GROUP_COCKPIT, start_id="$")
        except Exception:
            pass
        self._ready = True

    async def run(self) -> None:
        if not self._ready:
            await self.setup()

        try:
            hb = await self._redis.get("orch:heartbeat")
            if not hb:
                self._console.print(
                    "  [bold yellow]\u26a0 Orchestrator not running. Use --block for direct execution.[/]"
                )
        except Exception:
            pass

        self._running = True
        self._mission_start = time.monotonic()
        self._first_render_time = self._mission_start
        self._last_event_time = self._mission_start
        self._no_event_timeout_reached = False
        with self._lock:
            self._mission_status = "running"

        # Start keyboard listener for expand/collapse interaction
        try:
            self._keyboard_listener = keyboard.Listener(on_release=self._on_key_release)
            self._keyboard_listener.daemon = True
            self._keyboard_listener.start()
        except Exception:
            pass

        with Live(
            self._render_frame(),
            console=self._console,
            refresh_per_second=20,
            screen=False,
        ) as live:
            self._live = live
            try:
                while self._running and not self._stop_requested:
                    changed = await self._poll_events()
                    if changed:
                        self._last_event_time = time.monotonic()
                    self._process_keys()

                    # Update pipeline status before rendering so the header
                    # shows "complete" (not stale "running") in the last frame
                    if self._pipeline_should_stop():
                        self._stop_requested = True

                    live.update(self._render_frame())

                    if not self._no_event_timeout_reached:
                        elapsed = time.monotonic() - self._first_render_time
                        since_event = time.monotonic() - self._last_event_time
                        if elapsed > 5.0 and since_event > 5.0:
                            self._no_event_timeout_reached = True

                    await asyncio.sleep(0.02)

                # One final render with the terminal state after the loop ends
                if not self._stop_requested:
                    self._resolve_remaining_agents("disabled")
                live.update(self._render_frame())
            except KeyboardInterrupt:
                with self._lock:
                    self._resolve_remaining_agents("cancelled")
                    self._mission_status = "cancelled"
            except asyncio.CancelledError:
                pass
            finally:
                self._cleanup()

    # ── State resolution ─────────────────────────────────────────────────

    def _resolve_remaining_agents(self, terminal: str) -> None:
        """Force-resolve any agent still pending or running to a terminal state.
        Called on error, cancellation, or timeout to produce a coherent final frame.
        """
        for agent in AGENT_ORDER:
            cur = self._agent_states.get(agent, "pending")
            if cur in ("pending", "running"):
                self._agent_states[agent] = terminal
                block = self._agent_blocks.get(agent)
                if block:
                    if terminal == "disabled":
                        block.summary = "not triggered"
                    elif terminal == "error":
                        block.summary = block.summary or "Cancelled"
                    block.status = terminal
                    if not block.end_time:
                        block.end_time = time.monotonic()

    def _all_agents_terminal(self) -> bool:
        terminal = {"complete", "error", "disabled"}
        return all(self._agent_states.get(a, "pending") in terminal for a in AGENT_ORDER)

    def _pipeline_should_stop(self) -> bool:
        with self._lock:
            if self._all_agents_terminal():
                # Finalize mission status based on agent outcomes
                any_error = any(self._agent_states.get(a) == "error" for a in AGENT_ORDER)
                if self._mission_status not in ("error", "cancelled"):
                    self._mission_status = "error" if any_error else "complete"
                return True
            return False

    # ── Event polling ────────────────────────────────────────────────────

    async def _poll_events(self) -> bool:
        changed = False

        try:
            results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-1",
                streams={STREAM_AGENT_EVENTS: ">"},
                count=20,
                block=20,
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

        try:
            td_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-td",
                streams={STREAM_AGENT_THINKING: ">"},
                count=50,
                block=20,
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

        try:
            sa_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-sa",
                streams={STREAM_SUBACTION: ">"},
                count=20,
                block=20,
            )
            if sa_results:
                for _, messages in sa_results:
                    for msg_id, raw in messages:
                        msg = self._decode(raw)
                        self._handle_subaction(msg, msg_id)
                        await self._redis.xack(STREAM_SUBACTION, GROUP_COCKPIT, msg_id)
                        changed = True
        except Exception:
            pass

        self._tick += 0.02
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

    # ── Agent event handler ──────────────────────────────────────────────

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
        if agent not in self._agent_blocks:
            return

        with self._lock:
            # Clear no-event timeout — we just got an event
            self._no_event_timeout_reached = False

            block = self._agent_blocks[agent]
            self._last_seq[agent] = seq

            if summary:
                block.summary = summary

            self._extract_structured_details(agent, detail)

            if state in ("thinking", "planning", "acting", "verifying"):
                block.current_pane = state

                if not block.seen:
                    block.seen = True
                    block.status = "active"
                    block.start_time = time.monotonic()

                    # Set ephemeral transition from previous active agent
                    if self._last_active_agent and self._last_active_agent != agent:
                        prev_block = self._agent_blocks[self._last_active_agent]
                        if prev_block.status not in ("done", "error"):
                            prev_block.status = "done"
                            prev_block.end_time = time.monotonic()
                            self._agent_states[self._last_active_agent] = "complete"
                        reason = summary or ""
                        self._current_transition = render_transition(
                            self._last_active_agent, agent, reason, width=self._width
                        )
                        self._transition_expires = time.monotonic() + _TRANSITION_DURATION

                    self._last_active_agent = agent

                    # Mark queued-to-running transition
                    self._agent_states[agent] = "running"
                    if self._mission_status == "starting":
                        self._mission_status = "running"

                # Route detail data to the active pane (lock released below)
                if state == "planning" and summary:
                    block.planning_items.append(summary)
                elif state == "acting" and summary:
                    block.acting_items.append(summary)
                elif state == "verifying":
                    block.verifying_status = summary or block.summary

            elif state == "done":
                block.status = "done"
                block.end_time = time.monotonic()
                block.summary = summary or "Complete"
                self._agent_states[agent] = "complete"

                if agent == self._last_active_agent:
                    self._last_active_agent = None

                if detail:
                    for k in ("endpoint_url", "model_format", "val_metric", "metric_name", "port"):
                        v = detail.get(k)
                        if v is not None:
                            block.subactions.append(
                                SubactionNode(detail=f"{k}: {v}", detail_data=detail, state="done")
                            )

                if agent == "Arbiter":
                    for k in ("metric_name", "val_metric", "threshold", "operator", "decision"):
                        v = detail.get(k)
                        if v is not None:
                            self._summary_data[k] = v
                    val = detail.get("val_metric")
                    if val is not None:
                        self._summary_data["val_metric"] = float(val)
                    m_name = detail.get("metric_name", "metric")
                    m_val = detail.get("val_metric") or detail.get("metric_value")
                    thr = detail.get("threshold")
                    op = detail.get("operator", "\u2265")
                    dec = detail.get("decision", summary or "passed")
                    # Gate: don't render PASS with null metric or threshold
                    if m_val is None or thr is None:
                        block.summary = "AWAITING EVALUATION"
                    else:
                        try:
                            block.summary = (
                                f"{dec} \u00b7 {m_name}={float(m_val):.4f} ({op} {float(thr):.4f})"
                            )
                        except (ValueError, TypeError):
                            block.summary = f"{dec} \u00b7 {m_name}={m_val} ({op} {thr})"

                if agent == "Harbor":
                    endpoint = detail.get("endpoint_url", "")
                    if endpoint:
                        dur = block._dur_str()
                        block.summary = f"Model live \u00b7 {dur}" if dur else "Model live"
                        block.details["Endpoint"] = endpoint
                        block.details["ModelFormat"] = detail.get("model_format", "onnx")
                    self._collect_summary(detail)

            elif state == "error":
                block.status = "error"
                block.end_time = time.monotonic()
                block.summary = summary or "Failed"
                self._agent_states[agent] = "error"
                self._mission_status = "error"

                if agent == self._last_active_agent:
                    self._last_active_agent = None

                for k in ("error", "reason"):
                    err = detail.get(k)
                    if err:
                        block.subactions.append(
                            SubactionNode(detail=f"Error: {err}", state="error")
                        )
                        break

        # ── Actions requiring external async calls (lock released) ──────

        if state == "done" and agent == "Harbor":
            self._build_mission_summary()
            self._push_summary_to_scrollback()
            if not self._harbor_probed:
                asyncio.create_task(self._probe_harbor_health(detail))
                self._harbor_probed = True
            asyncio.ensure_future(self._delayed_stop(0.8))

        if state == "error" and agent != "Harbor":
            self._resolve_remaining_agents("disabled")
            asyncio.ensure_future(self._delayed_stop(1.5))

    def _extract_structured_details(self, agent: str, detail: dict[str, Any]) -> None:
        block = self._agent_blocks[agent]
        if detail.get("detail_type"):
            try:
                typed = dict_to_detail(detail)
                self._apply_typed_detail(agent, typed)
                return
            except Exception:
                pass

        if agent == "Scout":
            if "num_rows" in detail:
                block.details["Rows"] = detail["num_rows"]
            if "num_columns" in detail:
                block.details["Features"] = detail["num_columns"]
            if "confidence" in detail:
                block.details["Confidence"] = f"{float(detail['confidence']):.0%}"
            if "task_type" in detail:
                block.details["Task"] = detail["task_type"].title()
            if "modality" in detail:
                block.details["Modality"] = detail["modality"].title()
        elif agent == "Forge":
            if "architecture" in detail:
                block.details["Architecture"] = detail["architecture"]
            if "candidates" in detail:
                block.details["Candidates"] = detail["candidates"]
            if "rationale" in detail:
                block.details["Rationale"] = detail["rationale"]
        elif agent == "Furnace":
            if "epoch" in detail and "total_epochs" in detail:
                # Clamp: never display epoch > total_epochs (symptom of fencepost
                # in Furnace's early-stopping counter, fixed separately)
                epoch = min(int(detail["epoch"]), int(detail["total_epochs"]))
                block.details["Epoch"] = f"{epoch}/{detail['total_epochs']}"
            if "metric_value" in detail:
                block.details["Best"] = f"{detail['metric_value']:.4f}"
        elif agent == "Arbiter":
            if "decision" in detail:
                block.details["Decision"] = detail["decision"]
            if "metric_value" in detail:
                block.details["Value"] = f"{float(detail['metric_value']):.4f}"
        elif agent == "Harbor":
            if "endpoint_url" in detail:
                block.details["Endpoint"] = detail["endpoint_url"]
            if "model_format" in detail:
                block.details["ModelFormat"] = detail["model_format"]
            if "model_name" in detail:
                block.details["Model"] = detail["model_name"]
            if "drift_enabled" in detail:
                self._summary_data["drift_enabled"] = detail["drift_enabled"]
            if "drift_psi" in detail:
                self._summary_data["drift_psi"] = detail["drift_psi"]
            if "drift_feature" in detail:
                self._summary_data["drift_feature"] = detail["drift_feature"]
            if "drift_threshold" in detail:
                self._summary_data["drift_threshold"] = detail["drift_threshold"]

    def _apply_typed_detail(self, agent: str, detail) -> None:
        block = self._agent_blocks[agent]
        if isinstance(detail, ScoutDatasetDetail):
            block.details["Rows"] = detail.num_rows
            block.details["Features"] = detail.num_columns
        elif isinstance(detail, ScoutDataQualityDetail):
            if detail.class_imbalance_ratio:
                block.details["Imbalance"] = f"{detail.class_imbalance_ratio:.1f}:1"
        elif isinstance(detail, ScoutTaskDetail):
            block.details["Task"] = detail.task_type.title()
            block.details["Confidence"] = f"{detail.confidence:.0%}"
        elif isinstance(detail, ForgeArchitectureDetail):
            block.details["Architecture"] = detail.selected
            block.details["Confidence"] = f"{detail.confidence:.0%}"
        elif isinstance(detail, ForgeCandidatesDetail):
            primary = detail.primary
            block.details["Candidates"] = ", ".join(
                [
                    primary.get("name", ""),
                    *[a.get("name", "") for a in detail.alternatives],
                ]
            )
        elif isinstance(detail, ForgeRationaleDetail):
            block.details["Rationale"] = detail.rationale
        elif isinstance(detail, FurnaceEpochDetail):
            # Clamp: never display epoch > total_epochs
            total = detail.total_epochs or 1
            epoch = min(int(detail.epoch), int(total))
            block.details["Epoch"] = f"{epoch}/{total}"
            block.details["Best"] = f"{detail.best_score:.4f}" if detail.best_score else "\u2014"
        elif isinstance(detail, ArbiterMetricsDetail):
            block.details["Primary"] = f"{detail.primary_metric}: {detail.primary_value:.4f}"
        elif isinstance(detail, ArbiterDecisionDetail):
            block.details["Decision"] = detail.decision
        elif isinstance(detail, HarborEndpointDetail):
            block.details["Endpoint"] = detail.endpoint_url
            block.details["ModelFormat"] = detail.model_format.upper()
            if detail.drift_enabled:
                self._summary_data["drift_enabled"] = detail.drift_enabled
                self._summary_data["drift_psi"] = detail.drift_psi
                self._summary_data["drift_feature"] = detail.drift_feature
                self._summary_data["drift_threshold"] = detail.drift_threshold

    def _handle_thinking_delta(self, msg: dict[str, Any]) -> None:
        agent = str(msg.get("agent", ""))
        token = str(msg.get("token", ""))
        if agent in self._agent_blocks and token:
            block = self._agent_blocks[agent]
            block.thinking_pane.append_token(token)
            block.token_count += 1

    def _handle_subaction(self, msg: dict[str, Any], msg_id: str = "") -> None:
        agent = str(msg.get("agent") or "")
        detail = str(msg.get("detail") or "")
        progress = float(msg.get("progress") or 0.0)
        state = str(msg.get("state") or "running")

        if agent not in self._agent_blocks or not detail:
            return

        # Dedup: if we've already seen this msg_id, skip
        if msg_id:
            if msg_id in self._seen_subactions:
                return
            self._seen_subactions.add(msg_id)
            if len(self._seen_subactions) > 2000:
                self._seen_subactions.clear()

        block = self._agent_blocks[agent]

        # Furnace: use progress bar instead of flat subaction lines
        if agent == "Furnace":
            self._handle_furnace_progress(block, detail, progress, state)
            return

        if block.subactions and block.subactions[-1].detail == detail:
            block.subactions[-1].progress = progress
            block.subactions[-1].state = state
        else:
            block.subactions.append(SubactionNode(detail=detail, progress=progress, state=state))

    def _handle_furnace_progress(
        self, block: AgentBlock, detail: str, progress: float, state: str
    ) -> None:
        from prometheus.ui.components.streaming.progress_bar import ProgressBar

        if "training" not in block.progress_bars:
            block.progress_bars["training"] = ProgressBar(
                value=0.0,
                label="Training",
                width=40,
                style="training",
            )
        block.progress_bars["training"].set_value(progress)
        if state == "done":
            block.progress_bars["training"].detail = "Complete"
        elif detail:
            block.progress_bars["training"].detail = detail

    def _collect_summary(self, detail: dict[str, Any]) -> None:
        self._summary_data = dict(detail)

    async def _probe_harbor_health(self, detail: dict[str, Any]) -> None:
        endpoint = detail.get("endpoint_url")
        if not endpoint:
            return
        try:
            import httpx
            import time

            async with httpx.AsyncClient(timeout=5.0) as client:
                t0 = time.monotonic()
                r = await client.get(f"{endpoint}/health")
                latency = (time.monotonic() - t0) * 1000
                if r.status_code == 200:
                    self._summary_data["health"] = "healthy"
                else:
                    self._summary_data["health"] = "degraded"
                self._summary_data["health_latency_ms"] = round(latency, 1)
        except Exception:
            self._summary_data["health"] = "unreachable"

    async def _delayed_stop(self, delay: float) -> None:
        await asyncio.sleep(delay)
        with self._lock:
            self._resolve_remaining_agents("disabled")
        self._running = False

    # ── Render frame ─────────────────────────────────────────────────────

    def _render_frame(self) -> Text:
        out = Text()
        width = self._console.width
        self._header_banner.update_width(width)

        elapsed_seconds = int(time.monotonic() - self._mission_start)

        # ── Header — always at top, driven by single source of truth ──
        header_renderable = self._header_banner.render(
            agent_states=self._agent_states.copy(),
            status=self._mission_status,
            elapsed_seconds=elapsed_seconds,
            tick=self._tick,
        )
        out.append_text(header_renderable)
        out.append("\n")

        # ── Agent blocks in sequence ─────────────────────────────────
        all_terminal = self._all_agents_terminal()
        active_agent_now = None

        for idx, agent in enumerate(AGENT_ORDER):
            block = self._agent_blocks[agent]
            state = self._agent_states.get(agent, "pending")

            if state == "complete":
                # Completed agent — show finalized badge + key details
                block._focused = idx == self._focused_idx
                rendered = block.render_finalized(width=width)
                out.append_text(rendered)

            elif state == "error":
                # Failed agent — show error badge + detail
                block._focused = idx == self._focused_idx
                rendered = block.render_finalized(width=width)
                out.append_text(rendered)

            elif state == "running":
                # Active agent — show live render
                active_agent_now = agent
                out.append_text(block.render_live(self._tick, width=width))
                out.append("\n")

                # Ephemeral transition: show if this agent just became active
                if self._current_transition and time.monotonic() < self._transition_expires:
                    out.append_text(self._current_transition)
                    out.append("\n")

                # Show queued agents after active
                active_idx = AGENT_ORDER.index(agent)
                for qa in AGENT_ORDER[active_idx + 1 :]:
                    qb = self._agent_blocks[qa]
                    if qb.seen is False:
                        out.append_text(self._render_queued(qa))
                        out.append("\n")

            elif state in ("disabled",) or (state == "pending" and all_terminal):
                # Disabled or pending-after-completion: show as "not triggered"
                out.append_text(self._render_queued(agent))
                out.append("\n")

            elif state == "pending" and not all_terminal:
                # Queued agent — show as pending
                out.append_text(self._render_queued(agent))
                out.append("\n")

        # ── Summary card (only when all agents resolved) ──────────────
        if self._mission_summary and all_terminal:
            # Only draw summary when every agent slot has resolved
            out.append("\n")
            out.append_text(self._mission_summary.render())
            out.append("\n")
            next_text = self._render_next_steps()
            if next_text:
                out.append_text(next_text)
                out.append("\n")

        # ── No-events warning (suppress when pipeline is complete) ────
        if self._no_event_timeout_reached and not active_agent_now and not all_terminal:
            warn = Text()
            warn.append("  \u26a0 ", style="bold yellow")
            warn.append("Waiting for agent events ", style="bold yellow")
            warn.append(
                f"({elapsed_seconds // 60:02d}m {elapsed_seconds % 60:02d}s)", style="bold yellow"
            )
            warn.append(" \u2014 ", style="bold yellow")
            warn.append("run directly: ", style="bold yellow")
            warn.append("prometheus mission new --block", style="bold italic yellow")
            out.append_text(warn)

        return out

    @staticmethod
    def _render_queued(agent: str) -> Text:
        t = Text()
        agent_color = AGENT_COLORS.get(agent, Theme.secondary)
        t.append("  \u25cb ", style=str(Theme.muted))
        t.append(agent, style=f"bold {agent_color}")
        t.append("  queued", style=str(Theme.muted))
        return t

    @staticmethod
    def _render_next_steps() -> Text:
        t = Text()
        t.append("  next: ", style=str(Theme.muted))
        t.append("prometheus predict --mission ...  ", style=str(Theme.body))
        t.append("\u00b7  ", style=str(Theme.muted))
        t.append("cockpit", style=str(Theme.info))
        return t

    # ── Keyboard interaction ────────────────────────────────────────────

    def _on_key_release(self, key: keyboard.Key | keyboard.KeyCode | None) -> None:
        try:
            if key == keyboard.Key.up:
                self._key_queue.append("up")
            elif key == keyboard.Key.down:
                self._key_queue.append("down")
            elif key == keyboard.Key.enter:
                self._key_queue.append("enter")
            elif hasattr(key, "char") and key.char == "e":
                self._key_queue.append("enter")
            elif key == keyboard.Key.esc:
                self._key_queue.append("esc")
        except Exception:
            pass

    def _process_keys(self) -> None:
        while self._key_queue:
            k = self._key_queue.popleft()
            if k == "up":
                self._focused_idx = max(-1, self._focused_idx - 1)
            elif k == "down":
                if self._focused_idx < 0:
                    self._focused_idx = 0
                else:
                    self._focused_idx = min(len(AGENT_ORDER) - 1, self._focused_idx + 1)
            elif k == "enter":
                if 0 <= self._focused_idx < len(AGENT_ORDER):
                    agent = AGENT_ORDER[self._focused_idx]
                    block = self._agent_blocks.get(agent)
                    if block:
                        block._expanded = not block._expanded
            elif k == "esc":
                self._focused_idx = -1
                for agent in self._agent_blocks:
                    self._agent_blocks[agent]._expanded = False

    # ── Mission summary ─────────────────────────────────────────────────

    def _build_mission_summary(self) -> None:
        if self._mission_summary is not None:
            return

        scout = self._agent_blocks.get("Scout")
        forge = self._agent_blocks.get("Forge")
        arbiter = self._agent_blocks.get("Arbiter")
        harbor = self._agent_blocks.get("Harbor")
        harbor_detail = harbor.details if harbor else {}

        # Fallback: read from Arbiter details if summary_data not populated
        if not self._summary_data.get("val_metric") and arbiter:
            if "Primary" in arbiter.details:
                self._summary_data["metric_name"] = "AUC-ROC"
                self._summary_data["val_metric"] = float(arbiter.details.get("Best", 0.0))
            elif "Value" in arbiter.details:
                self._summary_data["val_metric"] = float(arbiter.details.get("Value", 0.0))

        self._mission_summary = MissionSummaryCard(
            mission_id=self._mission_id,
            problem_description=self._problem,
            dataset_name=self._dataset_name,
            num_rows=self._num_rows,
            num_features=scout.details.get("Features", 0) if scout else 0,
            task_type=scout.details.get("Task", "classification") if scout else "classification",
            modality=scout.details.get("Modality", "tabular") if scout else "tabular",
            winner_architecture=(
                forge.details.get("Architecture", "LightGBM") if forge else "LightGBM"
            ),
            metric_name=self._summary_data.get("metric_name", "AUC-ROC"),
            metric_value=self._summary_data.get("val_metric", 0.0),
            threshold=self._summary_data.get("threshold"),
            threshold_operator=self._summary_data.get("operator", ">"),
            dissect_patches=self._count_dissect_patches(),
            dissect_categories=self._get_dissect_categories(),
            artifacts=self._scan_artifacts(),
            endpoint_url=self._summary_data.get("endpoint_url", ""),
            duration_seconds=time.monotonic() - self._mission_start,
            status=(
                "complete"
                if not any(self._agent_states.get(a) == "error" for a in AGENT_ORDER)
                else "error"
            ),
            model_name=harbor_detail.get("Model", "Model"),
            model_format=harbor_detail.get(
                "ModelFormat", self._summary_data.get("model_format", "onnx")
            ),
            health_status=self._summary_data.get("health", "unknown"),
            health_latency_ms=self._summary_data.get("health_latency_ms"),
            drift_enabled=self._summary_data.get("drift_enabled", False),
            drift_feature=self._summary_data.get("drift_feature", ""),
            drift_psi=self._summary_data.get("drift_psi", 0.0),
            drift_threshold=self._summary_data.get("drift_threshold", 0.2),
        )
        self._mission_summary.update_width(self._console.width)

    def _push_summary_to_scrollback(self) -> None:
        if self._mission_summary and not self._summary_pushed:
            self._summary_pushed = True

    def _count_dissect_patches(self) -> int:
        dissect = self._agent_blocks.get("Dissect")
        if not dissect:
            return 0
        return sum(
            1
            for s in dissect.subactions
            if "patch" in s.detail.lower() or "repair" in s.detail.lower()
        )

    def _get_dissect_categories(self) -> list[str]:
        dissect = self._agent_blocks.get("Dissect")
        if not dissect:
            return []
        cats = []
        for s in dissect.subactions:
            data = getattr(s, "detail_data", None)
            if data and isinstance(data, dict):
                cat = data.get("category") or data.get("error_taxonomy_category")
                if cat and cat not in cats:
                    cats.append(cat)
        return cats

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
                            "path": fpath,
                            "size_bytes": os.path.getsize(fpath),
                            "artifact_type": "file",
                        }
                    )
        return artifacts

    def _cleanup(self) -> None:
        if self._keyboard_listener is not None:
            try:
                self._keyboard_listener.stop()
            except Exception:
                pass
        with self._lock:
            self._resolve_remaining_agents("disabled")
        if not self._mission_summary:
            self._build_mission_summary()
        if self._mission_summary and not self._summary_pushed:
            self._console.print()
            self._console.print(self._mission_summary.render())


async def run_unified_live(
    redis: aioredis.Redis,
    mission_id: str,
    problem_description: str = "",
    **kwargs: Any,
) -> None:
    renderer = UnifiedLiveRenderer(redis, mission_id, problem_description, **kwargs)
    try:
        await renderer.run()
    except KeyboardInterrupt:
        pass


async def run_quiet(
    redis: aioredis.Redis,
    mission_id: str,
    **kwargs: Any,
) -> None:
    """Print flat [agent] key=val ... lines — no Rich, no Live."""
    from bus.consumer import ensure_consumer_group

    await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")

    done_agents: set[str] = set()

    while True:
        try:
            results = await redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="quiet-1",
                streams={STREAM_AGENT_EVENTS: ">"},
                count=20,
                block=2000,
            )
            if not results:
                continue

            for _, messages in results:
                for msg_id, raw in messages:
                    msg: dict[str, Any] = {}
                    for k, v in raw.items():
                        key = k.decode() if isinstance(k, bytes) else k
                        val = v.decode() if isinstance(v, bytes) else v
                        try:
                            msg[key] = json.loads(val)
                        except (json.JSONDecodeError, TypeError):
                            msg[key] = val

                    agent = str(msg.get("agent", "")).lower()
                    state = str(msg.get("state", ""))
                    summary = str(msg.get("summary", ""))
                    detail = msg.get("detail", {})
                    if isinstance(detail, str):
                        try:
                            detail = json.loads(detail)
                        except (json.JSONDecodeError, TypeError):
                            detail = {}

                    if not agent or not state:
                        continue

                    await redis.xack(STREAM_AGENT_EVENTS, GROUP_COCKPIT, msg_id)

                    parts: list[str] = [f"[{agent}]"]

                    if state in ("thinking", "planning", "verifying"):
                        if state == "thinking":
                            continue
                        parts.append(state)
                        if summary:
                            parts.append(summary.lower().replace(" ", "_"))
                        parts.extend(_quiet_kv(agent, state, detail))

                    elif state == "acting":
                        if agent == "furnace":
                            prog = detail if isinstance(detail, dict) else {}
                            e = prog.get("epoch", "")
                            te = prog.get("total_epochs", "")
                            fold = prog.get("fold", "")
                            tf = prog.get("total_folds", "")
                            loss = prog.get("loss", "")
                            auc = prog.get("auc", "")
                            pct = prog.get("progress", "")
                            parts.append("progress")
                            if fold and tf:
                                parts.append(f"fold={fold}/{tf}")
                            if e and te:
                                parts.append(f"epoch={e}/{te}")
                            if loss:
                                parts.append(f"loss={loss}")
                            if auc:
                                parts.append(f"auc={auc}")
                            if pct:
                                parts.append(f"progress={pct}")
                        else:
                            parts.append(summary.lower().replace(" ", "_") if summary else "acting")

                    elif state == "done":
                        if agent == "scout":
                            parts.append("spec_ready")
                            if isinstance(detail, dict):
                                parts.extend(_quiet_kv(agent, state, detail))
                        elif agent == "forge":
                            parts.append("script_ready")
                            arch = ""
                            if isinstance(detail, dict):
                                arch = detail.get("architecture") or detail.get("selected", "")
                            parts.append(f"arch={arch}" if arch else "")
                        elif agent == "furnace":
                            parts.append("complete")
                        elif agent == "dissect":
                            parts.append("repaired")
                        elif agent == "arbiter":
                            parts.append("decision")
                            if isinstance(detail, dict):
                                for k in ("decision", "val_metric", "threshold", "metric_name"):
                                    v = detail.get(k)
                                    if v is not None:
                                        parts.append(f"{k}={v}")
                        elif agent == "harbor":
                            parts.append("deployed")
                            if isinstance(detail, dict):
                                ep = detail.get("endpoint_url", "")
                                if ep:
                                    parts.append(f"endpoint={ep}")
                        done_agents.add(agent)

                    elif state == "error":
                        parts.append("error")
                        if summary:
                            parts.append(f"msg={summary}")

                    line = "  ".join(p for p in parts if p)
                    print(line)

                    if agent == "harbor" and state == "done":
                        return

        except KeyboardInterrupt:
            return
        except Exception:
            await asyncio.sleep(0.5)


def _quiet_kv(agent: str, state: str, detail: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if agent == "scout":
        for k in ("task_type", "modality", "confidence", "target"):
            v = detail.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
    elif agent == "forge":
        for k in ("architecture", "selected", "rationale", "confidence"):
            v = detail.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
    elif agent == "arbiter":
        for k in ("decision", "metric_value", "threshold", "metric_name"):
            v = detail.get(k)
            if v is not None:
                parts.append(f"{k}={v}")
    return parts

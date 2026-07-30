"""Mission Cockpit — live Textual TUI for the Prometheus Swarm.

Consumes the ``agent_events`` Redis stream as a read-only consumer group
and renders a three-panel dashboard:

  1. Header ribbon (mission slug / problem / elapsed time)
  2. Phase tracker (all six agents with live status)
  3. Active-agent pane (full event timeline for the current agent)

Reuses the same consumer-group pattern as ``trace_persister.py``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

from textual.app import App, ComposeResult

from prometheus.ui.cockpit.consumer import CockpitConsumer
from prometheus.ui.theme import Theme
from prometheus.ui.cockpit.trace_replay import TraceReplay
from prometheus.ui.cockpit.widgets import (
    AGENT_ORDER,
    ActiveAgentPane,
    CascadeAttempt,
    CockpitFooter,
    DiffViewerScreen,
    EscalationModalScreen,
    HelpScreen,
    LogScreen,
    MissionCompletionCard,
    MissionHeader,
    ModelPickerScreen,
    PhaseTracker,
    ReplayController,
)

logger = logging.getLogger(__name__)


class CockpitApp(App[None]):
    """Textual app that renders the live Mission Cockpit."""

    FONT_SIZES = {"small": "12px", "medium": "16px", "large": "20px"}

    CSS = f"""
    Screen {{
        border: blank;
    }}

    MissionHeader {{
        dock: top;
        padding: 0 1;
        background: {Theme.background};
    }}

    PhaseTracker {{
        dock: top;
        padding: 0 1 0 1;
        background: {Theme.surface};
    }}

    CascadeAttempt {{
        dock: bottom;
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: {Theme.background};
    }}

    CockpitFooter {{
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: {Theme.background};
    }}

    ReplayController {{
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: {Theme.background};
    }}

    MissionCompletionCard {{
        dock: bottom;
        height: auto;
        max-height: 6;
        padding: 0 1;
        background: {Theme.surface};
        border: solid {Theme.success};
    }}

    ActiveAgentPane {{
        padding: 1 1;
        height: 100%;
    }}
    """

    def __init__(
        self,
        redis=None,
        mission_id: str = "",
        *,
        group_override: str | None = None,
        trace_path: str | None = None,
        trace_events: list[dict] | None = None,
        problem_description: str = "",
        no_dissect: bool = False,
        no_thinking: bool = False,
        no_color: bool = False,
        start_paused: bool = True,
        speed: str = "fast",
        high_contrast: bool = False,
        font_size: str | None = None,
    ) -> None:
        super().__init__()
        self._redis = redis
        self._mission_id = mission_id
        self._group_override = group_override
        self._trace_path = trace_path
        self._trace_events = trace_events
        self._problem_description = problem_description
        self._no_dissect = no_dissect
        self._no_thinking = no_thinking
        self._no_color = no_color or os.environ.get("NO_COLOR") == "1"
        self._start_paused = start_paused
        self._speed = speed
        self._high_contrast = high_contrast
        self._font_size = font_size
        self._consumer: CockpitConsumer | None = None
        self._consumer_task: asyncio.Task[None] | None = None
        self._replay: TraceReplay | None = None
        self._replay_task: asyncio.Task[None] | None = None
        self._all_events: dict[str, list[dict[str, Any]]] = {}
        self._active_agent: str = ""
        self._header_set = False
        self._cascade_path: list[dict[str, Any]] = []
        self._patch_log_count: int = 0
        self._last_ctrl_c: float = 0.0
        self._live_thinking: dict[str, str] = {}
        self._orchestrator_ok: bool | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield MissionHeader()
        yield PhaseTracker()
        yield ActiveAgentPane()
        yield CascadeAttempt()
        yield MissionCompletionCard()
        yield CockpitFooter()
        yield ReplayController()

    async def on_mount(self) -> None:
        self._apply_accessibility_theme()
        if self._redis is not None:
            self._consumer = CockpitConsumer(
                self._redis,
                self._on_event,
                on_thinking_token=self._on_thinking_token,
                group_override=self._group_override,
            )
            self._consumer_task = asyncio.create_task(self._consumer.run())
            self.query_one(ReplayController).visible = False
            asyncio.create_task(self._check_orchestrator_heartbeat())
            logger.info("Cockpit: consumer task started")
        elif self._trace_path:
            speed = "manual" if self._start_paused else self._speed
            replay = TraceReplay(self, self._trace_path, speed=speed, preload=self._trace_events)
            self._replay = replay
            self._replay_task = asyncio.create_task(replay.run())
            self.query_one(CockpitFooter).visible = False
            logger.info("Cockpit: trace replay task started from %s", self._trace_path)
        else:
            self.query_one(ReplayController).visible = False
            self.query_one(CockpitFooter).visible = False
            logger.info("Cockpit: no Redis — idle (test / offline mode)")

    async def on_unmount(self) -> None:
        if self._consumer is not None:
            await self._consumer.stop()
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        if self._replay_task is not None:
            self._replay_task.cancel()
            try:
                await self._replay_task
            except asyncio.CancelledError:
                pass

    # ── Orchestrator heartbeat check ──────────────────────────────────────────

    async def _check_orchestrator_heartbeat(self) -> None:
        """Check orchestrator heartbeat every 10s, clear warning when detected."""
        await asyncio.sleep(5)
        for _ in range(60):
            if self._redis is None:
                self._orchestrator_ok = None
                return
            try:
                raw = await self._redis.get("orch:heartbeat")
                if raw is not None:
                    ts = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
                    age = (datetime.now(timezone.utc) - ts).total_seconds()
                    alive = age < 30
                    if alive != self._orchestrator_ok:
                        self._orchestrator_ok = alive
                        self.refresh()
                        logger.info(
                            "Cockpit: orchestrator heartbeat %s", "detected" if alive else "lost"
                        )
                else:
                    if self._orchestrator_ok is not False:
                        self._orchestrator_ok = False
                        self.refresh()
            except Exception:
                if self._orchestrator_ok is not False:
                    self._orchestrator_ok = False
                    self.refresh()
            await asyncio.sleep(10)
        logger.info("Cockpit: heartbeat monitoring stopped (5 min timeout)")

    # ── Accessibility ────────────────────────────────────────────────────────

    def _apply_accessibility_theme(self) -> None:
        overrides: list[str] = []
        if self._no_color:
            overrides.extend(
                [
                    "MissionHeader { color: #ffffff; }",
                    "PhaseTracker { color: #cccccc; }",
                    "CockpitFooter { color: #aaaaaa; }",
                    "Screen { background: #000000; }",
                    "* { color: #cccccc; }",
                ]
            )
        if self._high_contrast:
            overrides.extend(
                [
                    "Screen { background: #000000; }",
                    "MissionHeader { background: #000000; color: #ffffff; }",
                    "PhaseTracker { background: #1a1a1a; color: #ffff00; }",
                    "ActiveAgentPane { background: #000000; }",
                    "CockpitFooter { background: #000000; }",
                    "CascadeAttempt { background: #1a1a1a; }",
                    "ReplayController { background: #000000; }",
                ]
            )
        if self._font_size:
            px = self.FONT_SIZES.get(self._font_size, "16px")
            overrides.append(f"* {{ font-size: {px}; }}")
        if overrides:
            css_block = "\n".join(overrides)
            self.CSS += f"\n/* Accessibility overrides */\n{css_block}"

    # ── Event ingestion ─────────────────────────────────────────────────────

    async def inject_event(self, event: dict[str, Any]) -> None:
        """Process an agent event as if it arrived from the Redis stream.

        Public entry point for tests.  Follows the exact same code path
        as the live consumer callback.
        """
        await self._on_event(event)

    async def _on_event(self, event: dict[str, Any]) -> None:
        """Core dispatch: event → widget state updates."""
        agent = event.get("agent", "")
        state = event.get("state", "")
        mission_id = event.get("mission_id") or event.get("job_id", "")

        if not agent:
            return

        # Filter by configured mission_id
        if self._mission_id and mission_id != self._mission_id:
            return

        # --no-dissect: suppress Dissect events, show DISABLED in tracker
        if self._no_dissect and agent == "Dissect":
            self.query_one(PhaseTracker).set_state("Dissect", "disabled")
            return

        # Set header from first event — prefer mission brief problem_description
        if not self._header_set:
            self._header_set = True
            from prometheus.utils.slugs import uuid_to_slug

            display = uuid_to_slug(mission_id) if mission_id else (agent or "")
            summary = self._problem_description or event.get("summary", "Mission in progress")
            self.query_one(MissionHeader).set_mission(display, summary)

        # Store per-agent
        if agent not in self._all_events:
            self._all_events[agent] = []
        self._all_events[agent].append(event)

        # Non-thinking events clear the live thinking buffer for this agent
        if state != "thinking" and agent == self._active_agent:
            self._live_thinking.pop(agent, None)

        # Update phase tracker
        self.query_one(PhaseTracker).set_state(agent, state)

        # Propagate no_thinking to the active pane
        pane = self.query_one(ActiveAgentPane)
        pane._no_thinking = self._no_thinking
        if agent != self._active_agent:
            prev_agent = self._active_agent
            self._active_agent = agent

            # Detect handoff reason from the event payload
            handoff_reason = ""
            summary_lower = (event.get("summary") or "").lower()
            detail = event.get("detail", "")
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    detail = {}
            if isinstance(detail, dict):
                exc_type = detail.get("exception_type", detail.get("type", ""))
                exc_msg = detail.get("exception_message", detail.get("message", ""))
                epoch = detail.get("epoch", detail.get("epoch_at_crash", ""))
                if exc_type and epoch:
                    handoff_reason = f"({exc_type} at epoch {epoch})"
                elif exc_type:
                    handoff_reason = f"({exc_type})"
            if not handoff_reason:
                epoch = event.get("epoch") or event.get("epoch_at_crash") or ""
                if epoch:
                    if "crash" in summary_lower:
                        handoff_reason = f"(crashed at epoch {epoch})"
                    else:
                        handoff_reason = f"(epoch {epoch})"
            if not handoff_reason:
                if "crash" in summary_lower:
                    handoff_reason = "(crash detected)"
                elif "done" in summary_lower or "complete" in summary_lower:
                    handoff_reason = "(phase complete)"
                elif "error" in summary_lower or "fail" in summary_lower:
                    handoff_reason = "(error)"
                else:
                    handoff_reason = "(handoff)"

            if prev_agent:
                pane.add_handoff_banner(prev_agent, agent, handoff_reason)

            pane.clear()
            for ev in self._all_events[agent]:
                pane.append_event(ev)
        else:
            pane.append_event(event)

        # ── Cascade attempt tracking ──────────────────────────────────
        if agent == "Dissect":
            detail = event.get("detail", "")
            cascade_level = None
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    detail = {}
            if isinstance(detail, dict):
                cascade_level = detail.get("cascade_level")

            cascade_widget = self.query_one(CascadeAttempt)

            # Crash header (Ch.7.2) — on first crash-related event
            if state in ("error", "thinking") and event.get("summary", "").lower().startswith(
                "crash"
            ):
                exc_type = detail.get("exception_type", detail.get("type", "Error"))
                exc_msg = detail.get(
                    "exception_message", detail.get("message", event.get("summary", ""))
                )
                cascade_widget.set_crash_header(exc_type, exc_msg)

            # Classification header (Ch.7.2)
            if state == "planning" and "classif" in event.get("summary", "").lower():
                category = detail.get("category", detail.get("error_taxonomy_category", "unknown"))
                method = detail.get("method", detail.get("taxonomy_match_method", "?"))

                # Parse confidence: could be float in detail or embedded in summary
                raw_conf = detail.get("confidence", detail.get("confidence_score", 0))
                try:
                    confidence = float(raw_conf) if raw_conf else 0.0
                except (ValueError, TypeError):
                    confidence = 0.0
                cascade_widget.set_classify_header(category, method, confidence)

            if cascade_level is not None:
                outcome = detail.get("outcome", "")
                # Limit cascade panel to decision events (TRYING/HIT/MISS/REQUIRED)
                # so that post-resolution steps (applying patch, running sandbox)
                # appear only in the active-agent pane, not duplicated here.
                if outcome in ("trying", "hit", "miss", "resolved", "success", "required"):
                    cascade_attempt = {
                        "cascade_level": cascade_level,
                        "strategy": detail.get(
                            "strategy", detail.get("level_name", f"L{cascade_level}")
                        ),
                        "outcome": outcome,
                        "message": event.get("summary", detail.get("message", "")),
                    }
                    self._cascade_path.append(cascade_attempt)
                    cascade_widget = self.query_one(CascadeAttempt)
                    cascade_widget.append_attempt(cascade_attempt)

                # Count patch_log entries if escalation
                if outcome == "escalated":
                    self._patch_log_count += 1

            # ── Escalation modal ──────────────────────────────────────
            escalation_triggered = False
            escalation_reason = ""
            traceback_info = ""

            # Condition 1: explicit "escalat" in summary
            if state == "error" and "escalat" in event.get("summary", "").lower():
                escalation_triggered = True
                escalation_reason = detail.get("reason", event.get("summary", ""))

            # Condition 2: traceback/exception fields in detail (Ch.7.5 auto-detect)
            if not escalation_triggered and state == "error" and isinstance(detail, dict):
                if detail.get("exception_type") or detail.get("traceback"):
                    escalation_triggered = True
                    escalation_reason = (
                        detail.get("reason")
                        or f"{detail.get('exception_type', 'Error')}: {detail.get('exception_message', event.get('summary', ''))}"
                    )
                    tb = detail.get("traceback", "")
                    if tb:
                        tb_lines = tb.splitlines()
                        traceback_info = "\n".join(tb_lines[:8])
                        if len(tb_lines) > 8:
                            traceback_info += (
                                f"\n  [{Theme.muted}]... ({len(tb_lines) - 8} more lines)[/]"
                            )

            if escalation_triggered:
                cascade_widget = self.query_one(CascadeAttempt)
                self.push_screen(
                    EscalationModalScreen(
                        reason=escalation_reason,
                        source="Dissect",
                        diagnostic_path=f"outputs/{mission_id}/diagnostic_report.json",
                        cascade_path=list(self._cascade_path),
                        patch_log_entries=self._patch_log_count,
                        mission_id=mission_id,
                        patch_diff=cascade_widget.last_diff,
                        traceback_info=traceback_info,
                    ),
                    callback=self._on_escalation_result,
                )

        # ── Mission completion card ───────────────────────────────────
        if agent == "Harbor" and state == "done":
            data = self._build_completion_data()
            self.query_one(MissionCompletionCard).show(data)

    def _build_completion_data(self) -> dict[str, Any]:
        """Aggregate final results from all agents into a summary dict."""
        data: dict[str, Any] = {
            "slug": "",
            "elapsed_s": 0.0,
            "metric_name": "",
            "metric_value": 0.0,
            "threshold": 0.0,
            "decision": "",
            "endpoint_url": "",
            "model_format": "",
            "total_events": 0,
        }
        header = self.query_one(MissionHeader)
        data["slug"] = getattr(header, "_slug", "")
        data["elapsed_s"] = getattr(header, "_elapsed", 0.0)

        for ev in self._all_events.get("Arbiter", []):
            detail = ev.get("detail", "")
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    detail = {}
            if isinstance(detail, dict):
                data["metric_name"] = detail.get("metric_name") or detail.get("primary_metric", "")
                raw = detail.get("metric_value") or detail.get("primary_metric_value", 0.0)
                try:
                    data["metric_value"] = float(raw)
                except (ValueError, TypeError):
                    data["metric_value"] = 0.0
                try:
                    data["threshold"] = float(detail.get("threshold", 0.0))
                except (ValueError, TypeError):
                    data["threshold"] = 0.0
                data["decision"] = detail.get("decision") or ev.get("summary", "")

        for ev in self._all_events.get("Harbor", []):
            detail = ev.get("detail", "")
            if isinstance(detail, str):
                try:
                    detail = json.loads(detail)
                except (json.JSONDecodeError, TypeError):
                    detail = {}
            if isinstance(detail, dict):
                data["endpoint_url"] = (
                    detail.get("endpoint_url") or detail.get("url") or detail.get("endpoint") or ""
                )
                data["model_format"] = detail.get("model_format", "")

        total = sum(len(evs) for evs in self._all_events.values())
        data["total_events"] = total
        return data

    async def _on_thinking_token(self, msg: dict[str, Any]) -> None:
        """Accumulate streaming thinking tokens for display.

        Tokens are pushed on the ``agent_thinking`` stream by agents
        during LLM calls.  Each message contains ``agent`` and
        ``text`` (the next chunk).  We concatenate them per-agent so
        the ActiveAgentPane can render the live text dim+italic.
        """
        agent = msg.get("agent", "")
        text = msg.get("text", "")
        if not agent:
            return
        if self._no_thinking:
            return
        existing = self._live_thinking.get(agent, "")
        self._live_thinking[agent] = existing + text
        if agent == self._active_agent:
            pane = self.query_one(ActiveAgentPane)
            pane._live_thinking = self._live_thinking
            pane.refresh()

    async def _on_escalation_result(self, result: Any) -> None:
        if result is None:
            return
        if result == "abort":
            self._publish_job_failed()
            self.exit(return_code=1)
        elif result == "skip":
            pass
        elif isinstance(result, dict):
            action = result.get("action")
            if action == "retry":
                hint = result.get("hint", "")
                self._publish_resume_training(hint)
            elif action == "export":
                path = result.get("path", "")
                if path:
                    from prometheus.ui.console import console

                    console.print(f"  [green]Trace exported:[/] {path}")
            elif action == "edit":
                self._publish_resume_training("edited manually")

    def _publish_job_failed(self) -> None:
        try:
            from bus.events import JOB_FAILED, STREAM_ORCHESTRATOR_OUT
            from bus.publisher import publish

            if self._redis and self._mission_id:
                asyncio.create_task(
                    publish(
                        self._redis,
                        STREAM_ORCHESTRATOR_OUT,
                        JOB_FAILED,
                        {
                            "job_id": self._mission_id,
                            "source_agent": "Cockpit",
                            "reason": "Aborted by user from escalation screen",
                            "diagnostic_report_path": f"outputs/{self._mission_id}/diagnostic_report.json",
                        },
                    )
                )
        except Exception:
            pass

    def _publish_resume_training(self, hint: str) -> None:
        try:
            from bus.events import RESUME_TRAINING, STREAM_DISSECT_OUTPUT
            from bus.publisher import publish

            if self._redis and self._mission_id:
                asyncio.create_task(
                    publish(
                        self._redis,
                        STREAM_DISSECT_OUTPUT,
                        RESUME_TRAINING,
                        {
                            "job_id": self._mission_id,
                            "patched_script_path": "",
                            "resume_from_checkpoint": "",
                            "patch_id": "",
                            "hint": hint,
                        },
                    )
                )
        except Exception:
            pass

    # ── Replay: reset state for go-to / step-back ──────────────────

    def _reset_state(self) -> None:
        """Clear all widget state for replay repositioning.

        Called by TraceReplay before fast-injecting events 0..n.
        Equivalent to unmounting and remounting, but avoids the flash.
        """
        self._all_events.clear()
        self._active_agent = ""
        self._header_set = False
        self._cascade_path.clear()
        self._patch_log_count = 0
        self._live_thinking.clear()

        self.query_one(PhaseTracker).agent_states = {}
        self.query_one(ActiveAgentPane).clear()
        self.query_one(CascadeAttempt).clear()
        self.query_one(MissionHeader).set_mission("", "")

        # Pop escalation modal if it was pushed
        while len(self.screen_stack) > 1:
            self.pop_screen()

    # ── Replay keyboard controls (only active in trace replay mode) ─

    def action_detach(self) -> None:
        """Detach from the Cockpit — mission keeps running in the orchestrator."""
        from prometheus.ui.console import console

        console.print(
            f"  [dim]Detached from {self._mission_id or 'mission'} — reattach with: mission watch {self._mission_id or '<mission-id>'}[/]"
        )
        self.exit(return_code=0)

    def key_q(self) -> None:
        self.action_detach()

    def key_l(self) -> None:
        """Logs — scrollback event log overlay."""
        self._open_log()

    def key_ctrl_l(self) -> None:
        """Ctrl+L — open scrollback event log (same as l)."""
        self._open_log()

    def _open_log(self) -> None:
        if self._active_agent and self._active_agent in self._all_events:
            self.push_screen(
                LogScreen(
                    events=self._all_events[self._active_agent],
                    agent=self._active_agent,
                )
            )

    def key_t(self) -> None:
        """Toggle thinking stream expansion in the active pane."""
        self._toggle_thinking()

    def _toggle_thinking(self) -> None:
        pane = self.query_one(ActiveAgentPane)
        pane._show_all_thinking = not getattr(pane, "_show_all_thinking", False)
        pane.refresh()

    def key_ctrl_t(self) -> None:
        """Ctrl+T — tri-state background task cycler.

        State 0: Default clean view (PhaseTracker + Cascade hidden).
        State 1: Shows active background training jobs (PhaseTracker visible).
        State 2: Shows parallel sub-agents (PhaseTracker + Cascade visible).
        """
        self._bg_view_state = getattr(self, "_bg_view_state", -1)
        self._bg_view_state = (self._bg_view_state + 1) % 3

        tracker = self.query_one(PhaseTracker)
        cascade = self.query_one(CascadeAttempt)

        if self._bg_view_state == 0:
            tracker.display = False
            cascade.display = False
            self.query_one(CockpitFooter).display = True
            logger.debug("bg-view: clean")
        elif self._bg_view_state == 1:
            tracker.display = True
            cascade.display = False
            self.query_one(CockpitFooter).display = True
            logger.debug("bg-view: background jobs")
        else:
            tracker.display = True
            cascade.display = True
            self.query_one(CockpitFooter).display = False
            logger.debug("bg-view: sub-agents")

    def key_tab(self) -> None:
        """Switch active agent focus to next agent in order."""
        if not self._all_events:
            return
        agents = [a for a in AGENT_ORDER if a in self._all_events]
        if not agents:
            return
        try:
            idx = agents.index(self._active_agent)
            idx = (idx + 1) % len(agents)
        except ValueError:
            idx = 0
        next_agent = agents[idx]
        self._active_agent = next_agent
        pane = self.query_one(ActiveAgentPane)
        pane.clear()
        for ev in self._all_events.get(next_agent, []):
            pane.append_event(ev)
        self.query_one(PhaseTracker)._focus_agent = next_agent

    async def key_ctrl_o(self) -> None:
        """Ctrl+O — toggle between clean prompt view and full Cockpit TUI."""
        self._minimal_view = not getattr(self, "_minimal_view", False)
        is_min = self._minimal_view

        self.query_one(MissionHeader).display = not is_min
        self.query_one(PhaseTracker).display = not is_min
        self.query_one(CascadeAttempt).display = not is_min
        self.query_one(CockpitFooter).display = not is_min
        replay = self.query_one(ReplayController)
        if replay:
            replay.display = not is_min

        pane = self.query_one(ActiveAgentPane)
        if is_min:
            pane.styles.margin = (0, 0, 0, 0)
            pane.styles.height = "100%"
        else:
            pane.styles.margin = (1, 1, 0, 1)
            pane.styles.height = "100%"

    async def key_ctrl_p(self) -> None:
        """Ctrl+P — quick model / provider switcher."""
        current = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        chosen = await self.push_screen_wait(ModelPickerScreen(current_model=current))
        if chosen:
            logger.info("Switched to model: %s", chosen)
            self.refresh()

    # ── Double-Ctrl-C detach model (Ch.6.3) ──────────────────────────

    def _on_key(self, event) -> None:
        import time

        from textual.keys import Keys

        if event.key == Keys.ControlC:
            now = time.time()
            delta = now - self._last_ctrl_c
            self._last_ctrl_c = now
            if delta < 2.0 and delta > 0:
                # Double Ctrl-C within 2s → cancel prompt
                event.stop()
                self._prompt_cancel_mission()
                return
            else:
                # Single Ctrl-C → detach
                event.stop()
                self.action_detach()
                return
        super()._on_key(event)

    def _prompt_cancel_mission(self) -> None:
        """Show a confirmation prompt to cancel the mission."""
        from textual.screen import ModalScreen

        class CancelConfirmScreen(ModalScreen[bool]):
            CSS = """
            CancelConfirmScreen {
                align: center middle;
                background: #0f0f1a 85%;
            }
            #cancel-box {
                width: 50;
                height: auto;
                padding: 2 3;
                border: solid $error;
                background: #1a1a2e;
            }
            """

            def compose(self) -> ComposeResult:
                from textual.widgets import Static

                with Static(id="cancel-box"):
                    yield Static(f"\n  [{Theme.error}]\u26a0  Cancel mission?[/]")
                    yield Static(f"\n  [{Theme.secondary}]This will stop the training container[/]")
                    yield Static(f"\n  [{Theme.muted}][y] yes  [n] no  [escape] no[/]")

            def key_y(self) -> None:
                self.dismiss(True)

            def key_n(self) -> None:
                self.dismiss(False)

            def key_escape(self) -> None:
                self.dismiss(False)

        async def _ask():
            result = await self.push_screen_wait(CancelConfirmScreen())
            if result:
                self._publish_job_failed()
                self.exit(return_code=0)

        asyncio.create_task(_ask())

    def key_d(self) -> None:
        cascade = self.query_one(CascadeAttempt)
        level_diffs = cascade.level_diffs
        if level_diffs:
            self.push_screen(DiffViewerScreen(level_diffs=level_diffs))
        elif cascade.last_diff:
            self.push_screen(DiffViewerScreen(diff_text=cascade.last_diff))
        elif self._cascade_path:
            self.push_screen(
                DiffViewerScreen(
                    title="patch preview",
                    diff_text=self._cascade_path[-1].get("message", "No diff available"),
                )
            )

    def key_f(self) -> None:
        cascade = self.query_one(CascadeAttempt)
        count = len(cascade._attempts)
        self.push_screen(
            DiffViewerScreen(
                title="fingerprint history",
                diff_text=f"  Cascade attempts: {count}\n\n  (fingerprint database integration coming soon)",
            )
        )

    def key_space(self) -> None:
        if self._replay is not None:
            self._replay.toggle_pause()

    def _is_replay(self) -> bool:
        return self._replay is not None

    def key_right(self) -> None:
        if self._replay is not None:
            asyncio.create_task(self._replay.step_forward())

    def key_j(self) -> None:
        pane = self.query_one(ActiveAgentPane)
        if pane._cursor_mode:
            pane._cursor_index = min(pane._cursor_index + 1, len(pane._events) - 1)
            pane.refresh()
        elif self._replay is not None:
            asyncio.create_task(self._replay.step_forward())

    def key_left(self) -> None:
        if self._replay is not None:
            asyncio.create_task(self._replay.step_backward())

    def key_k(self) -> None:
        pane = self.query_one(ActiveAgentPane)
        if pane._cursor_mode:
            pane._cursor_index = max(pane._cursor_index - 1, 0)
            pane.refresh()
        elif self._replay is not None:
            asyncio.create_task(self._replay.step_backward())

    def key_shift_up(self) -> None:
        """Shift+↑ — enter cursor mode on the ActiveAgentPane."""
        pane = self.query_one(ActiveAgentPane)
        if not pane._events:
            return
        pane._cursor_mode = True
        pane._cursor_index = len(pane._events) - 1
        pane.refresh()

    def key_escape(self) -> None:
        """Multi-stage Esc dismissal stack:

        1. If a modal screen is pushed (LogScreen, HelpScreen, etc.),
           let it handle Esc (their own ``key_escape`` will pop them).
        2. Otherwise, collapse expanded pane content (cursor mode,
           thinking expansion).
        3. Otherwise, detach from the Cockpit (back to the shell
           prompt).
        """
        # Stage 1: modal screen is active — let it handle Esc
        if len(self.screen_stack) > 1:
            return

        pane = self.query_one(ActiveAgentPane)

        # Stage 2a: exit cursor mode
        if pane._cursor_mode:
            pane._cursor_mode = False
            pane._cursor_index = -1
            pane.refresh()
            return

        # Stage 2b: collapse thinking expansion
        if pane._show_all_thinking:
            pane._show_all_thinking = False
            pane.refresh()
            return

        # Stage 3: detach from Cockpit
        self.action_detach()

    def key_c(self) -> None:
        """c — when in cursor mode, copy the selected event text."""
        pane = self.query_one(ActiveAgentPane)
        if not pane._cursor_mode or pane._cursor_index < 0:
            return
        ev = pane._events[pane._cursor_index]
        text = json.dumps(ev, indent=2, default=str)
        from prometheus.ui.cockpit.widgets import _copy_to_clipboard

        copied = _copy_to_clipboard(text)
        if copied:
            logger.info("Copied event #%d to clipboard", pane._cursor_index)
        else:
            from prometheus.ui.console import console as _console

            _console.print(
                f"  [{Theme.info}]Event text ({len(text)} chars) — clipboard unavailable[/]"
            )

    def key_p(self) -> None:
        """p — detach (default), or in cursor mode copy primary output property."""
        pane = self.query_one(ActiveAgentPane)
        if pane._cursor_mode and pane._cursor_index >= 0:
            self._copy_primary_property(pane)
        else:
            self.action_detach()

    def _copy_primary_property(self, pane: ActiveAgentPane) -> None:
        """Extract and copy the primary property from the selected event.

        For Harbor events: copies the endpoint URL.
        For Forge events: copies the script path.
        For others: copies the summary text.
        """
        ev = pane._events[pane._cursor_index]
        agent = ev.get("agent", "")
        detail = ev.get("detail", "")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except Exception:
                detail = {}
        if isinstance(detail, dict):
            if agent == "Harbor":
                prop = (
                    detail.get("endpoint_url") or detail.get("url") or detail.get("endpoint") or ""
                )
            elif agent == "Forge":
                prop = detail.get("script_path") or detail.get("path") or ""
            else:
                prop = ev.get("summary", "")
        else:
            prop = ev.get("summary", "")
        if not prop:
            prop = ev.get("summary", "")
        from prometheus.ui.cockpit.widgets import _copy_to_clipboard

        copied = _copy_to_clipboard(str(prop))
        if copied:
            logger.info(
                "Copied primary property from event #%d: %s", pane._cursor_index, str(prop)[:80]
            )
            from prometheus.ui.console import console as _console

            _console.print(f"  [{Theme.success}]\u2714 Copied {len(str(prop))} chars[/]")
        else:
            from prometheus.ui.console import console as _console

            _console.print(
                f"  [{Theme.info}]Property ({len(str(prop))} chars) — clipboard unavailable[/]"
            )

    def key_ctrl_k(self) -> None:
        """Ctrl+k — jump to previous user prompt / planning event in cursor mode."""
        pane = self.query_one(ActiveAgentPane)
        if not pane._cursor_mode or not pane._events:
            return
        for i in range(pane._cursor_index - 1, -1, -1):
            ev = pane._events[i]
            if ev.get("state") in ("planning", "done", "complete"):
                pane._cursor_index = i
                pane.refresh()
                return

    def key_ctrl_j(self) -> None:
        """Ctrl+j — jump to next user prompt / planning event in cursor mode."""
        pane = self.query_one(ActiveAgentPane)
        if not pane._cursor_mode or not pane._events:
            return
        for i in range(pane._cursor_index + 1, len(pane._events)):
            ev = pane._events[i]
            if ev.get("state") in ("planning", "done", "complete"):
                pane._cursor_index = i
                pane.refresh()
                return

    async def key_question_mark(self) -> None:
        """? key — open the help screen."""
        self.push_screen(HelpScreen())

    async def key_g(self) -> None:
        """Go to event — prompts for number via a screen push."""
        if self._replay is None:
            return
        from prometheus.ui.cockpit.widgets import GoToEventScreen

        n = await self.push_screen_wait(GoToEventScreen(max_event=self._replay.total - 1))
        if n is not None:
            await self._replay.go_to(n)

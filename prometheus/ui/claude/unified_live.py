from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
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
from prometheus.ui.components.streaming.header_banner import HeaderBanner
from prometheus.ui.components.streaming.mission_summary import MissionSummaryCard
from prometheus.ui.components.streaming.pipeline_tracker import PipelineTracker, AGENT_ORDER
from prometheus.ui.components.streaming.transition_banner import render_transition
from prometheus.ui.detail_types import (
    dict_to_detail,
    ScoutDatasetDetail,
    ScoutDataQualityDetail,
    ScoutTaskDetail,
    ScoutConfidenceDetail,
    ForgeArchitectureDetail,
    ForgeCandidatesDetail,
    ForgeRationaleDetail,
    FurnaceEpochDetail,
    ArbiterMetricsDetail,
    ArbiterDecisionDetail,
    ArbiterLeaderboardDetail,
    HarborEndpointDetail,
)
from prometheus.ui.theme import Theme

logger = logging.getLogger(__name__)

_PAD_LEFT = 3
_INDENT = " " * _PAD_LEFT


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

        self._running = False
        self._stop_requested = False
        self._tick: float = 0.0
        self._mission_start = time.monotonic()
        self._first_render_time = 0.0
        self._last_event_time = 0.0
        self._no_event_timeout_reached = False
        self._last_seq: dict[str, int] = {}
        self._seen_subactions: set[str] = set()

        # Agent blocks
        self._agent_blocks: dict[str, AgentBlock] = {
            name: AgentBlock(name=name) for name in AGENT_ORDER
        }
        self._active_agent: str | None = None
        self._previous_agent: str | None = None
        self._scrollback: list[Text] = []

        # Summary data
        self._summary_data: dict[str, Any] = {}
        self._mission_summary: MissionSummaryCard | None = None
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
        self._pipeline_tracker = PipelineTracker()

    async def run(self) -> None:
        try:
            hb = await self._redis.get("orch:heartbeat")
            if not hb:
                self._console.print(
                    "  [bold yellow]\u26a0 Orchestrator not running. Use --block for direct execution.[/]"
                )
        except Exception:
            pass

        # Don't destroy CG — use existing cursor to avoid re-delivering past events
        await ensure_consumer_group(self._redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")
        try:
            await ensure_consumer_group(
                self._redis, STREAM_AGENT_THINKING, GROUP_COCKPIT, start_id="$"
            )
            await ensure_consumer_group(self._redis, STREAM_SUBACTION, GROUP_COCKPIT, start_id="$")
        except Exception:
            pass

        self._running = True
        self._first_render_time = time.monotonic()
        self._last_event_time = time.monotonic()
        self._no_event_timeout_reached = False

        # Print mission banner to scrollback
        self._scrollback.append(self._header_banner.render())

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
                    live.update(self._render_frame())

                    if not self._no_event_timeout_reached:
                        elapsed = time.monotonic() - self._first_render_time
                        since_event = time.monotonic() - self._last_event_time
                        if elapsed > 5.0 and since_event > 5.0:
                            self._no_event_timeout_reached = True

                    if self._pipeline_should_stop():
                        self._stop_requested = True
                    await asyncio.sleep(0.05)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                self._cleanup()

    def _all_agents_terminal(self) -> bool:
        seen = [n for n in self._agent_blocks.values() if n.seen]
        if not seen:
            return False
        return all(n.status in ("done", "error") for n in seen)

    def _pipeline_should_stop(self) -> bool:
        harbor = self._agent_blocks.get("Harbor")
        if harbor and harbor.seen and harbor.status in ("done", "error"):
            self._build_mission_summary()
            self._push_summary_to_scrollback()
            return True
        for name in ("Scout", "Forge", "Furnace", "Dissect", "Arbiter"):
            node = self._agent_blocks.get(name)
            if node and node.seen and node.status == "error":
                self._build_mission_summary()
                self._push_summary_to_scrollback()
                return True
        seen = [n for n in self._agent_blocks.values() if n.seen]
        if len(seen) == len(AGENT_ORDER):
            all_terminal = all(n.status in ("done", "error") for n in seen)
            if all_terminal:
                self._build_mission_summary()
                self._push_summary_to_scrollback()
                return True
        return False

    async def _poll_events(self) -> bool:
        changed = False

        try:
            results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-1",
                streams={STREAM_AGENT_EVENTS: ">"},
                count=20,
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

        try:
            td_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-td",
                streams={STREAM_AGENT_THINKING: ">"},
                count=50,
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

        try:
            sa_results = await self._redis.xreadgroup(
                groupname=GROUP_COCKPIT,
                consumername="unified-sa",
                streams={STREAM_SUBACTION: ">"},
                count=20,
                block=50,
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

        # Clear no-event timeout — we just got an event
        self._no_event_timeout_reached = False

        block = self._agent_blocks[agent]
        self._last_seq[agent] = seq

        state_map = {
            "thinking": "running",
            "planning": "running",
            "acting": "running",
            "verifying": "running",
            "done": "complete",
            "error": "error",
        }
        pipeline_state = state_map.get(state, "pending")
        self._pipeline_tracker.set_state(agent, pipeline_state)

        if summary:
            block.summary = summary
            self._pipeline_tracker.set_summary(agent, summary)

        self._extract_structured_details(agent, detail)

        if state in ("thinking", "planning", "acting", "verifying"):
            if not block.seen:
                block.seen = True
                block.status = "active"
                block.start_time = time.monotonic()
                self._header_banner.update_status("running", agent)

                # Transition from previous agent to new active agent
                if self._active_agent and self._active_agent != agent:
                    prev_block = self._agent_blocks[self._active_agent]
                    if prev_block.status not in ("done", "error"):
                        prev_block.status = "done"
                        prev_block.end_time = time.monotonic()
                        self._pipeline_tracker.set_state(self._active_agent, "complete")
                        self._scrollback.append(prev_block.render_finalized(width=self._width))
                    reason = summary or ""
                    self._scrollback.append(
                        render_transition(self._active_agent, agent, reason, width=self._width)
                    )
                elif self._previous_agent and self._previous_agent != agent:
                    # Previous agent already finalized via "done" path
                    reason = summary or ""
                    self._scrollback.append(
                        render_transition(self._previous_agent, agent, reason, width=self._width)
                    )

                self._active_agent = agent

            if state == "verifying":
                block.summary = f"Verifying: {summary}" if summary else block.summary

        elif state == "done":
            block.status = "done"
            block.end_time = time.monotonic()
            block.summary = summary or "Complete"
            self._pipeline_tracker.set_state(agent, "complete")

            if agent == self._active_agent:
                self._scrollback.append(block.render_finalized(width=self._width))
                self._previous_agent = agent
                self._active_agent = None

            if detail:
                for k in ("endpoint_url", "model_format", "val_metric", "metric_name", "port"):
                    v = detail.get(k)
                    if v is not None:
                        block.subactions.append(
                            SubactionNode(detail=f"{k}: {v}", detail_data=detail, state="done")
                        )

            if agent == "Harbor":
                self._collect_summary(detail)
                if not self._harbor_probed:
                    asyncio.create_task(self._probe_harbor_health(detail))
                    self._harbor_probed = True
                asyncio.ensure_future(self._delayed_stop(0.8))

        elif state == "error":
            block.status = "error"
            block.end_time = time.monotonic()
            block.summary = summary or "Failed"
            self._pipeline_tracker.set_state(agent, "error")

            if agent == self._active_agent:
                self._scrollback.append(block.render_finalized(width=self._width))
                self._active_agent = None

            for k in ("error", "reason"):
                err = detail.get(k)
                if err:
                    block.subactions.append(SubactionNode(detail=f"Error: {err}", state="error"))
                    break
            if agent != "Harbor":
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
                block.details["Epoch"] = f"{detail['epoch']}/{detail['total_epochs']}"
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
            block.details["Epoch"] = f"{detail.epoch}/{detail.total_epochs or '?'}"
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
        self._running = False

    def _render_frame(self) -> Text:
        out = Text()
        width = self._console.width

        # Scrollback (finalized blocks + transition banners)
        for item in self._scrollback:
            out.append_text(item)
            out.append("\n")

        # Live zone
        if self._active_agent:
            block = self._agent_blocks[self._active_agent]
            out.append_text(block.render_live(self._tick, width=width))

        # No-events warning (suppress when pipeline is complete)
        pipeline_done = self._mission_summary is not None or self._all_agents_terminal()
        if self._no_event_timeout_reached and not self._active_agent and not pipeline_done:
            warn = Text()
            elapsed = time.monotonic() - self._first_render_time
            warn.append("\n")
            warn.append("  \u26a0 ", style="bold yellow")
            warn.append("Waiting for agent events ", style="bold yellow")
            warn.append(
                f"({int(elapsed // 60):02d}m {int(elapsed % 60):02d}s)", style="bold yellow"
            )
            warn.append(" \u2014 ", style="bold yellow")
            warn.append("run directly: ", style="bold yellow")
            warn.append("prometheus mission new --block", style="bold italic yellow")
            out.append_text(warn)

        # Pipeline ribbon at bottom
        if self._pipeline_tracker:
            out.append("\n")
            out.append_text(self._pipeline_tracker.render(self._tick))

        return out

    def _build_mission_summary(self) -> None:
        if self._mission_summary is not None:
            return

        scout = self._agent_blocks.get("Scout")
        forge = self._agent_blocks.get("Forge")
        arbiter = self._agent_blocks.get("Arbiter")

        harbor = self._agent_blocks.get("Harbor")
        harbor_detail = harbor.details if harbor else {}

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
                if not any(n.status == "error" for n in self._agent_blocks.values() if n.seen)
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
        if self._mission_summary:
            self._scrollback.append(self._mission_summary.render())

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
        if not self._mission_summary:
            self._build_mission_summary()
        if self._mission_summary:
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

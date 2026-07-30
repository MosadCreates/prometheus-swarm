"""
Orchestrator runtime — the main event loop that manages all agents.

Launches agents in response to events on Redis Streams.
Manages the pipeline: Scout -> Forge -> Furnace <-> Dissect -> Arbiter -> Harbor.
Handles ESCALATE -> JOB_FAILED and EVALUATION_RETRY -> Forge loop.

ARCHITECTURE NOTE:
runtime.py is the production event-driven orchestrator.
For sequential job execution (benchmarks, scripts), use orchestrator/job_runner.py.
Both use the same agent implementations. runtime.py drives them via Redis events;
job_runner.py drives them via direct async calls.
Do not add sequential execution logic to runtime.py.
Do not add event-driven logic to job_runner.py.
"""

import asyncio
import json
import logging
import os
from runtime.paths import get_job_paths
import sys

# Ensure project root is on sys.path so agent modules can be imported
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from datetime import datetime, timezone

from dotenv import load_dotenv
import redis.asyncio as aioredis

from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from agents.arbiter.agent import ArbiterAgent
from agents.harbor.agent import HarborAgent
from agents.scout.agent import ScoutAgent
from contracts.state import MissionState, transition_and_save, canonical_phase
from memory.redis_client import RedisClient
from orchestrator.mission_report import generate_mission_report
from evaluation import config as eval_config
from evaluation.perf_logger import record_stage
from bus.agent_events import emit_agent_event
from bus.events import (
    MISSION_BRIEF_READY,
    CRASH_EVENT,
    EVALUATION_PASS,
    EVALUATION_RETRY,
    ESCALATE,
    RESUME_TRAINING,
    JOB_FAILED,
    ENDPOINT_LIVE,
    DRIFT_ALERT,
    PLAN_CREATED,
    PLAN_COMPLETED,
    PLAN_FAILED,
    STREAM_SCOUT_OUTPUT,
    STREAM_FORGE_OUTPUT,
    STREAM_FURNACE_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_FURNACE_FEED,
    STREAM_DISSECT_OUTPUT,
    STREAM_ARBITER_OUTPUT,
    STREAM_HARBOR_OUTPUT,
    STREAM_ORCHESTRATOR_OUT,
    STREAM_PLANNER_OUTPUT,
    GROUP_ORCHESTRATOR,
    GROUP_FORGE,
    GROUP_FURNACE,
    GROUP_DISSECT,
    GROUP_ARBITER,
    GROUP_HARBOR,
    GROUP_SCOUT,
    GROUP_FRONTEND,
    STREAM_AGENT_EVENTS,
    GROUP_COCKPIT,
)

load_dotenv()
logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))


class OrchestratorRuntime:
    """Main orchestrator event loop."""

    def __init__(self):
        self.redis: aioredis.Redis | None = None
        self._running = False
        self.health_monitor = None

    async def initialize(self) -> None:
        """Initialize Redis connection and ensure all consumer groups exist."""
        self.redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
        )
        await self.redis.ping()
        logger.info("Orchestrator connected to Redis")

        await self._ensure_consumer_groups()
        await self._register_all_tools()

        # Write heartbeat every 5s so frontend can detect orchestrator is alive
        asyncio.create_task(self._heartbeat_loop())

        # Start metrics server
        from shared.metrics import start_metrics_server

        start_metrics_server()

        # Start health monitor
        from shared.health_monitor import HealthMonitor

        self.health_monitor = HealthMonitor(redis_client=self.redis)
        await self.health_monitor.start()

    def _make_redis_client(self) -> RedisClient:
        rc = RedisClient()
        rc._client = self.redis
        return rc

    async def _ensure_consumer_groups(self) -> None:
        """Create all required consumer groups if they don't exist."""
        streams_groups = {
            STREAM_FURNACE_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_ARBITER],
            STREAM_FURNACE_CRASH: [GROUP_ORCHESTRATOR, GROUP_DISSECT],
            STREAM_FURNACE_FEED: [GROUP_ORCHESTRATOR, GROUP_FRONTEND],
            STREAM_DISSECT_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_FURNACE],
            STREAM_ARBITER_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_HARBOR],
            STREAM_HARBOR_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_SCOUT],
            STREAM_SCOUT_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_FORGE],
            STREAM_FORGE_OUTPUT: [GROUP_ORCHESTRATOR, GROUP_FURNACE],
            STREAM_PLANNER_OUTPUT: [GROUP_ORCHESTRATOR],
            STREAM_AGENT_EVENTS: [GROUP_ORCHESTRATOR, GROUP_COCKPIT],
        }

        for stream, groups in streams_groups.items():
            for group in groups:
                try:
                    await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
                except Exception:
                    pass

        logger.info("Consumer groups ensured")

    async def _register_all_tools(self) -> None:
        """Register all agent tool docstrings in tool_memory ChromaDB collection."""
        try:
            from memory.collections.tool_memory import register_agent_tools

            agents = [
                ("Scout", "agents.scout.tools"),
                ("Forge", "agents.forge.tools"),
                ("Furnace", "agents.furnace.tools"),
                ("Dissect", "agents.dissect.tools"),
                ("Arbiter", "agents.arbiter.tools"),
                ("Harbor", "agents.harbor.tools"),
            ]
            total = 0
            for name, module_path in agents:
                try:
                    total += register_agent_tools(name, module_path)
                except Exception as e:
                    logger.warning(f"Tool registration failed for {name}: {e}")
            logger.info(f"Registered {total} tool docstrings across {len(agents)} agents")
        except Exception as e:
            logger.warning(f"Tool memory registration skipped: {e}")

    async def run(self) -> None:
        """Main event loop. Listens on all orchestrator streams in parallel."""
        self._running = True
        logger.info("Orchestrator runtime started")

        consumers = [
            self._consume_scout(),
            self._consume_forge(),
            self._consume_furnace(),
            self._consume_furnace_crash(),
            self._consume_dissect(),
            self._consume_arbiter(),
            self._consume_harbor(),
        ]

        await asyncio.gather(*consumers)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                await self.redis.set("orch:heartbeat", datetime.now(timezone.utc).isoformat())
                await asyncio.sleep(5)
            except Exception:
                pass

    async def stop(self) -> None:
        self._running = False
        if self.health_monitor:
            await self.health_monitor.stop()
        if self.redis:
            try:
                await self.redis.aclose()
            except RuntimeError:
                pass  # Event loop already closed
        logger.info("Orchestrator stopping...")

    # ------------------------------------------------------------------
    # Consumer loops
    # ------------------------------------------------------------------

    async def _consume_scout(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-scout",
                    {STREAM_SCOUT_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            await self._on_mission_brief_ready(data)
                            await self.redis.xack(
                                STREAM_SCOUT_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Scout consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_forge(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-forge",
                    {STREAM_FORGE_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            await self._on_training_script_ready(data)
                            await self.redis.xack(
                                STREAM_FORGE_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Forge consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_furnace(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-furnace",
                    {STREAM_FURNACE_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            await self._on_training_complete(data)
                            await self.redis.xack(
                                STREAM_FURNACE_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Furnace consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_furnace_crash(self) -> None:
        """Consume CRASH_EVENT from furnace_crash stream and launch Dissect."""
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-furnace-crash",
                    {STREAM_FURNACE_CRASH: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            event_type = data.get("event_type", "")
                            if event_type == CRASH_EVENT:
                                await self._on_crash_event(data)
                            await self.redis.xack(
                                STREAM_FURNACE_CRASH,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Furnace crash consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_dissect(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-dissect",
                    {STREAM_DISSECT_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            event_type = data.get("event_type", "")
                            if event_type == RESUME_TRAINING:
                                job_id = data.get("job_id", "?")
                                logger.info(
                                    f"[job={job_id}] Dissect RESUME_TRAINING. Transitioning state back to FURNACE_RUNNING."
                                )
                                # Two-step transition: DISSECT_RUNNING → DISSECT_COMPLETED → FURNACE_RUNNING
                                current = await MissionState.load_from_redis(self.redis, job_id)
                                if current and current.phase == "DISSECT_RUNNING":
                                    await transition_and_save(
                                        self.redis,
                                        job_id,
                                        "DISSECT_COMPLETED",
                                        agent="Dissect",
                                        message="Dissect patch successful, ready to resume",
                                    )
                                await transition_and_save(
                                    self.redis,
                                    job_id,
                                    "FURNACE_RUNNING",
                                    agent="Furnace",
                                    message="Resuming training after Dissect patch",
                                )
                            elif event_type == ESCALATE:
                                await self._on_escalate(data)
                            await self.redis.xack(
                                STREAM_DISSECT_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Dissect consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_arbiter(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-arbiter",
                    {STREAM_ARBITER_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            event_type = data.get("event_type", "")
                            if event_type in (
                                EVALUATION_PASS,
                                EVALUATION_RETRY,
                                ESCALATE,
                            ):
                                await self._on_arbiter_decision(data)
                            await self.redis.xack(
                                STREAM_ARBITER_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Arbiter consumer error: {e}")
                await asyncio.sleep(1)

    async def _consume_harbor(self) -> None:
        while self._running:
            try:
                results = await self.redis.xreadgroup(
                    GROUP_ORCHESTRATOR,
                    "orchestrator-harbor",
                    {STREAM_HARBOR_OUTPUT: ">"},
                    count=1,
                    block=2000,
                )
                if results:
                    for _stream, messages in results:
                        for msg_id, data in messages:
                            event_type = data.get("event_type", "")
                            if event_type == ENDPOINT_LIVE:
                                await self._on_endpoint_live(data)
                            elif event_type == DRIFT_ALERT:
                                await self._on_drift_alert(data)
                            elif event_type == JOB_FAILED:
                                await self._handle_escalate(
                                    data.get("job_id", "?"),
                                    data.get("source_agent", "Harbor"),
                                    data.get("reason", "Deployment failed"),
                                )
                            await self.redis.xack(
                                STREAM_HARBOR_OUTPUT,
                                GROUP_ORCHESTRATOR,
                                msg_id,
                            )
            except Exception as e:
                logger.error(f"Harbor consumer error: {e}")
                await asyncio.sleep(1)

    # ------------------------------------------------------------------
    # Event handlers — launch real agents
    # ------------------------------------------------------------------

    async def _run_scout_if_needed(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        brief_key = f"job:{job_id}:mission_brief"
        exists = await self.redis.exists(brief_key)
        if exists:
            return
        logger.info(f"[job={job_id}] No mission brief found. Running Scout first.")
        await transition_and_save(self.redis, job_id, "SCOUT_RUNNING", agent="Scout")
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "scout", "start")
        scout = ScoutAgent(job_id=job_id)
        scout.redis = self._make_redis_client()
        scout.job_data = {
            "problem_description": data.get("problem_description", ""),
            "file_path": data.get("dataset_path", ""),
            "target_column": data.get("target_column"),
            "constraints": None,
        }
        try:
            await scout.run()
            await transition_and_save(
                self.redis,
                job_id,
                "SCOUT_COMPLETED",
                agent="Scout",
                message="Scout completed",
            )
        except Exception as e:
            logger.error(f"[job={job_id}] Scout failed: {e}")
            await self._handle_escalate(job_id, "Scout", f"Scout execution failed: {e}")
            raise

    async def _compile_and_store_plan(self, job_id: str) -> None:
        """Compile ExecutionPlan from MissionSpecification and store in Redis."""
        if eval_config.DISABLE_PLANNER:
            logger.info(f"[job={job_id}] Planner disabled — skipping plan compilation")
            if eval_config.PROFILE_MODE:
                record_stage(job_id, "planner", "skipped")
            return

        if eval_config.PROFILE_MODE:
            record_stage(job_id, "planner", "start")

        spec_key = f"job:{job_id}:mission_spec"
        spec = await self.redis.get(spec_key)
        if not spec:
            logger.warning(f"[job={job_id}] No MissionSpecification found for plan compilation")
            return
        try:
            spec_dict = json.loads(spec) if isinstance(spec, str) else spec
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"[job={job_id}] Could not parse MissionSpecification for planning")
            return

        from prometheus.planner.compiler import compile_plan

        # Load historical hints from past execution outcomes
        hints = await self._load_planning_hints(spec_dict, job_id)

        plan = compile_plan(spec_dict, job_id, hints=hints)
        plan_key = f"job:{job_id}:execution_plan"
        await self.redis.set(plan_key, plan.model_dump_json())
        await self._init_plan_state(plan)
        from bus.publisher import publish

        from contracts.events import PlanCreatedEvent

        await publish(
            self.redis,
            STREAM_PLANNER_OUTPUT,
            PLAN_CREATED,
            PlanCreatedEvent(
                job_id=job_id,
                plan_id=plan.plan_id,
                estimated_total_minutes=plan.estimated_total_minutes,
                confidence_score=plan.confidence.score,
                confidence_assessment=plan.confidence.assessment,
            ),
        )
        logger.info(
            f"[job={job_id}] Plan {plan.plan_id} created | "
            f"confidence={plan.confidence.score:.2f} ({plan.confidence.assessment}) | "
            f"est={plan.estimated_total_minutes}min | "
            f"nodes={len(plan.nodes)}"
        )

        if eval_config.PROFILE_MODE:
            record_stage(job_id, "planner", "end")

    async def _load_planning_hints(self, spec_dict: dict, job_id: str):
        """Load PlanningHints from historical execution outcomes."""
        try:
            from learning.planner_feedback import compute_planning_hints

            hints = await compute_planning_hints(spec_dict, self.redis, job_id)
            return hints
        except Exception as e:
            logger.debug(f"[job={job_id}] PlanningHints unavailable: {e}")
            return None

    async def _record_execution_outcome(
        self, job_id: str, deployment_success: bool | None = None
    ) -> None:
        """Record ExecutionOutcome after job completion or escalation."""
        try:
            from learning.execution_outcome import record_outcome, get_outcome

            outcome = await get_outcome(self.redis, job_id)
            if outcome:
                # Already recorded — update deployment flag
                return

            brief = None
            try:
                rc = self._make_redis_client()
                brief = await rc.get_json(f"job:{job_id}:mission_brief")
            except Exception:
                pass

            arch = brief.get("recommended_architecture_family", "unknown") if brief else "unknown"
            modality = brief.get("modality", "tabular") if brief else "tabular"
            task_type = brief.get("task_type", "classification") if brief else "classification"
            num_rows = brief.get("dataset", {}).get("num_rows", 0) if brief else 0
            num_cols = brief.get("dataset", {}).get("num_columns", 0) if brief else 0

            retry_count = 0
            try:
                rc2 = self._make_redis_client()
                retry_raw = await rc2._client.get(f"job:{job_id}:retry_count")
                retry_count = int(retry_raw) if retry_raw else 0
            except Exception:
                pass

            duration_seconds = 0.0
            try:
                started_raw = await self.redis.get(f"job:{job_id}:training_started_at")
                if started_raw:
                    started = float(started_raw) if isinstance(started_raw, str) else started_raw
                    duration_seconds = datetime.now(timezone.utc).timestamp() - started
            except Exception:
                pass

            crash_count = 0
            crashes_recovered = 0
            try:
                crash_raw = await self.redis.get(f"job:{job_id}:crash_count")
                crash_count = int(crash_raw) if crash_raw else 0
                recovered_raw = await self.redis.get(f"job:{job_id}:crashes_recovered")
                crashes_recovered = int(recovered_raw) if recovered_raw else 0
            except Exception:
                pass

            outcome_label = "pass" if deployment_success else "escalate"

            await record_outcome(
                redis=self.redis,
                job_id=job_id,
                architecture=arch,
                modality=modality,
                task_type=task_type,
                duration_seconds=duration_seconds,
                retries=retry_count,
                crashes=crash_count,
                crashes_recovered=crashes_recovered,
                deployment_success=deployment_success,
                outcome_label=outcome_label,
                num_rows=num_rows,
                num_columns=num_cols,
            )
        except Exception as e:
            logger.warning(f"[job={job_id}] Outcome recording failed: {e}")

    async def _update_plan_state(self, job_id: str, task_id: str, status: str) -> None:
        """Update plan task state without triggering dispatch (for observability)."""
        state_key = f"job:{job_id}:plan_state"
        raw = await self.redis.get(state_key)
        if not raw:
            return
        try:
            state = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return
        state[task_id] = status
        await self.redis.set(state_key, json.dumps(state))

    async def _init_plan_state(self, plan) -> None:
        """Initialize plan task states in Redis."""
        state: dict[str, str] = {}
        for node_id in plan.nodes:
            state[node_id] = "pending"
        state["__plan_complete__"] = "pending"
        state["__plan_failed__"] = "pending"
        await self.redis.set(f"job:{plan.job_id}:plan_state", json.dumps(state))

    async def _mark_task_completed(
        self, job_id: str, task_id: str, condition: str | None = None
    ) -> None:
        """Mark a task as completed in plan state, then dispatch next ready tasks."""
        state_key = f"job:{job_id}:plan_state"
        raw = await self.redis.get(state_key)
        if not raw:
            return
        try:
            state = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return

        state[task_id] = "completed"
        await self.redis.set(state_key, json.dumps(state))

        # Dispatch next tasks from the plan
        await self._dispatch_from_plan(job_id, state, task_id, condition)

    async def _dispatch_from_plan(
        self, job_id: str, state: dict[str, str], completed_task: str, condition: str | None = None
    ) -> None:
        """Check the ExecutionPlan and launch any tasks whose dependencies are met."""
        plan_key = f"job:{job_id}:execution_plan"
        raw = await self.redis.get(plan_key)
        if not raw:
            return
        try:
            plan_dict = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            return

        nodes = plan_dict.get("nodes", {})
        edges = plan_dict.get("edges", [])

        # Find outgoing edges from the completed task that match the condition
        for edge in edges:
            if edge.get("from_node") != completed_task:
                continue
            edge_condition = edge.get("condition")
            if edge_condition and edge_condition != condition:
                continue

            next_node_id = edge.get("to_node", "")
            if next_node_id in ("__plan_complete__", "__plan_failed__"):
                await self._handle_plan_terminal(job_id, next_node_id)
                continue

            # Check if next node's dependencies are all met
            next_node = nodes.get(next_node_id)
            if not next_node:
                continue
            deps = next_node.get("depends_on", [])
            all_deps_met = all(state.get(d, "pending") == "completed" for d in deps)

            if all_deps_met and state.get(next_node_id, "pending") == "pending":
                state[next_node_id] = "ready"
                await self.redis.set(f"job:{job_id}:plan_state", json.dumps(state))
                await self._launch_agent_for_task(job_id, next_node_id)

    async def _handle_plan_terminal(self, job_id: str, terminal: str) -> None:
        """Handle plan terminal node (__plan_complete__ or __plan_failed__)."""
        from bus.publisher import publish

        if terminal == "__plan_complete__":
            from contracts.events import PlanCompletedEvent

            await publish(
                self.redis,
                STREAM_PLANNER_OUTPUT,
                PLAN_COMPLETED,
                PlanCompletedEvent(job_id=job_id),
            )
            logger.info(f"[job={job_id}] Plan completed successfully")
        elif terminal == "__plan_failed__":
            from contracts.events import PlanFailedEvent

            await publish(
                self.redis,
                STREAM_PLANNER_OUTPUT,
                PLAN_FAILED,
                PlanFailedEvent(job_id=job_id),
            )
            logger.info(f"[job={job_id}] Plan failed")

    async def _launch_agent_for_task(self, job_id: str, task_id: str) -> None:
        """Launch the appropriate agent for a task based on its id."""
        logger.info(f"[job={job_id}] Dispatching task: {task_id}")
        if task_id in ("forge_generate", "forge_retry"):
            try:
                forge = ForgeAgent(job_id=job_id)
                forge.redis = self._make_redis_client()
                await forge.run()
            except Exception as e:
                logger.error(f"[job={job_id}] Forge ({task_id}) failed: {e}")
                await self._handle_escalate(job_id, "Forge", str(e))

    async def _on_mission_brief_ready(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "scout", "end")
        await self._run_scout_if_needed(data)

        # Guard against re-entry: if Forge is already running or past, skip
        current = await MissionState.load_from_redis(self.redis, job_id)
        if current and current.phase not in ("SCOUT_COMPLETED", "SCOUT_RUNNING", "MISSION_CREATED"):
            logger.info(
                f"[job={job_id}] Already past Scout phase (state={current.phase}). Skipping Forge launch."
            )
            return

        # Compile ExecutionPlan from MissionSpecification
        await self._compile_and_store_plan(job_id)

        logger.info(f"[job={job_id}] Mission brief ready. Launching Forge.")
        await transition_and_save(self.redis, job_id, "FORGE_RUNNING", agent="Forge")
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "forge", "start")

        forge = ForgeAgent(job_id=job_id)
        forge.redis = self._make_redis_client()
        try:
            await forge.run()
            # Avoid race with event-driven _on_training_script_ready
            # (TOCTOU is inherent — catch harmless double-transition)
            try:
                current = await MissionState.load_from_redis(self.redis, job_id)
                if current and current.phase in ("FORGE_RUNNING",):
                    await transition_and_save(
                        self.redis,
                        job_id,
                        "FORGE_COMPLETED",
                        agent="Forge",
                        message="Forge completed",
                    )
            except ValueError:
                pass
        except Exception as e:
            logger.error(f"[job={job_id}] Forge failed: {e}")
            await self._handle_escalate(job_id, "Forge", f"Forge execution failed: {e}")

    async def _on_training_script_ready(self, data: dict) -> None:
        job_id = data.get("job_id", "?")

        # Guard against re-entry: if Furnace is already running or past, skip
        current = await MissionState.load_from_redis(self.redis, job_id)
        if current and current.phase not in ("FORGE_COMPLETED", "FORGE_RUNNING"):
            logger.info(
                f"[job={job_id}] Already past Forge phase (state={current.phase}). Skipping Furnace launch."
            )
            return

        # If Forge is still running (inline path hasn't reached FORGE_COMPLETED yet),
        # advance the state so the FURNACE_RUNNING transition is valid
        if current and current.phase == "FORGE_RUNNING":
            await transition_and_save(
                self.redis,
                job_id,
                "FORGE_COMPLETED",
                agent="Forge",
                message="Forge completed (via training script ready)",
            )

        script_path = data.get("script_path", "")
        # Mark forge_generate as completed in plan state
        await self._update_plan_state(job_id, "forge_generate", "completed")
        logger.info(f"[job={job_id}] Training script ready. Launching Furnace.")
        await transition_and_save(self.redis, job_id, "FURNACE_RUNNING", agent="Furnace")
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "forge", "end")
            record_stage(job_id, "furnace", "start")
        await self.redis.set(f"job:{job_id}:script_path", script_path)

        # Read search space from Redis and pass to Furnace as serialized JSON
        search_space_json = None
        search_key = data.get("search_space_redis_key")
        if search_key:
            raw = await self.redis.get(search_key)
            if raw:
                search_space_json = raw

        furnace = FurnaceAgent(job_id=job_id)
        furnace.redis = self._make_redis_client()
        await self.redis.set(
            f"job:{job_id}:training_started_at", str(datetime.now(timezone.utc).timestamp())
        )
        try:
            await furnace.run(script_path=script_path, search_space_json=search_space_json)
            try:
                # Avoid race with event-driven _on_training_complete or _consume_dissect RESUME_TRAINING
                current = await MissionState.load_from_redis(self.redis, job_id)
                if current and current.phase in ("FURNACE_RUNNING",):
                    await transition_and_save(
                        self.redis,
                        job_id,
                        "FURNACE_COMPLETED",
                        agent="Furnace",
                        message="Furnace completed",
                    )
            except ValueError:
                pass
        except Exception as e:
            logger.error(f"[job={job_id}] Furnace failed: {e}")
            await self._handle_escalate(
                job_id,
                "Furnace",
                f"Furnace execution failed: {e}",
            )

    async def _on_training_complete(self, data: dict) -> None:
        job_id = data.get("job_id", "?")

        # Guard against re-entry: if Arbiter is already running or past, skip
        current = await MissionState.load_from_redis(self.redis, job_id)
        if current and current.phase not in ("FURNACE_COMPLETED", "FURNACE_RUNNING"):
            logger.info(
                f"[job={job_id}] Already past Furnace phase (state={current.phase}). Skipping Arbiter launch."
            )
            return

        # Mark furnace_train as completed in plan state
        await self._update_plan_state(job_id, "furnace_train", "completed")
        logger.info(f"[job={job_id}] Training complete. Launching Arbiter.")
        # Advance from FURNACE_RUNNING → FURNACE_COMPLETED first if needed
        # (state machine allows FURNACE_COMPLETED → ARBITER_RUNNING, not direct)
        if current and current.phase == "FURNACE_RUNNING":
            try:
                await transition_and_save(
                    self.redis,
                    job_id,
                    "FURNACE_COMPLETED",
                    agent="Furnace",
                    message="Furnace completed (via training complete event)",
                )
            except ValueError:
                pass
        try:
            await transition_and_save(self.redis, job_id, "ARBITER_RUNNING", agent="Arbiter")
        except ValueError:
            pass
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "furnace", "end")
            record_stage(job_id, "arbiter", "start")
        await self.redis.set(
            f"job:{job_id}:checkpoint",
            json.dumps({"checkpoint_path": data.get("checkpoint_path", "")}),
        )
        # Persist training outcome for mission report
        await self.redis.set(
            f"job:{job_id}:training_complete",
            json.dumps(data, default=str),
        )

        arbiter = ArbiterAgent(job_id=job_id)
        arbiter.redis = self._make_redis_client()
        try:
            await arbiter.on_training_complete(data)
        except Exception as e:
            logger.error(f"[job={job_id}] Arbiter failed: {e}")
            await self._handle_escalate(
                job_id,
                "Arbiter",
                f"Arbiter execution failed: {e}",
            )

    async def _on_crash_event(self, data: dict) -> None:
        """Handle CRASH_EVENT from Furnace by launching Dissect to patch the error."""
        job_id = data.get("job_id", "?")
        if eval_config.DISABLE_DISSECT:
            logger.info(f"[job={job_id}] Dissect disabled — escalating crash")
            await self._handle_escalate(
                job_id,
                "Furnace",
                f"Crash with Dissect disabled: {data.get('exception_type', '?')}: {data.get('exception_message', '?')}",
            )
            return
        logger.info(f"[job={job_id}] Crash event received. Launching Dissect.")
        await transition_and_save(
            self.redis,
            job_id,
            "TRAINING_FAILED",
            agent="Furnace",
            message=f"Crash: {data.get('exception_type', '?')}: {data.get('exception_message', '?')}",
        )
        await transition_and_save(self.redis, job_id, "DISSECT_RUNNING", agent="Dissect")
        if eval_config.PROFILE_MODE:
            record_stage(job_id, "dissect", "start")

        from agents.dissect.agent import DissectAgent

        dissect = DissectAgent(job_id=job_id)
        dissect.redis = self._make_redis_client()

        # Data from Redis Streams comes as flat string values; reconstruct the dict
        crash_event = {
            "job_id": data.get("job_id", job_id),
            "exception_type": data.get("exception_type", "UnknownError"),
            "exception_message": data.get("exception_message", ""),
            "traceback": data.get("traceback", ""),
            "script_path": data.get("script_path", ""),
            "last_checkpoint_path": data.get("last_checkpoint_path", ""),
            "epoch_at_crash": int(data.get("epoch_at_crash", 0)),
            "crash_attempt_number": int(data.get("crash_attempt_number", 1)),
        }
        try:
            await dissect.handle_crash(crash_event)
        except Exception as e:
            logger.error(f"[job={job_id}] Dissect failed: {e}")
            await self._handle_escalate(job_id, "Dissect", f"Dissect execution failed: {e}")

    async def _on_arbiter_decision(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        event_type = data.get("event_type", "")
        decision = (
            "pass"
            if event_type == EVALUATION_PASS
            else ("retry" if event_type == EVALUATION_RETRY else "escalate")
        )
        logger.info(f"[job={job_id}] Arbiter decision: {decision}")

        outcome_label = {"pass": "success", "retry": "retry", "escalate": "escalate"}[decision]
        outcome_metric = data.get("primary_metric_value")

        # Store outcome in architecture memory
        try:
            from memory.collections.architecture_memory import store_architecture

            decision_id = await self.redis.get(f"job:{job_id}:architecture_decision_id")
            brief = None
            try:
                rc = self._make_redis_client()
                brief = await rc.get_json(f"job:{job_id}:mission_brief")
            except Exception:
                pass

            if decision_id and brief:
                store_architecture(
                    decision_id=decision_id,
                    job_id=job_id,
                    modality=brief.get("modality", "tabular"),
                    task_type=brief.get("task_type", "classification"),
                    num_rows=brief.get("dataset", {}).get("num_rows", 0),
                    class_imbalance_ratio=brief.get("data_quality", {}).get(
                        "class_imbalance_ratio"
                    ),
                    model_selected=brief.get("recommended_architecture_family", "lightgbm"),
                    imbalance_strategy=brief.get("imbalance_strategy", "none"),
                    outcome_metric=outcome_metric,
                    outcome_label=outcome_label,
                )
                logger.info(f"[job={job_id}] Architecture outcome stored: {outcome_label}")
        except Exception as e:
            logger.warning(f"[job={job_id}] Failed to store architecture outcome: {e}")

        if decision == "pass":
            # Advance via ARBITER_RUNNING → ARBITER_COMPLETED → MISSION_PASSED → HARBOR_DEPLOYING
            try:
                await transition_and_save(self.redis, job_id, "ARBITER_COMPLETED", agent="Arbiter")
            except ValueError:
                pass
            try:
                await transition_and_save(self.redis, job_id, "MISSION_PASSED", agent="Arbiter")
            except ValueError:
                pass
            await transition_and_save(self.redis, job_id, "HARBOR_DEPLOYING", agent="Harbor")
            harbor = HarborAgent(job_id=job_id)
            harbor.redis = self._make_redis_client()
            try:
                await harbor.on_evaluation_pass(data)
            except Exception as e:
                logger.error(f"[job={job_id}] Harbor failed: {e}")
                await self._handle_escalate(
                    job_id,
                    "Harbor",
                    f"Harbor execution failed: {e}",
                )
            # Mark arbiter_evaluate as completed (pass condition) for plan state
            await self._mark_task_completed(job_id, "arbiter_evaluate", condition="pass")

        elif decision == "retry":
            await transition_and_save(
                self.redis,
                job_id,
                "RETRY_RUNNING",
                agent="Forge",
                message="Score within 15% threshold — retrying with new architecture",
            )
            # Increment retry counter so Forge can deprioritize previously-tried architectures
            await self.redis.incr(f"job:{job_id}:retry_count")
            logger.info(f"[job={job_id}] Score within 15% — retrying with new architecture")
            # Use plan-based dispatch: mark arbiter_evaluate completed with "retry" condition
            # The plan tells us the next task is forge_retry
            await self._mark_task_completed(job_id, "arbiter_evaluate", condition="retry")

        elif decision == "escalate":
            await self._handle_escalate(
                job_id,
                "Arbiter",
                data.get("reason", "Metrics too low"),
            )

    async def _on_escalate(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        source = data.get("source_agent", "Unknown")
        reason = data.get("reason", "No reason provided")
        await self._handle_escalate(job_id, source, reason)

    async def _handle_escalate(self, job_id: str, source: str, reason: str) -> None:
        logger.error(f"[job={job_id}] ESCALATED by {source}: {reason}")

        await transition_and_save(
            self.redis, job_id, "MISSION_FAILED", agent=source, message=f"Escalated: {reason}"
        )

        # Publish agent error event so transcript consumer renders the failure
        try:
            await emit_agent_event(
                client=self.redis,
                mission_id=job_id,
                agent=source,
                state="error",
                summary=f"Escalated: {reason}",
                detail={"reason": reason},
            )
        except Exception as e:
            logger.warning(f"[job={job_id}] Failed to emit agent error event: {e}")

        # Mark plan as failed
        await self._handle_plan_terminal(job_id, "__plan_failed__")

        # Record execution outcome (failure)
        await self._record_execution_outcome(job_id, deployment_success=False)

        report = {
            "job_id": job_id,
            "source_agent": source,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "escalated": True,
        }

        jp = get_job_paths(job_id)
        os.makedirs(str(jp.job_dir), exist_ok=True)
        with open(str(jp.diagnostic_report_path), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        # Generate mission report for escalated jobs
        try:
            await generate_mission_report(job_id, self.redis)
        except Exception as e:
            logger.warning(f"[job={job_id}] Mission report generation failed: {e}")

        # Kill training container if running (per CLAUDE.md §14 ESCALATE Resolution Path)
        try:
            from training.docker_manager import DockerManager

            docker = DockerManager()
            await docker.kill_container(job_id)
        except Exception as e:
            logger.warning(f"[job={job_id}] Failed to kill training container: {e}")

        await self._publish_job_failed(job_id, source, reason)

    async def _publish_job_failed(self, job_id: str, source: str, reason: str) -> None:
        from bus.publisher import publish

        from contracts.events import JobFailedEvent

        await publish(
            self.redis,
            STREAM_ORCHESTRATOR_OUT,
            JOB_FAILED,
            JobFailedEvent(
                job_id=job_id,
                source_agent=source,
                reason=reason,
                diagnostic_report_path=str(get_job_paths(job_id).diagnostic_report_path),
            ),
        )

    async def _on_endpoint_live(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        endpoint = data.get("endpoint_url", "?")
        logger.info(f"[job={job_id}] Model live at {endpoint}")
        await transition_and_save(self.redis, job_id, "HARBOR_COMPLETED", agent="Harbor")
        # Mark plan as completed
        await self._handle_plan_terminal(job_id, "__plan_complete__")

        # Record execution outcome
        await self._record_execution_outcome(job_id, deployment_success=True)

        # Generate mission report after successful deployment
        try:
            await generate_mission_report(
                job_id,
                self.redis,
                deploy_data=data,
                pipeline_duration_seconds=None,
            )
        except Exception as e:
            logger.warning(f"[job={job_id}] Mission report generation failed: {e}")

    async def _on_drift_alert(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        psi = data.get("psi_score", 0.0)
        logger.warning(
            f"[job={job_id}] Drift detected: PSI={psi}. " f"Starting new cycle via Scout."
        )
        await transition_and_save(
            self.redis, job_id, "SCOUT_RETRAIN", agent="Scout", message=f"Drift detected: PSI={psi}"
        )

        file_path = await self.redis.get(f"job:{job_id}:file_path")
        problem_description = await self.redis.get(f"job:{job_id}:problem_description")
        if not file_path:
            logger.error(
                f"[job={job_id}] Cannot restart drift cycle: "
                f"original file_path not found in Redis"
            )
            return

        scout = ScoutAgent(job_id=job_id)
        scout.redis = self._make_redis_client()
        brief_key = f"job:{job_id}:mission_brief"
        brief = await self.redis.get_json(brief_key)
        target_col = (brief or {}).get("target_column")

        scout.job_data = {
            "problem_description": problem_description or "",
            "file_path": file_path,
            "target_column": target_col,
            "constraints": None,
        }
        try:
            await scout.run()
        except Exception as e:
            logger.error(f"[job={job_id}] Scout failed during " f"drift-triggered retrain: {e}")
            await self._handle_escalate(
                job_id,
                "Scout",
                f"Drift-triggered Scout run failed: {e}",
            )

    async def _set_job_status(self, job_id: str, status: str, agent: str) -> None:
        canonical = canonical_phase(status)
        await transition_and_save(self.redis, job_id, canonical, agent=agent)
        await self.redis.set(f"job:{job_id}:current_agent", agent)


async def main() -> None:
    """Entry point: starts the orchestrator and runs until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    runtime = OrchestratorRuntime()
    await runtime.initialize()

    from orchestrator.patch_log_writer import run_writer

    writer_task = asyncio.create_task(run_writer())

    try:
        await runtime.run()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.critical(f"Orchestrator runtime crashed: {e}", exc_info=True)
    finally:
        writer_task.cancel()
        try:
            await writer_task
        except asyncio.CancelledError:
            pass
        await runtime.stop()


if __name__ == "__main__":
    asyncio.run(main())

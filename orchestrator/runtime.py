"""
Orchestrator runtime — the main event loop that manages all agents.

Launches agents in response to events on Redis Streams.
Manages the pipeline: Scout -> Forge -> Furnace <-> Dissect -> Arbiter -> Harbor.
Handles ESCALATE -> JOB_FAILED and EVALUATION_RETRY -> Forge loop.
"""

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv
import redis.asyncio as aioredis

from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from agents.dissect.agent import DissectAgent
from agents.arbiter.agent import ArbiterAgent
from agents.harbor.agent import HarborAgent
from agents.scout.agent import ScoutAgent
from memory.redis_client import RedisClient
from bus.events import (
    MISSION_BRIEF_READY,
    TRAINING_SCRIPT_READY,
    TRAINING_COMPLETE,
    CRASH_EVENT,
    RESUME_TRAINING,
    EVALUATION_PASS,
    EVALUATION_RETRY,
    ESCALATE,
    JOB_FAILED,
    ENDPOINT_LIVE,
    DRIFT_ALERT,
    STREAM_SCOUT_OUTPUT,
    STREAM_FORGE_OUTPUT,
    STREAM_FURNACE_OUTPUT,
    STREAM_FURNACE_CRASH,
    STREAM_DISSECT_OUTPUT,
    STREAM_ARBITER_OUTPUT,
    STREAM_HARBOR_OUTPUT,
    STREAM_ORCHESTRATOR_OUT,
    GROUP_ORCHESTRATOR,
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

    def _make_redis_client(self) -> RedisClient:
        rc = RedisClient()
        rc._client = self.redis
        return rc

    async def _ensure_consumer_groups(self) -> None:
        """Create all required consumer groups if they don't exist."""
        streams_groups = {
            STREAM_FURNACE_OUTPUT: [GROUP_ORCHESTRATOR, "arbiter_consumers"],
            STREAM_FURNACE_CRASH: ["dissect_consumers"],
            STREAM_DISSECT_OUTPUT: [GROUP_ORCHESTRATOR, "furnace_consumers"],
            STREAM_ARBITER_OUTPUT: [GROUP_ORCHESTRATOR, "harbor_consumers"],
            STREAM_HARBOR_OUTPUT: [GROUP_ORCHESTRATOR, "scout_consumers"],
            STREAM_SCOUT_OUTPUT: [GROUP_ORCHESTRATOR],
            STREAM_FORGE_OUTPUT: [GROUP_ORCHESTRATOR],
        }

        for stream, groups in streams_groups.items():
            for group in groups:
                try:
                    await self.redis.xgroup_create(
                        stream, group, id="0", mkstream=True
                    )
                except Exception:
                    pass

        logger.info("Consumer groups ensured")

    async def run(self) -> None:
        """Main event loop. Listens on all orchestrator streams in parallel."""
        self._running = True
        logger.info("Orchestrator runtime started")

        consumers = [
            self._consume_scout(),
            self._consume_forge(),
            self._consume_furnace(),
            self._consume_dissect(),
            self._consume_arbiter(),
            self._consume_harbor(),
        ]

        await asyncio.gather(*consumers)

    async def stop(self) -> None:
        self._running = False
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
                            if event_type == ESCALATE:
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

    async def _on_mission_brief_ready(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        logger.info(
            f"[job={job_id}] Mission brief ready. Launching Forge."
        )
        await self._set_job_status(job_id, "FORGE_WORKING", "Forge")

        forge = ForgeAgent(job_id=job_id)
        forge.redis = self._make_redis_client()
        try:
            await forge.run()
        except Exception as e:
            logger.error(f"[job={job_id}] Forge failed: {e}")
            await self._handle_escalate(
                job_id, "Forge", f"Forge execution failed: {e}"
            )

    async def _on_training_script_ready(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        script_path = data.get("script_path", "")
        logger.info(
            f"[job={job_id}] Training script ready. Launching Furnace."
        )
        await self._set_job_status(
            job_id, "FURNACE_TRAINING", "Furnace"
        )
        await self.redis.set(
            f"job:{job_id}:script_path", script_path
        )

        furnace = FurnaceAgent(job_id=job_id)
        furnace.redis = self._make_redis_client()
        try:
            await furnace.run(script_path=script_path)
        except Exception as e:
            logger.error(f"[job={job_id}] Furnace failed: {e}")
            await self._handle_escalate(
                job_id,
                "Furnace",
                f"Furnace execution failed: {e}",
            )

    async def _on_training_complete(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        logger.info(
            f"[job={job_id}] Training complete. Launching Arbiter."
        )
        await self._set_job_status(
            job_id, "ARBITER_EVALUATING", "Arbiter"
        )
        await self.redis.set(
            f"job:{job_id}:checkpoint",
            json.dumps(
                {
                    "checkpoint_path": data.get(
                        "checkpoint_path", ""
                    )
                }
            ),
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

    async def _on_arbiter_decision(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        event_type = data.get("event_type", "")
        decision = (
            "pass"
            if event_type == EVALUATION_PASS
            else (
                "retry"
                if event_type == EVALUATION_RETRY
                else "escalate"
            )
        )
        logger.info(f"[job={job_id}] Arbiter decision: {decision}")

        if decision == "pass":
            await self._set_job_status(
                job_id, "HARBOR_DEPLOYING", "Harbor"
            )
            harbor = HarborAgent(job_id=job_id)
            harbor.redis = self._make_redis_client()
            try:
                await harbor.on_evaluation_pass(data)
            except Exception as e:
                logger.error(
                    f"[job={job_id}] Harbor failed: {e}"
                )
                await self._handle_escalate(
                    job_id,
                    "Harbor",
                    f"Harbor execution failed: {e}",
                )

        elif decision == "retry":
            await self._set_job_status(
                job_id, "FORGE_RETRY", "Forge"
            )
            logger.info(
                f"[job={job_id}] Score within 15% — retrying "
                f"with new architecture"
            )
            # Re-publish MISSION_BRIEF_READY to re-trigger Forge
            # with the SAME mission brief. Scout is NOT re-run on
            # retry per CLAUDE.md Section 13.1.
            from bus.publisher import publish as _publish

            await _publish(
                self.redis,
                STREAM_SCOUT_OUTPUT,
                MISSION_BRIEF_READY,
                {
                    "job_id": job_id,
                    "mission_brief_redis_key": (
                        f"job:{job_id}:mission_brief"
                    ),
                },
            )

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

    async def _handle_escalate(
        self, job_id: str, source: str, reason: str
    ) -> None:
        logger.error(
            f"[job={job_id}] ESCALATED by {source}: {reason}"
        )

        await self._set_job_status(job_id, "ESCALATED", source)

        report = {
            "job_id": job_id,
            "source_agent": source,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "escalated": True,
        }

        os.makedirs(f"outputs/{job_id}", exist_ok=True)
        with open(
            f"outputs/{job_id}/diagnostic_{job_id}.json", "w"
        ) as f:
            json.dump(report, f, indent=2)

        await self._publish_job_failed(job_id, source, reason)

    async def _publish_job_failed(
        self, job_id: str, source: str, reason: str
    ) -> None:
        from bus.publisher import publish

        await publish(
            self.redis,
            STREAM_ORCHESTRATOR_OUT,
            JOB_FAILED,
            {
                "job_id": job_id,
                "source_agent": source,
                "reason": reason,
                "diagnostic_report_path": (
                    f"outputs/{job_id}/diagnostic_{job_id}.json"
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def _on_endpoint_live(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        endpoint = data.get("endpoint_url", "?")
        logger.info(f"[job={job_id}] Model live at {endpoint}")
        await self._set_job_status(job_id, "COMPLETED", "Harbor")

    async def _on_drift_alert(self, data: dict) -> None:
        job_id = data.get("job_id", "?")
        psi = data.get("psi_score", 0.0)
        logger.warning(
            f"[job={job_id}] Drift detected: PSI={psi}. "
            f"Starting new cycle via Scout."
        )

        file_path = await self.redis.get(
            f"job:{job_id}:file_path"
        )
        problem_description = await self.redis.get(
            f"job:{job_id}:problem_description"
        )
        if not file_path:
            logger.error(
                f"[job={job_id}] Cannot restart drift cycle: "
                f"original file_path not found in Redis"
            )
            return

        scout = ScoutAgent(job_id=job_id)
        scout.redis = self._make_redis_client()
        scout.job_data = {
            "problem_description": problem_description or "",
            "file_path": file_path,
            "target_column": None,
            "constraints": None,
        }
        try:
            await scout.run()
        except Exception as e:
            logger.error(
                f"[job={job_id}] Scout failed during "
                f"drift-triggered retrain: {e}"
            )
            await self._handle_escalate(
                job_id,
                "Scout",
                f"Drift-triggered Scout run failed: {e}",
            )

    async def _set_job_status(
        self, job_id: str, status: str, agent: str
    ) -> None:
        await self.redis.set(f"job:{job_id}:status", status)
        await self.redis.set(
            f"job:{job_id}:current_agent", agent
        )
        logger.info(
            f"[job={job_id}] Status: {status} (agent: {agent})"
        )


async def main() -> None:
    """Entry point: starts the orchestrator and runs until interrupted."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(
            asyncio.WindowsSelectorEventLoopPolicy()
        )

    runtime = OrchestratorRuntime()
    await runtime.initialize()

    from orchestrator.patch_log_writer import run_writer

    writer_task = asyncio.create_task(run_writer())

    try:
        await runtime.run()
    except asyncio.CancelledError:
        pass
    finally:
        writer_task.cancel()
        try:
            await writer_task
        except asyncio.CancelledError:
            pass
        await runtime.stop()


if __name__ == "__main__":
    sys.path.insert(
        0,
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    asyncio.run(main())

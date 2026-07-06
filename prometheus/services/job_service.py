from __future__ import annotations

import asyncio
import uuid

from prometheus.dto.job_dto import JobResult, JobStatusRow
from prometheus.contracts import IJobService


class JobService(IJobService):
    def list_jobs(self) -> list[JobStatusRow]:
        try:
            from prometheus.core.redis import CliRedis
        except ImportError:
            return []
        rows: list[JobStatusRow] = []

        async def _fetch() -> list[JobStatusRow]:
            redis = CliRedis()
            try:
                ids = await redis.list_job_ids()
                result: list[JobStatusRow] = []
                for jid in ids:
                    s = await redis.get_job_status(jid)
                    result.append(
                        JobStatusRow(
                            id=s.get("job_id", jid)[:8],
                            status=s.get("status", "unknown"),
                            agent=s.get("current_agent", ""),
                            crashes=s.get("crash_count", 0),
                        )
                    )
                return result
            finally:
                await redis.close()

        try:
            rows = asyncio.run(_fetch())
        except Exception:
            pass
        return rows

    def get_status(self, job_id: str) -> JobStatusRow | None:
        try:
            from prometheus.core.redis import CliRedis
        except ImportError:
            return None

        async def _fetch() -> JobStatusRow | None:
            redis = CliRedis()
            try:
                s = await redis.get_job_status(job_id)
                return JobStatusRow(
                    id=s.get("job_id", job_id)[:8],
                    status=s.get("status", "unknown"),
                    agent=s.get("current_agent", ""),
                    crashes=s.get("crash_count", 0),
                )
            finally:
                await redis.close()

        try:
            return asyncio.run(_fetch())
        except Exception:
            return None

    def submit(self, dataset: str, description: str, target_column: str | None = None) -> JobResult:
        from prometheus.core.submission import submit_and_run
        from prometheus.core.pipeline import PipelineError

        job_id = str(uuid.uuid4())
        result: JobResult | None = None

        async def _run() -> JobResult:
            r = await submit_and_run(
                job_id=job_id,
                problem_description=description,
                file_path=dataset,
                target_column=target_column,
            )
            return JobResult(
                id=r.get("job_id", job_id),
                status=r.get("status", "unknown"),
                decision=r.get("decision", ""),
                reason=r.get("reason", ""),
                metrics=r.get("metrics", {}),
                endpoint_url=r.get("endpoint_url"),
                checkpoint_path=r.get("checkpoint_path"),
            )

        try:
            result = asyncio.run(_run())
        except PipelineError as e:
            return JobResult(id=job_id, status="failed", reason=str(e))

        return result or JobResult(id=job_id, status="failed", reason="No result returned")

    def cancel(self, job_id: str) -> bool:
        try:
            from prometheus.core.redis import CliRedis
        except ImportError:
            return False

        async def _cancel() -> bool:
            redis = CliRedis()
            try:
                await redis.update_job_status(job_id, "cancelled")
                return True
            finally:
                await redis.close()

        try:
            return asyncio.run(_cancel())
        except Exception:
            return False

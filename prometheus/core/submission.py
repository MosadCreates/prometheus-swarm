from typing import Any

from prometheus.core.pipeline import run_pipeline, PipelineError


async def submit_and_run(
    job_id: str,
    problem_description: str,
    file_path: str,
    target_column: str | None = None,
    constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return await run_pipeline(
        job_id=job_id,
        problem_description=problem_description,
        file_path=file_path,
        target_column=target_column,
        constraints=constraints,
    )

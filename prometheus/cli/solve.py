from __future__ import annotations

import asyncio
import os

import click

from prometheus.ui.components import Spinner
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.command(name="solve")
@click.argument("dataset", type=click.Path(exists=True))
@click.option("--description", "-d", required=True, help="Natural-language problem description")
@click.option("--target-column", "-t", default=None, help="Name of the target column")
@click.option("--watch", "-w", is_flag=True, help="Watch agent events after submission")
@click.pass_context
def solve(ctx, dataset, description, target_column, watch):
    """Submit a dataset + problem description to the event-driven swarm.

    DATASET is the path to your dataset file (CSV, JSON, etc.).
    """
    renderer = renderer_from_ctx(ctx)
    dataset_path = os.path.abspath(dataset)

    async def _submit():
        from orchestrator.job_queue import submit_job

        constraints = {}
        if target_column:
            constraints["target_column"] = target_column

        job_id = await submit_job(description, dataset_path, constraints)
        return job_id

    with Spinner("Submitting to swarm..."):
        try:
            job_id = asyncio.run(_submit())
        except Exception as e:
            renderer.error(str(e), title="Submission failed")
            return ExitCode.ERROR

    renderer.print(
        f"  [green]\u2713 Job submitted [{job_id[:8]}][/green]  " f"[dim](full ID: {job_id})[/dim]"
    )
    renderer.print(f"  [dim]Next:[/dim] [bold]prometheus explain {job_id[:8]}[/bold]")

    if watch:
        _run_replay(renderer, job_id)

    return ExitCode.SUCCESS


def _run_replay(renderer, job_id: str) -> None:
    """Live-stream agent events for the given job_id."""
    from bus.events import ALL_EVENT_STREAMS

    renderer.print(f"\n[dim]Waiting for events on job {job_id[:8]}... Ctrl+C to stop[/dim]")

    async def _watch():
        from memory.redis_client import RedisClient

        redis = RedisClient()
        await redis.connect()
        try:
            ids = {s: "$" for s in ALL_EVENT_STREAMS}
            while True:
                results = await redis._client.xread(
                    {s: ids[s] for s in ALL_EVENT_STREAMS},
                    block=2000,
                    count=10,
                )
                if not results:
                    continue
                for stream_name, messages in results:
                    for msg_id, msg_data in messages:
                        ids[
                            stream_name.decode() if isinstance(stream_name, bytes) else stream_name
                        ] = msg_id
                        payload = {
                            k.decode() if isinstance(k, bytes) else k: (
                                v.decode() if isinstance(v, bytes) else v
                            )
                            for k, v in msg_data.items()
                        }
                        if payload.get("job_id") == job_id or payload.get("job_id") == job_id[:8]:
                            event_type = payload.get("event_type", "?")
                            renderer.print(
                                f"  [{stream_name.decode() if isinstance(stream_name, bytes) else stream_name}] {event_type}  {payload.get('timestamp', '')}"
                            )
                    if not results:
                        await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            await redis.close()

    try:
        asyncio.run(_watch())
    except KeyboardInterrupt:
        renderer.print("[dim]\nWatching stopped.[/dim]")

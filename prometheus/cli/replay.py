from __future__ import annotations

import asyncio
import json

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


_STREAM_LABELS = {
    "scout_output": "Scout",
    "forge_output": "Forge",
    "furnace_feed": "Furnace",
    "furnace_output": "Furnace",
    "furnace_crash": "Furnace",
    "dissect_output": "Dissect",
    "arbiter_output": "Arbiter",
    "harbor_output": "Harbor",
    "orchestrator_output": "Orchestrator",
}


@click.command(name="replay")
@click.argument("job_id")
@click.option("--follow", "-f", is_flag=True, help="Keep watching for new events")
@click.option(
    "--all", "-a", "show_all", is_flag=True, help="Show events for all jobs (not just this one)"
)
@click.pass_context
def replay(ctx, job_id, follow, show_all):
    """Replay agent activity for a given job from Redis streams.

    Reads events from all 9 agent streams. Shows events for the given
    JOB_ID by default (omit with --all to see everything).

    Use --follow to tail new events live.
    """
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        from bus.events import ALL_EVENT_STREAMS
        from memory.redis_client import RedisClient

        redis = RedisClient()
        await redis.connect()
        try:
            count = 0
            ids = {s: "0" for s in ALL_EVENT_STREAMS}

            while True:
                results = await redis._client.xread(
                    {s: ids[s] for s in ALL_EVENT_STREAMS},
                    block=2000 if follow else 100,
                    count=50,
                )
                if not results:
                    if follow:
                        continue
                    break

                for stream_name, messages in results:
                    sn = stream_name.decode() if isinstance(stream_name, bytes) else stream_name
                    for msg_id, msg_data in messages:
                        ids[sn] = msg_id
                        payload = _decode_payload(msg_data)
                        if show_all or _matches_job(payload, job_id):
                            _render_event(renderer, sn, msg_id, payload)
                            count += 1

                if not follow:
                    break

            return count
        finally:
            await redis.close()

    renderer.print(f"[dim]Reading events for job {job_id[:8]}...[/dim]")
    try:
        total = asyncio.run(_fetch())
        renderer.print(f"\n[dim]{total} event(s) shown.[/dim]")
    except KeyboardInterrupt:
        renderer.print("[dim]\nReplay stopped.[/dim]")
    return ExitCode.SUCCESS


def _decode_payload(msg_data: dict) -> dict:
    """Decode bytes keys/values from a Redis stream message."""
    payload = {}
    for k, v in msg_data.items():
        key = k.decode() if isinstance(k, bytes) else k
        if isinstance(v, bytes):
            try:
                payload[key] = json.loads(v.decode())
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload[key] = v.decode()
        else:
            payload[key] = v
    return payload


def _matches_job(payload: dict, job_id: str) -> bool:
    pjid = payload.get("job_id", "")
    return pjid == job_id or pjid == job_id[:8]


def _render_event(renderer, stream_name: str, msg_id: str, payload: dict) -> None:
    """Format a single event line for terminal output."""
    agent = _STREAM_LABELS.get(stream_name, stream_name)
    event_type = payload.get("event_type", "?")
    ts = (payload.get("timestamp") or "")[:19].replace("T", " ")

    metric = (
        payload.get("best_val_metric")
        or payload.get("primary_metric_value")
        or payload.get("train_loss")
    )
    detail = ""
    if metric is not None:
        detail = f"  [yellow]{metric}[/]"
    elif payload.get("exception_type"):
        detail = f"  [red]{payload['exception_type']}[/]"
    elif payload.get("endpoint_url"):
        detail = f"  [green]{payload['endpoint_url']}[/]"
    elif payload.get("decision"):
        detail = f"  [bold]{payload['decision']}[/]"

    renderer.print(f"  [{agent:12s}] {event_type:30s} {ts}{detail}")

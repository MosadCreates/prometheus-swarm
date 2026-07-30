from __future__ import annotations

import asyncio
import json

import click

from prometheus.cli.output import detect_format, Format
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
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (default: auto-detect)",
)
@click.option("--follow", "-f", is_flag=True, help="Keep watching for new events")
@click.option(
    "--all", "-a", "show_all", is_flag=True, help="Show events for all jobs (not just this one)"
)
@click.pass_context
def replay(ctx, job_id, output_format, follow, show_all):
    """Replay agent activity for a given job from Redis streams.

    Reads events from all 9 agent streams. Shows events for the given
    JOB_ID by default (omit with --all to see everything).

    Use --follow to tail new events live.
    """
    renderer = renderer_from_ctx(ctx)
    if output_format:
        ctx.find_root().obj["format"] = output_format
    fmt = detect_format(ctx)

    async def _fetch():
        from bus.events import ALL_EVENT_STREAMS
        from memory.redis_client import RedisClient

        redis = RedisClient()
        await redis.connect()
        try:
            count = 0
            ids = {s: "0" for s in ALL_EVENT_STREAMS}
            all_events: list[dict] = []

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
                            event = _build_event(sn, msg_id, payload)
                            all_events.append(event)
                            count += 1

                if not follow:
                    break

            return all_events
        finally:
            await redis.close()

    if fmt != Format.JSON:
        renderer.print(f"[dim]Reading events for job {job_id[:8]}...[/dim]")

    try:
        events = asyncio.run(_fetch())
    except KeyboardInterrupt:
        renderer.print("[dim]\nReplay stopped.[/dim]")
        return ExitCode.SUCCESS

    _emit_events(ctx, fmt, job_id, events)
    return ExitCode.SUCCESS


def _build_event(stream_name: str, msg_id: str, payload: dict) -> dict:
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
        detail = f"metric={metric}"
    elif payload.get("exception_type"):
        detail = f"exception={payload['exception_type']}"
    elif payload.get("endpoint_url"):
        detail = f"url={payload['endpoint_url']}"
    elif payload.get("decision"):
        detail = f"decision={payload['decision']}"

    return {
        "agent": agent,
        "event_type": event_type,
        "timestamp": ts,
        "detail": detail,
        "stream": stream_name,
        "msg_id": msg_id,
    }


def _emit_events(ctx: click.Context, fmt: Format, job_id: str, events: list[dict]) -> None:
    match fmt:
        case Format.JSON:
            print(
                json.dumps(
                    {
                        "schema": "prometheus.replay.v1",
                        "job_id": job_id,
                        "count": len(events),
                        "events": events,
                    },
                    indent=2,
                    default=str,
                )
            )
        case Format.PLAIN:
            for ev in events:
                parts = [ev["timestamp"], ev["agent"], ev["event_type"]]
                if ev["detail"]:
                    parts.append(ev["detail"])
                print("  ".join(parts))
            if events:
                print(f"{len(events)} event(s) shown.")
        case Format.INTERACTIVE:
            r = renderer_from_ctx(ctx)
            r.print(f"\n  [dim]{len(events)} event(s) shown.[/dim]")


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

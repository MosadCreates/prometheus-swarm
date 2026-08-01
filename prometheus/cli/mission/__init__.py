from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.group(
    name="mission",
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def mission():
    """Create, manage, and inspect missions."""


@mission.command(name="new")
@click.argument("problem", required=False, default=None)
@click.option("--watch/--no-watch", default=None, help="Show live progress (default: auto-detect)")
@click.option(
    "--cockpit",
    is_flag=True,
    default=False,
    help="Use the full Cockpit TUI instead of the Claude-style transcript",
)
@click.option(
    "--auto", is_flag=True, help="Skip clarifying questions; proceed on best-guess defaults"
)
@click.option("--target", default=None, help="Name of the target column in the dataset")
@click.option("--dataset", "-d", default=None, help="Path to dataset file")
@click.option("--budget", default=None, type=float, help="LLM spend ceiling for the mission")
@click.option("--time-limit", default=None, help="Wall-clock ceiling before auto-cancel")
@click.option(
    "--block", is_flag=True, default=False, help="Run synchronously (block until completion)"
)
@click.option("--quiet", is_flag=True, default=False, help="Flat line output (CI/piping, no Rich)")
@click.pass_context
def mission_new(
    ctx: click.Context,
    problem: str | None,
    watch: bool | None,
    cockpit: bool,
    auto: bool,
    target: str | None,
    dataset: str | None,
    budget: float | None,
    time_limit: str | None,
    block: bool,
    quiet: bool,
) -> ExitCode:
    """Create and start a new mission — the six-agent pipeline, end to end.

    Provide a free-text problem description as the first argument:

      prometheus mission new "predict passenger survival" --dataset titanic.csv

    Omit PROBLEM to enter interactive prompt mode.  Use --auto for
    batch/CI use (no prompts).  Default is --watch in a terminal and
    --no-watch when piped.

    Use --block to run the full pipeline synchronously in the current
    terminal (no daemon needed).

    By default, the live transcript is rendered as a Claude Code-style
    sequence of agent badges and status indicators.  Use --cockpit for
    the full Textual TUI dashboard instead.
    """
    renderer = renderer_from_ctx(ctx)
    console = renderer.console

    # Auto-detect watch mode: --watch when TTY, --no-watch when piped
    if watch is None:
        watch = sys.stdout.isatty()

    # Collect problem description if not provided
    if not problem and not dataset:
        if auto:
            renderer.error(
                'Problem description required in --auto mode. Provide a description as an argument: `prometheus mission new "predict survival" --dataset data.csv --auto`.'
            )
            return ExitCode.ERROR
        problem = _prompt_problem(console)
        if problem is None:
            return ExitCode.SUCCESS

        dataset = _extract_dataset_from_description(problem) or dataset

    description = problem or f"Train on dataset at {dataset}"

    # --block runs synchronously via job_runner, no daemon needed
    if block:
        return _run_blocking(
            renderer, description, dataset, target, budget, time_limit, quiet=quiet
        )

    # Check if orchestrator daemon is running before submitting
    async def _check_orch() -> bool:
        try:
            from memory.redis_client import RedisClient

            c = RedisClient()
            await c.connect()
            hb = await c.get_str("orch:heartbeat")
            await c.close()
            return hb is not None
        except Exception:
            return False

    import asyncio as _asyncio

    orch_alive = _asyncio.run(_check_orch())

    if not orch_alive and watch:
        console.print("  [bold yellow]Orchestrator not running — running pipeline directly[/]")
        console.print()
        return _run_blocking(
            renderer, description, dataset, target, budget, time_limit, quiet=quiet
        )

    # Submit to the orchestrator via Redis bus
    from contextlib import nullcontext
    from orchestrator.job_queue import submit_job

    if watch:
        from prometheus.ui.components import Spinner

        submit_status = Spinner("Submitting mission...")
    else:
        console.print("  [dim]Submitting mission...[/dim]")
        submit_status = nullcontext()

    try:
        with submit_status:
            job_id = _asyncio.run(
                submit_job(
                    problem_description=description,
                    dataset_path=dataset or "",
                    target_column=target,
                    constraints=(
                        {"budget": budget, "time_limit": time_limit}
                        if budget or time_limit
                        else None
                    ),
                )
            )
    except KeyboardInterrupt:
        renderer.print("  [dim]Mission creation cancelled.[/dim]")
        return ExitCode.SUCCESS
    except Exception as e:
        renderer.error(
            f"Failed to submit mission: {e}. Check that Redis is running (`docker compose ps`) and the dataset path is valid."
        )
        return ExitCode.ERROR

    from prometheus.utils.slugs import uuid_to_slug

    slug = uuid_to_slug(job_id)
    console.print(f"  Mission created: {slug}")

    if not orch_alive:
        console.print("  [dim]\u26a0 Orchestrator is not running. [/dim]")
        console.print(
            "  [dim]Submit with --block to run synchronously, or start the daemon:  prometheus daemon start[/dim]"
        )

    if watch and cockpit:
        console.print("  watching now --- press p at any time to detach")
        obj = ctx.ensure_object(dict)
        _launch_cockpit(
            job_id,
            description,
            no_color=obj.get("no_color", False),
            high_contrast=obj.get("high_contrast", False),
            font_size=obj.get("font_size"),
        )
    elif watch:
        _launch_live_tree(job_id, description, dataset=dataset)

    return ExitCode.SUCCESS


def _prompt_problem(console: Console) -> str | None:
    """Prompt the user for a problem description interactively.

    Uses the shared ``read_input()`` with multiline mode so that
    Ctrl+J (or Alt+Enter) inserts a newline and Enter submits.
    """
    from prometheus.ui.input import read_input

    try:
        result = read_input(
            prompt="  Describe your ML problem:\n  \u203a ",
            multiline=True,
            console=console,
        )
    except (KeyboardInterrupt, EOFError):
        console.print()
        return None

    stripped = result.strip()
    if not stripped or stripped.lower() == "cancel":
        return None
    return stripped


def _extract_dataset_from_description(text: str) -> str | None:
    import re

    match = re.search(r"([^\s\"'`]+\.(?:csv|json|parquet|tsv|xlsx?))", text)
    return match.group(1) if match else None


def _run_blocking(
    renderer: Any,
    description: str,
    dataset: str | None,
    target_column: str | None = None,
    budget: float | None = None,
    time_limit: str | None = None,
    quiet: bool = False,
) -> ExitCode:
    """Run the full pipeline synchronously via job_runner (no daemon needed)."""
    import asyncio
    import os
    import sys
    import time

    import redis.asyncio as aioredis

    from orchestrator.job_runner import JobConfig

    config = JobConfig(
        problem_description=description,
        dataset_path=dataset or "",
        target_column=target_column or "",
        use_harbor=True,
        use_dissect=True,
        timeout_seconds=3600,
    )

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    def _run_job_thread(config: JobConfig):
        """Run job in a dedicated thread with its own event loop and Redis connection.

        This prevents Forge's synchronous script generation (2-20s) and other
        blocking operations from freezing the UI renderer on the main event loop.
        """
        import asyncio as _asyncio
        import sys as _sys

        from memory.redis_client import RedisClient
        from orchestrator.job_runner import run_job

        if _sys.platform == "win32":
            _asyncio.set_event_loop_policy(_asyncio.WindowsSelectorEventLoopPolicy())

        async def _run():
            rc = RedisClient()
            await rc.connect()
            try:
                return await run_job(config, rc._client)
            finally:
                await rc.close()

        return _asyncio.run(_run())

    async def _run_with_ui() -> ExitCode:
        nonlocal config
        ui_redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )

        # Extract dataset name for the header banner
        dataset_name = os.path.basename(dataset) if dataset else ""
        num_rows = 0
        if dataset and os.path.isfile(dataset):
            try:
                import pandas as pd

                df = pd.read_csv(dataset, nrows=0)
                num_rows = df.shape[0]
                # Try to get actual row count via a cheap wc-like approach
                with open(dataset, encoding="utf-8", errors="replace") as f:
                    for line_count, _ in enumerate(f, 1):
                        pass
                    num_rows = max(0, line_count - 1)  # subtract header
            except Exception:
                pass

        from prometheus.ui.claude.unified_live import run_quiet
        from prometheus.ui.stream.renderer import StreamRenderer

        if quiet:
            live_task = asyncio.create_task(run_quiet(ui_redis, config.job_id))
        else:
            renderer = StreamRenderer(
                ui_redis,
                config.job_id,
                description,
                dataset_name=dataset_name,
                num_rows=num_rows,
            )
            await renderer.setup()
            live_task = asyncio.create_task(renderer.run())

        try:
            # Run job in a thread pool to avoid blocking the renderer
            # event loop with Forge's synchronous script generation
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, _run_job_thread, config)
        finally:
            live_task.cancel()
            try:
                await live_task
            except (asyncio.CancelledError, KeyboardInterrupt):
                pass
            await ui_redis.aclose()

        elapsed = time.monotonic() - start
        mins, secs = divmod(int(elapsed), 60)

        if not quiet:
            if result.status == "pass":
                renderer.print(f"  Pipeline complete ({mins}m {secs}s)")
                if result.endpoint_url:
                    renderer.print(f"  Endpoint: {result.endpoint_url}")
                if result.metric_value is not None:
                    renderer.print(f"  {result.metric_name}: {result.metric_value:.4f}")
                return ExitCode.SUCCESS
            else:
                renderer.print(
                    f"  Pipeline finished with status: {result.status} ({mins}m {secs}s)"
                )
                if result.error_detail:
                    renderer.print(f"  Detail: {result.error_detail}")
                return ExitCode.ERROR
        return ExitCode.SUCCESS

    start = time.monotonic()
    try:
        return asyncio.run(_run_with_ui())
    except Exception as e:
        renderer.error(f"Pipeline failed: {e}")
        return ExitCode.ERROR


def _launch_cockpit(
    mission_id: str,
    problem_description: str,
    *,
    no_color: bool = False,
    high_contrast: bool = False,
    font_size: str | None = None,
) -> None:
    """Launch the Textual Mission Cockpit for a live mission."""
    import asyncio
    import os
    import sys

    import redis.asyncio as aioredis

    from bus.consumer import ensure_consumer_group
    from bus.events import GROUP_COCKPIT, STREAM_AGENT_EVENTS
    from prometheus.ui.cockpit.app import CockpitApp

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def _run() -> None:
        redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        try:
            await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")
            app = CockpitApp(
                redis=redis,
                mission_id=mission_id,
                problem_description=problem_description,
                no_color=no_color,
                high_contrast=high_contrast,
                font_size=font_size,
            )
            await app.run_async()
        finally:
            await redis.aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass

    from prometheus.ui.console import console as _cockpit_console

    _cockpit_console.print("  [dim]Detached. Reattach: prometheus mission watch[/dim]")


def _launch_live_tree(
    mission_id: str, problem_description: str = "", dataset: str | None = None
) -> None:
    """Launch unified live streaming renderer for a mission."""
    import asyncio
    import os
    import sys

    import redis.asyncio as aioredis

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Extract dataset metadata for header banner
    dataset_name = os.path.basename(dataset) if dataset else ""
    num_rows = 0
    if dataset and os.path.isfile(dataset):
        try:
            with open(dataset, encoding="utf-8", errors="replace") as f:
                for line_count, _ in enumerate(f, 1):
                    pass
                num_rows = max(0, line_count - 1)
        except Exception:
            pass

    async def _run() -> None:
        redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        try:
            from prometheus.ui.stream.renderer import run_stream

            await run_stream(
                redis, mission_id, problem_description, dataset_name=dataset_name, num_rows=num_rows
            )
        finally:
            await redis.aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


def _launch_claude_transcript(mission_id: str) -> None:
    """Launch Claude Code-style live transcript for a mission."""
    import asyncio
    import os
    import sys

    import redis.asyncio as aioredis

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def _run() -> None:
        redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        try:
            from prometheus.ui.claude.transcript_consumer import watch_mission_transcript

            await watch_mission_transcript(redis, mission_id)
        finally:
            await redis.aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


@mission.command(name="list")
@click.option("--status", "-s", "filter_status", default=None, help="Filter by phase/status")
@click.option("--limit", "-n", default=None, type=int, help="Max missions to show")
@click.pass_context
def mission_list(ctx: click.Context, filter_status: str | None, limit: int | None) -> ExitCode:
    """List missions with their current phase and status."""
    from prometheus.utils.output import emit_str_table, detect_format

    fmt = detect_format(ctx)
    emit_str_table(
        ctx,
        fmt,
        headers=["MISSION", "PROBLEM", "PHASE", "STATUS", "STARTED"],
        rows=_load_mission_summaries(filter_status, limit),
        json_schema="prometheus.mission_list.v1",
    )
    return ExitCode.SUCCESS


@mission.command(name="status")
@click.argument("mission_id", required=False, default=None)
@click.option(
    "--verbose", "-v", is_flag=True, default=False, help="Also show reproducibility context"
)
@click.pass_context
def mission_status(ctx: click.Context, mission_id: str | None, verbose: bool) -> ExitCode:
    """Show current status of a mission (latest by default)."""
    from prometheus.utils.output import emit_dict, detect_format, Format

    fmt = detect_format(ctx)
    mission_id, summary = _resolve_mission(mission_id)
    if mission_id is None or summary is None:
        return ExitCode.ERROR

    slug = summary.get("slug", mission_id[:12])
    status = summary.get("status", "unknown")
    phase = summary.get("phase", "")
    ts = summary.get("timestamp", "")[:19]
    agent = summary.get("agent", "")
    event = summary.get("event", "")

    data = {
        "mission_id": mission_id,
        "slug": slug,
        "phase": phase,
        "status": status,
        "agent": agent,
        "event": event,
        "timestamp": ts,
    }

    if verbose:
        reproducibility = _load_reproducibility_context(mission_id)
        if reproducibility:
            data["reproducibility"] = reproducibility

    if fmt in (Format.JSON, Format.PLAIN):
        emit_dict(ctx, fmt, data, schema="prometheus.status.v1")
    else:
        parts = [f"{slug}"]
        if phase:
            parts.append(f"{phase} {status}".strip())
        if event:
            parts.append(event)
        if ts:
            parts.append(ts)
        sep = " \u00b7 "
        renderer = renderer_from_ctx(ctx)
        renderer.print(f"  {sep.join(parts)}")
        if verbose and data.get("reproducibility"):
            _render_reproducibility(renderer, data["reproducibility"])
    return ExitCode.SUCCESS


def _load_reproducibility_context(job_id: str) -> dict | None:
    """Fetch job:{job_id}:reproducibility from Redis (written at submit time)."""
    import asyncio
    import json

    async def _fetch() -> str | None:
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                return await redis._client.get_str(f"job:{job_id}:reproducibility")
            finally:
                await redis.close()
        except (ImportError, Exception):
            return None

    raw = asyncio.run(_fetch())
    if not raw:
        return None
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return None


def _render_reproducibility(renderer, rc: dict) -> None:
    """Render reproducibility context lines under mission status --verbose."""
    git_hash = rc.get("git_commit", "")
    git_branch = rc.get("git_branch", "")
    dirty = rc.get("has_uncommitted_changes", False)
    dirty_mark = " [red]DIRTY[/]" if dirty else " [green]CLEAN[/]"
    renderer.print("  [bold]Reproducibility:[/]")
    renderer.print(f"    Git:      {git_hash[:12] if git_hash else '[dim]none[/]'}{dirty_mark}")
    if git_branch:
        renderer.print(f"    Branch:   {git_branch}")
    config_hash = rc.get("configuration_hash", "")
    if config_hash:
        renderer.print(f"    Config:   {config_hash}")
    renderer.print(f"    Python:   {rc.get('python_version', '?')}")
    ds_fp = rc.get("dataset_fingerprint", {})
    if ds_fp and ds_fp.get("exists"):
        size_mb = ds_fp.get("size_bytes", 0) / (1024 * 1024)
        renderer.print(
            f"    Dataset:  {ds_fp.get('file_path', '?')}  "
            f"[dim]{size_mb:.1f} MB / {ds_fp.get('content_hash', '')[:12]}[/]"
        )
    renderer.print()


@mission.command(name="logs")
@click.argument("mission_id", required=False, default=None)
@click.option("--follow", "-f", is_flag=True, default=False, help="Follow new events")
@click.option("--agent", default=None, help="Filter by agent name")
@click.option("--level", default=None, help="Filter by event state/level")
@click.option("--since", default=None, help="Show events since ISO timestamp")
@click.option("--lines", "-n", default=None, type=int, help="Number of recent events")
@click.pass_context
def mission_logs(
    ctx: click.Context,
    mission_id: str | None,
    follow: bool,
    agent: str | None,
    level: str | None,
    since: str | None,
    lines: int | None,
) -> ExitCode:
    """Show mission event log as one line per event."""
    from prometheus.utils.output import emit_log_lines, detect_format

    fmt = detect_format(ctx)
    mission_id, summary = _resolve_mission(mission_id)
    if mission_id is None or summary is None:
        return ExitCode.ERROR
    events = _load_mission_events(mission_id, agent_filter=agent, level_filter=level, since=since)
    if lines:
        events = events[-lines:]
    if not events:
        return ExitCode.SUCCESS
    emit_log_lines(ctx, fmt, events, schema="prometheus.mission_log.v1")
    return ExitCode.SUCCESS


@mission.command(name="watch")
@click.argument("mission_id", required=False, default=None)
@click.option(
    "--cockpit",
    is_flag=True,
    default=False,
    help="Use the full Cockpit TUI instead of the Claude-style transcript",
)
@click.option("--agent", default=None, help="Deep-link to one agent")
@click.option("--no-thinking", is_flag=True, default=False, help="Collapse thinking streams")
@click.option(
    "--no-dissect",
    is_flag=True,
    default=False,
    help="Hide Dissect agent events (research Condition B)",
)
@click.pass_context
def mission_watch(
    ctx: click.Context,
    mission_id: str | None,
    cockpit: bool,
    agent: str | None,
    no_thinking: bool,
    no_dissect: bool,
) -> ExitCode:
    """Attach live progress to a mission.

    By default renders a Claude Code-style transcript of agent events
    from Redis in real time.  Use --cockpit for the full Textual TUI
    dashboard instead.  Press Ctrl+C to exit.
    """
    import asyncio
    import os
    import sys

    import redis.asyncio as aioredis

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    mid = mission_id or ""

    if not cockpit:
        # Claude-style transcript — default mode
        async def _run_transcript() -> None:
            redis = aioredis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=False,
            )
            try:
                from prometheus.ui.claude.transcript_consumer import watch_mission_transcript

                await watch_mission_transcript(redis, mid)
            finally:
                await redis.aclose()

        try:
            asyncio.run(_run_transcript())
        except KeyboardInterrupt:
            pass
        return ExitCode.SUCCESS

    # --cockpit: legacy Textual TUI
    from bus.consumer import ensure_consumer_group
    from bus.events import GROUP_COCKPIT, STREAM_AGENT_EVENTS
    from prometheus.ui.cockpit.app import CockpitApp
    from prometheus.ui.cockpit.trace_replay import find_trace_path, load_brief_problem

    async def _run_cockpit() -> None:
        trace_path = find_trace_path(mid) if mid else None
        problem_description = ""

        obj = ctx.ensure_object(dict)
        nc = obj.get("no_color", False)
        hc = obj.get("high_contrast", False)
        fs = obj.get("font_size")

        if trace_path:
            problem_description = load_brief_problem(mid)
            app = CockpitApp(
                redis=None,
                mission_id=mid,
                trace_path=trace_path,
                problem_description=problem_description,
                no_dissect=no_dissect,
                no_thinking=no_thinking,
                no_color=nc,
                high_contrast=hc,
                font_size=fs,
            )
            await app.run_async()
        else:
            redis = aioredis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD") or None,
                decode_responses=True,
            )
            try:
                brief_raw = await redis.get(f"job:{mid}:mission_brief") if mid else None
                if brief_raw:
                    import json

                    brief = json.loads(brief_raw)
                    problem_description = brief.get("problem_description", "")
                await ensure_consumer_group(redis, STREAM_AGENT_EVENTS, GROUP_COCKPIT, start_id="$")
                app = CockpitApp(
                    redis=redis,
                    mission_id=mid,
                    problem_description=problem_description,
                    no_dissect=no_dissect,
                    no_thinking=no_thinking,
                    no_color=nc,
                    high_contrast=hc,
                    font_size=fs,
                )
                await app.run_async()
            finally:
                await redis.aclose()

    try:
        asyncio.run(_run_cockpit())
    except KeyboardInterrupt:
        pass
    return ExitCode.SUCCESS


@mission.command(name="resume")
@click.argument("mission_id")
@click.option(
    "--watch/--no-watch",
    default=None,
    help="Launch live cockpit after resume (default: auto-detect)",
)
@click.option(
    "--from-checkpoint",
    default=None,
    help="Path to checkpoint file to resume from (default: last saved checkpoint)",
)
@click.option(
    "--force", is_flag=True, default=False, help="Resume even if mission is in a terminal phase"
)
@click.pass_context
def mission_resume(
    ctx: click.Context,
    mission_id: str,
    watch: bool | None,
    from_checkpoint: str | None,
    force: bool,
) -> ExitCode:
    """Resume an interrupted mission.

    Reads the mission's current state from Redis, validates that it is
    resumable (not in CANCELLED, MISSION_FAILED, or HARBOR_COMPLETED),
    and restarts the pipeline from the appropriate phase.

    If the mission was training (FURNACE_RUNNING, DISSECT_RUNNING,
    TRAINING_FAILED), publishes a RESUME_TRAINING event so Furnace
    restarts from the last checkpoint.  Use --from-checkpoint to
    override which checkpoint file to restore.

    If the mission was in an earlier phase (Scout, Forge), transitions
    the state back to the running version of that phase so the
    orchestrator will pick it up on its next polling cycle.

    Does NOT restart Redis or the orchestrator process.  Use
    ``prometheus daemon start`` if the orchestrator is not running.
    """
    import asyncio
    import os
    import sys

    from memory.redis_client import RedisClient
    from contracts.state import MissionState, transition_and_save, SUCCESS_PHASES
    from bus.publisher import publish
    from bus.events import RESUME_TRAINING, STREAM_DISSECT_OUTPUT
    from contracts.events import ResumeTrainingEvent
    from prometheus.ui.cockpit.trace_replay import find_trace_path

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    renderer = renderer_from_ctx(ctx)

    from prometheus.utils.slugs import uuid_to_slug

    slug = uuid_to_slug(mission_id)

    async def _run() -> ExitCode:
        redis = RedisClient()
        await redis.connect()

        try:
            state = await MissionState.load_from_redis(redis._client, mission_id)

            if state is None:
                trace_path = find_trace_path(mission_id)
                if trace_path:
                    renderer.print(f"  Mission {slug} has a trace file but no Redis state.")
                    renderer.print(f"  Trace: {trace_path}")
                    renderer.print(
                        "  Use 'prometheus mission replay' to review, or resubmit with 'prometheus mission new'."
                    )
                    return ExitCode.ERROR
                renderer.error(
                    f"Mission {slug} not found in Redis or outputs/", hint="prometheus mission list"
                )
                return ExitCode.ERROR_NOT_FOUND

            if not force and state.is_terminal:
                renderer.print(
                    f"  Mission {slug} is in terminal phase '{state.phase}' and cannot be resumed."
                )
                renderer.print("  Use --force to override and restart from the beginning.")
                return ExitCode.ERROR

            if not force and state.phase in SUCCESS_PHASES:
                renderer.print(
                    f"  Mission {slug} already completed successfully (phase: {state.phase})."
                )
                renderer.print("  Use --force to restart anyway.")
                return ExitCode.ERROR

            phase = state.phase

            if from_checkpoint and not os.path.isfile(from_checkpoint):
                renderer.error(f"Checkpoint file not found: {from_checkpoint}")
                return ExitCode.ERROR_NOT_FOUND

            training_phases = {"FURNACE_RUNNING", "DISSECT_RUNNING", "TRAINING_FAILED"}
            pre_training_phases = {
                "MISSION_CREATED",
                "SCOUT_RUNNING",
                "SCOUT_COMPLETED",
                "FORGE_RUNNING",
                "FORGE_COMPLETED",
            }

            if phase in training_phases or force:
                resolved_checkpoint = from_checkpoint or state.best_checkpoint or ""
                checkpoint_label = resolved_checkpoint or "epoch 0"

                patch_id = str(__import__("uuid").uuid4())
                await publish(
                    redis._client,
                    STREAM_DISSECT_OUTPUT,
                    RESUME_TRAINING,
                    ResumeTrainingEvent(
                        job_id=mission_id,
                        patched_script_path=state.script_path or "",
                        resume_from_checkpoint=resolved_checkpoint,
                        patch_id=patch_id,
                    ),
                )
                await transition_and_save(
                    redis._client,
                    mission_id,
                    "FURNACE_RUNNING",
                    agent="CLI",
                    message=f"Resumed by user (checkpoint: {resolved_checkpoint or 'none'})",
                )
                renderer.print(f"  Resuming {slug}")
                renderer.print(f"  last checkpoint: {phase}, {checkpoint_label}")
                renderer.print("  \u2192 resuming from next phase")

            elif phase in pre_training_phases:
                target = phase.replace("_COMPLETED", "_RUNNING") if "_COMPLETED" in phase else phase
                if target == "MISSION_CREATED":
                    target = "SCOUT_RUNNING"
                await transition_and_save(
                    redis._client,
                    mission_id,
                    target,
                    agent="CLI",
                    message=f"Resumed by user \u2014 reverting to {target}",
                )
                renderer.print(f"  Resuming {slug}")
                renderer.print(f"  resetting phase {phase} to {target}")

            else:
                renderer.print(f"  No automatic resume path for phase '{phase}'.")
                renderer.print(
                    "  You can: reset with --force, or check 'prometheus mission status'"
                )
                return ExitCode.SUCCESS

        finally:
            await redis.close()

        return ExitCode.SUCCESS

    try:
        result = asyncio.run(_run())
    except KeyboardInterrupt:
        renderer.print("\nCancelled.")
        result = ExitCode.ERROR

    if watch is True and result == ExitCode.SUCCESS:
        obj = ctx.ensure_object(dict)
        from prometheus.ui.cockpit.trace_replay import load_brief_problem

        problem_description = load_brief_problem(mission_id)
        _launch_cockpit(
            mission_id,
            problem_description,
            no_color=obj.get("no_color", False),
            high_contrast=obj.get("high_contrast", False),
            font_size=obj.get("font_size"),
        )
    elif watch is None and sys.stdout.isatty() and result == ExitCode.SUCCESS:
        from prometheus.utils.slugs import uuid_to_slug

        slug = uuid_to_slug(mission_id)
        renderer.print(f"  Reattach: prometheus mission watch {slug}")
    return result


@mission.command(name="cancel")
@click.argument("mission_id")
@click.option("--force", is_flag=True, default=False, help="Skip confirmation")
@click.option("--reason", default=None, help="Recorded in audit trail")
@click.pass_context
def mission_cancel(
    ctx: click.Context, mission_id: str, force: bool, reason: str | None
) -> ExitCode:
    """Cancel a running mission.

    Stops the training container (if one is running), transitions the
    mission state to CANCELLED, and records the cancellation in the
    timeline.  Published a JOB_FAILED event so the frontend and any
    downstream consumers know the mission was terminated.

    Use --reason to attach a human-readable explanation for the audit trail.
    Use --force to skip the confirmation prompt.
    """
    import asyncio
    import sys

    from memory.redis_client import RedisClient
    from contracts.state import MissionState, transition_and_save
    from bus.publisher import publish
    from bus.events import JOB_FAILED, STREAM_ORCHESTRATOR_OUT
    from contracts.events import JobFailedEvent
    from training.docker_manager import DockerManager

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    renderer = renderer_from_ctx(ctx)

    from prometheus.utils.slugs import uuid_to_slug

    slug = uuid_to_slug(mission_id)

    async def _run() -> ExitCode:
        redis = RedisClient()
        await redis.connect()

        try:
            state = await MissionState.load_from_redis(redis._client, mission_id)

            if state is None:
                renderer.error(
                    f"Mission {slug} not found in Redis. The mission may have expired (TTL 24h) or was never created. Use `prometheus mission list` to see active missions."
                )
                return ExitCode.ERROR_NOT_FOUND

            if not force and state.is_terminal:
                renderer.print(
                    f"  Mission {slug} is already in terminal phase '{state.phase}'. Nothing to cancel."
                )
                return ExitCode.SUCCESS

            if not force:
                phase_info = f"{state.phase} is active" if state.phase else "active"
                renderer.print(f"  Cancel {slug}? {phase_info}. [y/N]")
                try:
                    click.confirm("  ", abort=True)
                except click.Abort:
                    renderer.print("  Cancelled.")
                    return ExitCode.SUCCESS

            docker = DockerManager()
            try:
                await docker.kill_container(mission_id)
                renderer.print("  Training container stopped.")
            except Exception as exc:
                renderer.print(
                    f"  No training container to stop (or container already exited): {exc}"
                )

            audit_reason = reason or "Cancelled by user via CLI"
            await transition_and_save(
                redis._client,
                mission_id,
                "CANCELLED",
                agent="CLI",
                message=audit_reason,
            )

            await publish(
                redis._client,
                STREAM_ORCHESTRATOR_OUT,
                JOB_FAILED,
                JobFailedEvent(
                    job_id=mission_id,
                    source_agent="CLI",
                    reason=audit_reason,
                    diagnostic_report_path=f"outputs/{mission_id}/diagnostic_report_{mission_id}.json",
                ),
            )

            renderer.print(f"  Mission {slug} cancelled.")
            if reason:
                renderer.print(f"  Reason: {reason}")

        finally:
            await redis.close()

        return ExitCode.SUCCESS

    try:
        return asyncio.run(_run())
    except KeyboardInterrupt:
        renderer.print("\nCancelled.")
        return ExitCode.ERROR


@mission.command(name="report")
@click.argument("mission_id")
@click.option(
    "--open",
    "open_report",
    is_flag=True,
    default=False,
    help="Open report in browser after generation",
)
@click.option(
    "--to", "to_path", default=None, help="Output path for the report file (default: stdout)"
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json", "markdown"]),
    default="text",
    help="Output format (default: text)",
)
@click.pass_context
def mission_report(
    ctx: click.Context, mission_id: str, open_report: bool, to_path: str | None, output_format: str
) -> ExitCode:
    """Render a complete mission report.

    Reads the mission trace file, evaluation report, and companion
    mission_brief from outputs/{mission_id}/ and produces a structured
    summary of what happened from submission through to completion or
    escalation.

    Default output is a human-readable text summary to stdout.
    Use --format=json for structured JSON output.
    Use --format=markdown for a Markdown document.
    Use --to=FILE to write the report to a file instead of stdout.
    Use --open to open the report in the default browser.
    """
    renderer = renderer_from_ctx(ctx)
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from prometheus.ui.cockpit.trace_replay import find_trace_path, find_brief_path

    trace_path = find_trace_path(mission_id)
    if not trace_path:
        renderer.error(
            f"No trace file found for mission '{mission_id}'",
            hint="outputs/{mission_id}/trace.jsonl",
        )
        return ExitCode.ERROR_NOT_FOUND

    # ── Read trace events ───────────────────────────────────────────
    events: list[dict] = []
    try:
        with open(trace_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        renderer.error(
            f"Corrupted trace file {trace_path}: {exc}. The mission trace may be incomplete. Run `prometheus mission watch {mission_id}` to capture a fresh trace."
        )
        return ExitCode.ERROR

    if not events:
        renderer.error(
            f"Trace file for '{mission_id}' is empty. The mission may still be in progress or no events were recorded yet. Run `prometheus mission status {mission_id}` to check."
        )
        return ExitCode.ERROR

    # ── Read companion brief ────────────────────────────────────────
    brief: dict = {}
    brief_path = find_brief_path(mission_id)
    if brief_path:
        try:
            with open(brief_path, encoding="utf-8") as f:
                brief = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # ── Read eval report ────────────────────────────────────────────
    eval_report: dict = {}
    eval_path = Path("outputs") / mission_id / f"eval_report_{mission_id}.json"
    if eval_path.exists():
        try:
            with open(eval_path, encoding="utf-8") as f:
                eval_report = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # ── Read patch history (Dissect repairs recorded for this job) ──
    patches = _load_patch_history(mission_id)

    # ── Compute summary from events ────────────────────────────────
    agents_seen: list[str] = []
    last_event = events[-1]
    for ev in events:
        agent = ev.get("agent", "")
        if agent and agent not in agents_seen:
            agents_seen.append(agent)

    summary = {
        "mission_id": mission_id,
        "problem_description": brief.get("problem_description", last_event.get("summary", "")),
        "task_type": brief.get("task_type", ""),
        "modality": brief.get("modality", ""),
        "total_events": len(events),
        "agents_involved": agents_seen,
        "last_agent": last_event.get("agent", ""),
        "last_state": last_event.get("state", ""),
        "last_summary": last_event.get("summary", ""),
        "last_timestamp": (
            last_event.get("timestamp", "")[:19] if last_event.get("timestamp") else ""
        ),
        "is_complete": last_event.get("state") in ("done", "error"),
    }

    # Evaluation data
    if eval_report:
        metrics = eval_report.get("metrics", {})
        decision = eval_report.get("decision", "unknown")
        summary["evaluation"] = {
            "decision": decision,
            "primary_metric": eval_report.get("primary_metric", ""),
            "primary_value": eval_report.get("primary_metric_value", 0),
            "all_metrics": metrics,
            "reason": eval_report.get("reason", ""),
        }

    # Dataset info
    ds = brief.get("dataset", {})
    if ds:
        summary["dataset"] = {
            "file_path": ds.get("file_path", ""),
            "num_rows": ds.get("num_rows"),
            "num_columns": ds.get("num_columns"),
        }

    # Patch history (Dissect repairs)
    if patches:
        summary["patches"] = patches

    # ── Output ──────────────────────────────────────────────────────
    if output_format == "json":
        output = json.dumps(summary, indent=2, default=str)
    elif output_format == "markdown":
        output = _render_report_markdown(summary)
    else:
        output = _render_report_text(summary)

    if to_path:
        out_dir = os.path.dirname(to_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(to_path, "w", encoding="utf-8") as f:
            f.write(output)
        click.echo(f"Report written to {to_path}")
    else:
        click.echo(output)

    if open_report:
        report_path = to_path or str(
            Path("outputs") / mission_id / f"mission_report_{mission_id}.md"
        )
        if not os.path.isfile(report_path):
            md = _render_report_markdown(summary)
            os.makedirs(os.path.dirname(report_path), exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(md)
        try:
            if sys.platform == "win32":
                os.startfile(report_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", report_path], check=True)
            else:
                subprocess.run(["xdg-open", report_path], check=True)
        except Exception as exc:
            renderer.error(f"Could not open report: {exc}")

    return ExitCode.SUCCESS


def _load_patch_history(job_id: str) -> list[dict]:
    """Read research/patch_log.jsonl and return entries matching this job_id."""
    import json
    from pathlib import Path

    log_path = Path("research") / "patch_log.jsonl"
    if not log_path.exists():
        return []

    entries = []
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("job_id") == job_id or entry.get("job_id") == job_id[:8]:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass

    return entries


@mission.command(name="replay")
@click.argument("mission_id")
@click.option(
    "--speed",
    type=click.Choice(["realtime", "fast", "manual"]),
    default="manual",
    help="Playback speed: manual (step-by-step), fast (0.05s delay), realtime (timestamp-based delay)",
)
@click.option("--agent", default=None, help="Filter to one agent's events (e.g. --agent=Scout)")
@click.option(
    "--from",
    "from_seq",
    default=None,
    type=int,
    help="Start at event index N (0-based, skips earlier events)",
)
@click.pass_context
def mission_replay(
    ctx: click.Context, mission_id: str, speed: str, agent: str | None, from_seq: int | None
) -> None:
    """Step through a finished mission's event trace.

    Opens the Mission Cockpit in replay mode — starts paused by default
    so you can step through events manually.  Keyboard controls:

      Space   — toggle play/pause
      → / j   — step forward one event
      ← / k   — step backward one event
      G       — go to a specific event number
      Q       — quit
    """
    import asyncio
    import sys
    from prometheus.ui.cockpit.app import CockpitApp
    from prometheus.ui.cockpit.trace_replay import find_trace_path, load_brief_problem

    renderer = renderer_from_ctx(ctx)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def _run() -> None:
        trace_path = find_trace_path(mission_id)
        if not trace_path:
            renderer.error(
                f"No trace file found for mission '{mission_id}'",
                hint="outputs/{mission_id}/trace.jsonl",
            )
            return

        problem_description = load_brief_problem(mission_id)

        raw_events: list[dict] = []
        try:
            with open(trace_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        import json

                        raw_events.append(json.loads(line))
        except (FileNotFoundError, json.JSONDecodeError):
            renderer.error(
                f"Corrupted trace file {trace_path}. The mission replay file may be incomplete. Try re-running the mission or check the file manually."
            )
            return

        if agent:
            agent_lower = agent.lower()
            filtered = [e for e in raw_events if (e.get("agent") or "").lower() == agent_lower]
            if not filtered:
                renderer.error(
                    f"No events found for agent '{agent}'. Check the agent name — valid agents: Scout, Forge, Furnace, Dissect, Arbiter, Harbor."
                )
                return
            raw_events = filtered

        if from_seq is not None:
            if from_seq < 0 or from_seq >= len(raw_events):
                renderer.error(f"--from {from_seq} out of range (0..{len(raw_events) - 1})")
                return
            raw_events = raw_events[from_seq:]

        obj = ctx.ensure_object(dict)
        nc = obj.get("no_color", False)
        hc = obj.get("high_contrast", False)
        fs = obj.get("font_size")
        app = CockpitApp(
            redis=None,
            mission_id=mission_id,
            trace_path=trace_path,
            trace_events=raw_events,
            problem_description=problem_description,
            start_paused=(speed == "manual"),
            speed=speed,
            no_color=nc,
            high_contrast=hc,
            font_size=fs,
        )
        await app.run_async()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


# ── Data helpers ────────────────────────────────────────────────────────────


def _load_mission_summaries(
    filter_status: str | None = None,
    limit: int | None = None,
) -> list[list[str]]:
    """Scan outputs/ for trace files and return summary rows."""
    from pathlib import Path

    from prometheus.utils.slugs import uuid_to_slug

    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        return []

    rows: list[list[str]] = []
    for child in sorted(outputs_dir.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        trace_file = child / "trace.jsonl"
        if not trace_file.exists():
            continue
        events = _read_trace_file(trace_file)
        if not events:
            continue
        last = events[-1]
        mission_id = last.get("mission_id") or last.get("job_id") or child.name
        slug = uuid_to_slug(mission_id)
        problem = last.get("problem") or last.get("summary", "")
        phase = last.get("phase") or last.get("state", "")
        agent = last.get("agent", "")

        if agent and phase:
            status = f"{agent} {phase}"
        elif phase:
            status = phase
        else:
            status = agent
        started = last.get("timestamp", "")[:19] if last.get("timestamp") else ""
        if filter_status and filter_status.lower() not in status.lower():
            continue
        rows.append([slug[:20], problem[:40], agent or "", phase or "", started[:16]])

    if limit:
        rows = rows[:limit]
    return rows


def _resolve_mission(
    mission_id: str | None,
) -> tuple[str | None, dict | None]:
    """Resolve mission_id (latest if None) and return its summary dict.

    Prefers the on-disk trace file (richer event data).  Falls back to
    Redis ``job:{id}:mission_state`` when the trace file hasn't been
    written yet (e.g. freshly submitted jobs).
    """
    if mission_id is None:
        mission_id = _latest_mission_id()
        if mission_id is None:
            from prometheus.ui.renderers import renderer_from_ctx
            import click as _click

            r = renderer_from_ctx(_click.get_current_context())
            r.error("No missions found. Run a mission first.", title="No data")
            return None, None

    from prometheus.utils.slugs import uuid_to_slug

    slug = uuid_to_slug(mission_id)

    trace_file = _find_trace_file(mission_id)
    if trace_file:
        events = _read_trace_file(trace_file)
        if events:
            last = events[-1]
            return mission_id, {
                "mission_id": mission_id,
                "slug": slug,
                "agent": last.get("agent", ""),
                "phase": last.get("phase", "") or last.get("state", ""),
                "event": last.get("event", "") or last.get("summary", ""),
                "status": f"{last.get('agent', '')} {last.get('phase', '') or last.get('state', '')}".strip(),
                "timestamp": last.get("timestamp", ""),
                "_source": "trace",
            }

    # Fallback: read from Redis
    return _redis_mission_summary(mission_id, slug)


def _redis_mission_summary(
    mission_id: str,
    slug: str,
) -> tuple[str, dict]:
    """Build a summary dict from Redis state (no trace file needed)."""
    try:
        import asyncio
        from contracts.state import MissionState
        from memory.redis_client import RedisClient

        async def _load() -> dict:
            c = RedisClient()
            await c.connect()
            state = await MissionState.load_from_redis(c._client, mission_id)
            await c.close()

            phase = state.phase if state else "unknown"
            agent = ""
            ts = ""
            if state and state.timeline:
                last = state.timeline[-1]
                agent = last.agent or ""
                ts = last.timestamp or ""

            return {
                "mission_id": mission_id,
                "slug": slug,
                "agent": agent,
                "phase": phase,
                "event": "",
                "status": f"{agent} {phase}".strip(),
                "timestamp": ts,
                "_source": "redis",
            }

        summary = asyncio.run(_load())
        return mission_id, summary
    except Exception:
        return mission_id, {
            "mission_id": mission_id,
            "slug": slug,
            "phase": "unknown",
            "status": "no trace",
            "agent": "",
            "event": "",
            "timestamp": "",
            "_source": "fallback",
        }


def _load_mission_events(
    mission_id: str,
    agent_filter: str | None = None,
    level_filter: str | None = None,
    since: str | None = None,
) -> list[dict]:
    trace_file = _find_trace_file(mission_id)
    if trace_file is None:
        return []
    events = _read_trace_file(trace_file)
    filtered = events
    if agent_filter:
        filtered = [
            e for e in filtered if agent_filter.lower() in (e.get("agent", "") or "").lower()
        ]
    if level_filter:
        filtered = [
            e for e in filtered if level_filter.lower() in (e.get("state", "") or "").lower()
        ]
    if since:
        filtered = [e for e in filtered if (e.get("timestamp") or "") >= since]
    return filtered


def _latest_mission_id() -> str | None:
    from pathlib import Path

    # Check on-disk traces first
    outputs_dir = Path("outputs")
    if outputs_dir.exists():
        for child in sorted(outputs_dir.iterdir(), reverse=True):
            if child.is_dir() and (child / "trace.jsonl").exists():
                return child.name

    # Fallback: check Redis for the most recent job
    try:
        import asyncio
        from memory.redis_client import RedisClient

        async def _get_latest() -> str | None:
            c = RedisClient()
            await c.connect()
            keys = await c._client.keys("job:*:meta")
            await c.close()
            if not keys:
                return None
            ids = []
            for k in keys:
                mid = k.replace("job:", "").replace(":meta", "")
                ids.append(mid)
            ids.sort(reverse=True)
            return ids[0] if ids else None

        return asyncio.run(_get_latest())
    except Exception:
        return None


def _find_trace_file(mission_id: str) -> str | None:
    from pathlib import Path

    candidates = [
        Path("outputs") / mission_id / "trace.jsonl",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _read_trace_file(path: str | Path) -> list[dict]:
    import json

    events: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return events


# ── Report render helpers ──────────────────────────────────────────────


def _render_report_text(summary: dict) -> str:
    """Render a mission summary as human-readable text."""
    lines: list[str] = []
    lines.append(f"Mission: {summary['mission_id'][:24]}")
    lines.append(f"  Problem: {summary.get('problem_description', 'N/A')[:80]}")
    lines.append(
        f"  Task type: {summary.get('task_type', '?')}  |  Modality: {summary.get('modality', '?')}"
    )
    lines.append(
        f"  Total events: {summary['total_events']}  |  Agents: {', '.join(summary['agents_involved'])}"
    )
    ds = summary.get("dataset", {})
    if ds:
        lines.append(
            f"  Dataset: {ds.get('file_path', '?')} ({ds.get('num_rows', '?')} rows, {ds.get('num_columns', '?')} cols)"
        )
    lines.append(
        f"  Last event: {summary['last_agent']} — {summary['last_state']} — {summary.get('last_summary', '')[:80]}"
    )
    if summary.get("last_timestamp"):
        lines.append(f"  At: {summary['last_timestamp']}")
    lines.append(f"  Complete: {'Yes' if summary.get('is_complete') else 'No'}")

    eval_data = summary.get("evaluation", {})
    if eval_data:
        lines.append("")
        lines.append("  Evaluation:")
        lines.append(f"    Decision: {eval_data.get('decision', '?')}")
        lines.append(
            f"    Primary metric: {eval_data.get('primary_metric', '?')} = {eval_data.get('primary_value', '?')}"
        )
        if eval_data.get("reason"):
            lines.append(f"    Reason: {eval_data['reason'][:120]}")
        metrics = eval_data.get("all_metrics", {})
        if metrics:
            items = [f"{k}={v}" for k, v in metrics.items() if k != "primary_metric"]
            if items:
                lines.append(f"    All metrics: {', '.join(items)}")

    lines.append("")
    return "\n".join(lines)


def _render_report_markdown(summary: dict) -> str:
    """Render a mission summary as Markdown."""
    lines: list[str] = []
    mid = summary["mission_id"][:24]
    lines.append(f"# Mission Report — `{mid}`")
    lines.append("")

    header = f"### {summary.get('problem_description', 'N/A')[:80]}"
    lines.append(header)
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|-------|-------|")
    lines.append(f"| Mission ID | `{summary['mission_id']}` |")
    lines.append(f"| Task Type | {summary.get('task_type', '?')} |")
    lines.append(f"| Modality | {summary.get('modality', '?')} |")
    lines.append(f"| Events | {summary['total_events']} |")
    lines.append(f"| Agents | {', '.join(summary['agents_involved'])} |")
    lines.append(f"| Status | {summary['last_state']} by {summary['last_agent']} |")
    if summary.get("last_timestamp"):
        lines.append(f"| Last activity | {summary['last_timestamp']} |")
    lines.append(f"| Complete | {'Yes' if summary.get('is_complete') else 'No'} |")
    ds = summary.get("dataset", {})
    if ds:
        lines.append(f"| Dataset | {ds.get('file_path', '?')} |")
        lines.append(f"| Rows | {ds.get('num_rows', '?')} |")
        lines.append(f"| Columns | {ds.get('num_columns', '?')} |")
    lines.append("")

    eval_data = summary.get("evaluation", {})
    if eval_data:
        lines.append("## Evaluation")
        lines.append("")
        lines.append(f"**Decision:** {eval_data.get('decision', '?')}")
        lines.append("")
        lines.append(
            f"**Primary metric:** {eval_data.get('primary_metric', '?')} = {eval_data.get('primary_value', '?')}"
        )
        lines.append("")
        metrics = eval_data.get("all_metrics", {})
        if metrics:
            lines.append("| Metric | Value |")
            lines.append("|--------|-------|")
            for k, v in metrics.items():
                if k != "primary_metric":
                    lines.append(f"| {k} | {v} |")
            lines.append("")
        if eval_data.get("reason"):
            lines.append(f"**Reason:** {eval_data['reason']}")
            lines.append("")

    lines.append("---")
    lines.append("*Generated by `prometheus mission report`*")
    lines.append("")
    return "\n".join(lines)

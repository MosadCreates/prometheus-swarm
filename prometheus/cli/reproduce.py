"""Reproducibility CLI — inspect reproducibility context for any job."""

from __future__ import annotations

import asyncio
import json

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


@click.group(
    cls=AliasedGroup,
    name="reproduce",
    aliases={"repro": "reproduce"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def reproduce():
    """Inspect reproducibility context for any job."""


@reproduce.command(name="inspect")
@click.argument("job_id")
@click.option("--verbose", "-v", is_flag=True, help="Show dependency and agent versions")
@click.pass_context
def reproduce_inspect(ctx, job_id, verbose):
    """Show the full reproducibility context for a job.

    Displays git commit, configuration hash, Python version,
    dataset fingerprint, and timestamps that make the job reproducible.
    """
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                raw = await redis._client.get_str(f"job:{job_id}:reproducibility")
                return raw
            finally:
                await redis.close()
        except ImportError:
            return None

    raw = asyncio.run(_fetch())
    if not raw:
        renderer.error(
            f"No reproducibility context found for job '{job_id[:8]}'.",
            title="Not found",
        )
        return ExitCode.ERROR_NOT_FOUND

    try:
        rc = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        renderer.error("Invalid reproducibility context format.", title="Parse error")
        return ExitCode.ERROR

    renderer.print(
        f"\n  [bold]Reproducibility Context[/]  [dim]v{rc.get('reproducibility_version', '?')}[/]"
    )
    renderer.print(f"  [bold]Job:[/]  {rc.get('job_id', job_id)[:8]}")
    renderer.print()

    # Git
    git_hash = rc.get("git_commit", "")
    git_branch = rc.get("git_branch", "")
    dirty = rc.get("has_uncommitted_changes", False)
    dirty_mark = " [red]DIRTY[/]" if dirty else " [green]CLEAN[/]"
    renderer.print(
        f"  [bold]Git Commit:[/]  {git_hash[:12] if git_hash else '[dim]none[/]'}{dirty_mark}"
    )
    if git_branch:
        renderer.print(f"  [bold]Branch:[/]     {git_branch}")

    # Configuration
    config_hash = rc.get("configuration_hash", "")
    if config_hash:
        renderer.print(f"  [bold]Config Hash:[/] {config_hash}")

    # Python
    py_ver = rc.get("python_version", "?")
    renderer.print(f"  [bold]Python:[/]      {py_ver}")

    # Versions
    renderer.print("  [bold]Versions:[/]")
    renderer.print(f"    MissionSpec:  {rc.get('mission_spec_version', '?')}")
    renderer.print(f"    ExecutionPlan: {rc.get('execution_plan_version', '?')}")
    renderer.print(f"    Planner:      {rc.get('planner_version', '?')}")

    # Dataset fingerprint
    ds_fp = rc.get("dataset_fingerprint", {})
    if ds_fp.get("exists"):
        content_hash = ds_fp.get("content_hash", "")
        size_bytes = ds_fp.get("size_bytes", 0)
        size_mb = size_bytes / (1024 * 1024)
        renderer.print("  [bold]Dataset:[/]")
        renderer.print(f"    Path:    {ds_fp.get('file_path', '?')}")
        renderer.print(f"    Size:    {size_mb:.1f} MB")
        renderer.print(f"    Fingerprint: {content_hash}")
    else:
        renderer.print("  [bold]Dataset:[/]  [dim]not available[/]")

    # Agent versions
    agent_vers = rc.get("agent_versions", {})
    if agent_vers and verbose:
        renderer.print("\n  [bold]Agent Versions:[/]")
        for name, ver in sorted(agent_vers.items()):
            renderer.print(f"    {name:<10}  {ver}")

    # Dependencies
    deps = rc.get("dependency_versions", {})
    if deps and verbose:
        renderer.print(f"\n  [bold]Dependencies ({len(deps)}):[/]")
        for pkg, ver in sorted(deps.items()):
            renderer.print(f"    {pkg:<20}  {ver}")

    # Timestamp
    created = rc.get("created_at", "")
    if created:
        renderer.print(f"\n  [bold]Recorded:[/]  {created}")

    renderer.print()
    return ExitCode.SUCCESS

"""Planner CLI — inspect, validate, and dry-run ExecutionPlans."""

from __future__ import annotations

import asyncio
import json

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.components import Spinner
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="planner",
    aliases={"plan": "planner"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def planner():
    """Plan execution strategy for ML jobs."""


@planner.command(name="inspect")
@click.argument("job_id")
@click.option("--verbose", "-v", is_flag=True, help="Show full plan details")
@click.pass_context
def planner_inspect(ctx, job_id, verbose):
    """Show the ExecutionPlan for a job."""
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                raw = await redis._client.get_str(f"job:{job_id}:execution_plan")
                return raw
            finally:
                await redis.close()
        except ImportError:
            return None

    raw = asyncio.run(_fetch())
    if not raw:
        renderer.error(f"No ExecutionPlan found for job '{job_id[:8]}'.", title="Not found")
        return ExitCode.ERROR_NOT_FOUND

    try:
        plan = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        renderer.error("Invalid ExecutionPlan format.", title="Parse error")
        return ExitCode.ERROR

    renderer.print(
        f"\n  [bold]ExecutionPlan[/]  [dim]v{plan.get('execution_plan_version', '?')}[/]"
    )
    renderer.print(f"  [bold]Plan ID:[/]  {plan.get('plan_id', '?')[:8]}")
    renderer.print(f"  [bold]Job ID:[/]  {plan.get('job_id', job_id)[:8]}")
    renderer.print()

    # Confidence
    conf = plan.get("confidence", {})
    score = conf.get("score", 0)
    assessment = conf.get("assessment", "unknown")
    color = "green" if score >= 0.85 else ("yellow" if score >= 0.60 else "red")
    renderer.print(f"  [bold]Confidence:[/]  [{color}]{score:.2f}[/] ({assessment})")

    # Resource budget
    budget = plan.get("resource_budget", {})
    reqs = budget.get("requirements", {})
    est = budget.get("estimates", {})
    renderer.print("  [bold]Budget:[/]")
    renderer.print(f"    GPU: {'Yes' if reqs.get('gpu_required') else 'No'}")
    renderer.print(f"    RAM: ~{est.get('estimated_ram_mb', '?')} MB")
    renderer.print(f"    Duration: ~{est.get('estimated_duration_minutes', '?')} min")
    renderer.print(f"    Cost hint: {budget.get('cost_optimization_hint', '?')}")

    # Retry policy
    retry = plan.get("retry_policy", {})
    renderer.print(f"  [bold]Retry:[/]  max={retry.get('max_attempts', 3)}")
    fallback = retry.get("fallback_models", [])
    if fallback:
        renderer.print(f"    Fallback models: {', '.join(fallback)}")

    # Critical path
    crit = plan.get("critical_path", [])
    if crit:
        renderer.print(f"  [bold]Critical Path:[/]  {' → '.join(crit)}")
    renderer.print(f"  [bold]Estimated total:[/]  ~{plan.get('estimated_total_minutes', '?')} min")

    # Nodes
    nodes = plan.get("nodes", {})
    renderer.print(f"\n  [bold]DAG Nodes:[/]  {len(nodes)}")
    if verbose:
        for nid, node in nodes.items():
            deps = node.get("depends_on", [])
            dep_str = f"  dep: {', '.join(deps)}" if deps else ""
            cond = node.get("condition", "")
            cond_str = f"  cond: {cond}" if cond else ""
            renderer.print(f"    {nid:<25} [{node.get('agent', '?'):>8}] {dep_str}{cond_str}")

    # Plan state
    state = asyncio.run(_fetch_plan_state(job_id))
    if state:
        renderer.print("\n  [bold]Task States:[/]")
        for task_id, status in sorted(state.items()):
            color_map = {
                "completed": "green",
                "ready": "cyan",
                "running": "yellow",
                "pending": "dim",
                "failed": "red",
            }
            c = color_map.get(status, "dim")
            renderer.print(f"    [{c}]{task_id:<25} {status}[/]")

    renderer.print()
    return ExitCode.SUCCESS


@planner.command(name="dry-run")
@click.argument("job_id")
@click.pass_context
def planner_dry_run(ctx, job_id):
    """Compile a MissionSpecification into a plan and validate it (no execution)."""
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                raw = await redis._client.get_str(f"job:{job_id}:mission_spec")
                return raw
            finally:
                await redis.close()
        except ImportError:
            return None

    with Spinner("Compiling plan..."):
        raw = asyncio.run(_fetch())

    if not raw:
        renderer.error(
            f"No MissionSpecification found for job '{job_id[:8]}'.",
            title="Not found",
        )
        return ExitCode.ERROR_NOT_FOUND

    try:
        spec = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        renderer.error("Invalid MissionSpecification format.", title="Parse error")
        return ExitCode.ERROR

    from prometheus.planner.compiler import compile_plan
    from prometheus.planner.validators import validate_plan

    plan = compile_plan(spec, job_id)
    errors = validate_plan(plan)

    renderer.print(f"\n  [bold]Dry Run:[/]  {plan.plan_id[:8]}")

    # Summary
    renderer.print(f"  Nodes: {len(plan.nodes)}")
    renderer.print(f"  Edges: {len(plan.edges)}")
    renderer.print(f"  Confidence: {plan.confidence.score:.2f} ({plan.confidence.assessment})")
    renderer.print(f"  Estimated: ~{plan.estimated_total_minutes} min")

    # Critical path
    if plan.critical_path:
        renderer.print(f"  Critical Path: {' → '.join(plan.critical_path)}")

    # Resource budget
    reqs = plan.resource_budget.requirements
    est = plan.resource_budget.estimates
    renderer.print(
        f"  Requirements: GPU={'Yes' if reqs.gpu_required else 'No'}, RAM={reqs.min_ram_mb}MB"
    )
    renderer.print(
        f"  Estimates: {est.estimated_duration_minutes}min, {est.estimated_ram_mb}MB RAM"
    )

    # Retry policy
    renderer.print(
        f"  Retry: max={plan.retry_policy.max_attempts}, fallback={plan.retry_policy.fallback_models}"
    )

    # Validation
    if errors:
        renderer.print(f"\n  [bold red]Validation Errors ({len(errors)}):[/]")
        for err in errors:
            renderer.print(f"    [red]✗[/] {err}")
        return ExitCode.ERROR
    else:
        renderer.print("\n  [green]✓ Plan valid (all 5 checks passed)[/]")

    renderer.print()
    return ExitCode.SUCCESS


@planner.command(name="validate")
@click.argument("job_id")
@click.pass_context
def planner_validate(ctx, job_id):
    """Run all 5 validators on an existing ExecutionPlan."""
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                raw = await redis._client.get_str(f"job:{job_id}:execution_plan")
                return raw
            finally:
                await redis.close()
        except ImportError:
            return None

    raw = asyncio.run(_fetch())
    if not raw:
        renderer.error(
            f"No ExecutionPlan found for job '{job_id[:8]}'.",
            title="Not found",
        )
        return ExitCode.ERROR_NOT_FOUND

    try:
        plan_dict = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        renderer.error("Invalid ExecutionPlan format.", title="Parse error")
        return ExitCode.ERROR

    from prometheus.planner.models import ExecutionPlan
    from prometheus.planner.validators import validate_plan

    plan = ExecutionPlan(**plan_dict)
    errors = validate_plan(plan)

    validator_names = [
        "dag_cycles",
        "missing_task_refs",
        "unreachable_nodes",
        "conditions_covered",
        "terminals",
    ]

    renderer.print(f"\n  [bold]Validator Results[/]  [dim]plan {plan.plan_id[:8]}[/]")
    renderer.print()

    for name in validator_names:
        relevant = [e for e in errors if name in e.lower()]
        if not relevant:
            renderer.print(f"  [green]✓ {name}[/]")
        else:
            for err in relevant:
                renderer.print(f"  [red]✗ {err}[/]")

    if errors:
        renderer.print(f"\n  [red]{len(errors)} error(s) found[/]")
        return ExitCode.ERROR

    renderer.print("\n  [green]All 5 validators passed[/]")
    return ExitCode.SUCCESS


@planner.command(name="stats")
@click.pass_context
def planner_stats(ctx):
    """Show aggregate execution statistics per architecture."""
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                from learning.planner_feedback import get_execution_stats

                raw = await redis._client.get_str("prometheus:execution_stats")
                if raw:
                    return json.loads(raw) if isinstance(raw, str) else raw
                return await get_execution_stats(redis._client)
            finally:
                await redis.close()
        except ImportError:
            return None

    stats = asyncio.run(_fetch())
    if not stats:
        renderer.error("No execution statistics available.", title="No data")
        return ExitCode.ERROR_NOT_FOUND

    renderer.print("\n  [bold]Execution Statistics[/]  [dim]per architecture[/]")
    renderer.print()
    for arch, s in sorted(stats.items()):
        pct = s.get("pass_rate", 0) * 100
        dur = s.get("avg_duration_min", "?")
        ram = s.get("avg_ram_mb", "?")
        err = s.get("avg_prediction_error", "?")
        renderer.print(
            f"  [bold]{arch:<12}[/]  {s['count']:>3} jobs  "
            f"[green]{pct:.0f}% pass[/]  "
            f"[yellow]{dur}m[/]  "
            f"[dim]{ram}MB[/]"
        )
        if err != "?":
            renderer.print(f"  {'':12}  prediction error: [red]{err}%[/]")
    renderer.print()
    return ExitCode.SUCCESS


@planner.command(name="explain")
@click.argument("job_id")
@click.pass_context
def planner_explain(ctx, job_id):
    """Show why the Planner estimated what it did for a job.

    Compares Planner predictions against historical evidence and
    actual execution outcome (if available).
    """
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                # Fetch plan
                plan_raw = await redis._client.get_str(f"job:{job_id}:execution_plan")
                # Fetch outcome
                outcome_raw = await redis._client.get_str(f"job:{job_id}:execution_outcome")
                # Fetch prediction error
                error_raw = await redis._client.get_str(f"job:{job_id}:prediction_error")
                # Fetch mission spec for context
                spec_raw = await redis._client.get_str(f"job:{job_id}:mission_spec")

                return {
                    "plan": json.loads(plan_raw) if plan_raw else None,
                    "outcome": json.loads(outcome_raw) if outcome_raw else None,
                    "prediction_error": json.loads(error_raw) if error_raw else None,
                    "spec": json.loads(spec_raw) if spec_raw else None,
                }
            finally:
                await redis.close()
        except ImportError:
            return {}

    data = asyncio.run(_fetch())
    plan = data.get("plan")
    if not plan:
        renderer.error(f"No ExecutionPlan found for job '{job_id[:8]}'.", title="Not found")
        return ExitCode.ERROR_NOT_FOUND

    meta = plan.get("metadata", {})
    budget = plan.get("resource_budget", {})
    reqs = budget.get("requirements", {})
    est = budget.get("estimates", {})
    conf = plan.get("confidence", {})

    renderer.print(
        f"\n  [bold]Planner Explanation[/]  [dim]job {data.get('spec', {}).get('job_id', job_id)[:8]}[/]"
    )
    renderer.print()

    # Architecture
    arch = meta.get("architecture", "?")
    modality = meta.get("modality", "?")
    num_rows = meta.get("num_rows", 0)
    renderer.print(f"  [bold]Architecture:[/]  {arch}")
    renderer.print(f"  [bold]Modality:[/]     {modality}  [dim]{num_rows} rows[/]")

    # Confidence breakdown
    renderer.print(
        f"\n  [bold]Confidence:[/]  {conf.get('score', 0):.2f} ({conf.get('assessment', '?')})"
    )
    factors = conf.get("factors", {})
    for k, v in sorted(factors.items()):
        color = "green" if v >= 0.85 else ("yellow" if v >= 0.6 else "red")
        renderer.print(f"    [{color}]{k:<25}[/] {v:.2f}")

    # Predicted vs historical vs actual
    outcome = data.get("outcome")
    pred_error = data.get("prediction_error")

    renderer.print("\n  [bold]Resource Estimates:[/]")
    pred_dur = est.get("estimated_duration_minutes", "?")
    pred_ram = est.get("estimated_ram_mb", "?")
    pred_vram = est.get("estimated_vram_mb", 0)

    if outcome:
        actual_dur_m = (
            outcome.get("duration_seconds", 0) / 60.0 if outcome.get("duration_seconds") else None
        )
        actual_ram = outcome.get("peak_ram_mb")
        actual_vram = outcome.get("peak_gpu_mb")
        actual_retries = outcome.get("retries", 0)
        actual_crashes = outcome.get("crashes", 0)

        dur_str = f"[green]{pred_dur}m[/]" if pred_dur != "?" else "[dim]?[/]"
        if actual_dur_m:
            dur_str += f"  actual: [yellow]{actual_dur_m:.0f}m[/]"
            if pred_error and "duration_error_pct" in pred_error:
                dur_str += f"  error: [red]{pred_error['duration_error_pct']}%[/]"

        ram_str = f"[green]{pred_ram}MB[/]" if pred_ram != "?" else "[dim]?[/]"
        if actual_ram:
            ram_str += f"  actual: [yellow]{actual_ram:.0f}MB[/]"
            if pred_error and "ram_error_pct" in pred_error:
                ram_str += f"  error: [red]{pred_error['ram_error_pct']}%[/]"

        renderer.print(f"    Duration:    {dur_str}")
        renderer.print(f"    RAM:         {ram_str}")
        if pred_vram or actual_vram:
            renderer.print(f"    VRAM:        {pred_vram}MB  actual: {actual_vram or '?'}MB")
        renderer.print(f"    GPU:         {'Yes' if reqs.get('gpu_required') else 'No'}")
        renderer.print(f"    Retries:     [yellow]{actual_retries}[/]")
        renderer.print(
            f"    Crashes:     {'[red]' if actual_crashes > 0 else '[green]'}{actual_crashes}[/]"
        )
        renderer.print(f"    Outcome:     [bold]{outcome.get('outcome_label', '?')}[/]")
        if outcome.get("final_metric") is not None:
            renderer.print(f"    Final metric: {outcome['final_metric']:.4f}")
    else:
        renderer.print(f"    Duration:    [green]{pred_dur}m[/]")
        renderer.print(f"    RAM:         [green]{pred_ram}MB[/]")
        if pred_vram:
            renderer.print(f"    VRAM:        {pred_vram}MB")
        renderer.print(f"    GPU:         {'Yes' if reqs.get('gpu_required') else 'No'}")
        renderer.print("    [dim](no execution outcome yet)[/]")

    # Retry policy
    retry = plan.get("retry_policy", {})
    renderer.print(f"\n  [bold]Retry:[/]  max={retry.get('max_attempts', 3)}")
    fallback = retry.get("fallback_models", [])
    if fallback:
        renderer.print(f"    Fallback: {', '.join(fallback)}")

    renderer.print()
    return ExitCode.SUCCESS


@planner.command(name="prediction-error")
@click.option("--arch", default=None, help="Filter by architecture")
@click.pass_context
def planner_prediction_error(ctx, arch):
    """Show prediction error history across jobs."""
    renderer = renderer_from_ctx(ctx)

    async def _fetch():
        try:
            from prometheus.core.redis import CliRedis

            redis = CliRedis()
            try:
                raw = await redis._client.get_str("prometheus:prediction_error_history")
                if raw:
                    entries = json.loads(raw) if isinstance(raw, str) else raw
                    if arch:
                        entries = [
                            e for e in entries if e.get("architecture", "").lower() == arch.lower()
                        ]
                    return entries
                return []
            finally:
                await redis.close()
        except ImportError:
            return None

    entries = asyncio.run(_fetch())
    if not entries:
        renderer.error("No prediction error history available.", title="No data")
        return ExitCode.ERROR_NOT_FOUND

    total = len(entries)
    dur_errors = [e["duration_error_pct"] for e in entries if "duration_error_pct" in e]
    ram_errors = [e["ram_error_pct"] for e in entries if "ram_error_pct" in e]
    avg_dur = sum(dur_errors) / len(dur_errors) if dur_errors else 0
    avg_ram = sum(ram_errors) / len(ram_errors) if ram_errors else 0

    renderer.print(f"\n  [bold]Prediction Error History[/]  [dim]{total} entries[/]")
    renderer.print(f"  Average duration error: [red]{avg_dur:.1f}%[/]")
    renderer.print(f"  Average RAM error:      [red]{avg_ram:.1f}%[/]")
    renderer.print()

    # Recent entries
    recent = entries[-10:] if len(entries) > 10 else entries
    renderer.print(f"  [bold]Recent {len(recent)} entries:[/]")
    for e in reversed(recent):
        jid = e.get("job_id", "?")[:8]
        dur = e.get("duration_error_pct", 0)
        ram = e.get("ram_error_pct", 0)
        dep = e.get("deployment_accuracy", "?")
        renderer.print(
            f"    {jid:<10}  dur: [red]{dur:6.1f}%[/]  ram: [red]{ram:6.1f}%[/]  deploy: {dep}"
        )
    renderer.print()
    return ExitCode.SUCCESS


async def _fetch_plan_state(job_id: str) -> dict | None:
    try:
        from prometheus.core.redis import CliRedis

        redis = CliRedis()
        try:
            raw = await redis._client.get_str(f"job:{job_id}:plan_state")
            if raw:
                return json.loads(raw) if isinstance(raw, str) else raw
            return None
        finally:
            await redis.close()
    except ImportError:
        return None

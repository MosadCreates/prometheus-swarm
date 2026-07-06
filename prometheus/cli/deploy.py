from __future__ import annotations

import asyncio
import json
import os
import sys

import click

from prometheus.core.docker import get_container_logs, list_serving_containers, stop_and_remove
from prometheus.core.serving import predict
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.tables import deploy_list_table
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="deploy",
    aliases={"ls": "list"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def deploy():
    """Inspect and interact with deployed model endpoints."""


@deploy.command(name="list")
@click.pass_context
def deploy_list(ctx):
    """List all deployed serving containers."""
    renderer = renderer_from_ctx(ctx)
    try:
        containers = list_serving_containers()
    except Exception as e:
        renderer.error(str(e), hint="Check Docker is running")
        return ExitCode.ERROR
    if not containers:
        renderer.print("[dim]No deployed endpoints found.[/dim]")
        return ExitCode.SUCCESS
    renderer.console.print(deploy_list_table(containers))
    return ExitCode.SUCCESS


@deploy.command(name="test")
@click.argument("endpoint_url")
@click.option(
    "--instances", "-i", default=None, help="JSON string, path to .json, or '-' for stdin"
)
@click.pass_context
def deploy_test(ctx, endpoint_url, instances):
    """Send test predictions to a deployed endpoint."""
    renderer = renderer_from_ctx(ctx)
    if not endpoint_url.startswith("http"):
        endpoint_url = f"http://{endpoint_url}"
    payload = _load_instances(instances, renderer)
    if payload is None:
        return ExitCode.ERROR
    try:
        result = asyncio.run(predict(endpoint_url, payload))
    except Exception as e:
        renderer.error(str(e), title="Prediction failed")
        return ExitCode.ERROR
    renderer.raw_json(result)
    return ExitCode.SUCCESS


@deploy.command(name="logs")
@click.argument("container_name")
@click.option("--lines", default=100, type=int)
@click.pass_context
def deploy_logs(ctx, container_name, lines):
    """Show logs for a deployed serving container."""
    renderer = renderer_from_ctx(ctx)
    try:
        output = get_container_logs(container_name, tail=lines)
    except Exception as e:
        renderer.error(str(e), title="Logs error")
        return ExitCode.ERROR
    renderer.print(output)
    return ExitCode.SUCCESS


@deploy.command(name="stop")
@click.argument("container_name")
@click.pass_context
def deploy_stop(ctx, container_name):
    """Stop and remove a deployed serving container."""
    renderer = renderer_from_ctx(ctx)
    try:
        stop_and_remove(container_name)
        renderer.success(f"Container {container_name} removed.")
    except Exception as e:
        renderer.error(str(e), title="Stop failed")
        return ExitCode.ERROR
    return ExitCode.SUCCESS


def _load_instances(instances: str | None, renderer=None) -> list | dict | None:
    if instances is None or instances.strip() == "-":
        raw = sys.stdin.read().strip()
        if not raw:
            if renderer:
                renderer.print("[red]No input provided via --instances or stdin[/red]")
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            if renderer:
                renderer.print(f"[red]Invalid JSON from stdin: {e}[/red]")
            return None
    raw = instances.strip().strip("'\"")
    if raw.startswith(("[", "{")):
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            if renderer:
                renderer.print(f"[red]Invalid JSON in --instances: {e}[/red]")
            return None
    if os.path.exists(raw):
        try:
            with open(raw) as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            if renderer:
                renderer.print(f"[red]Invalid JSON in {raw}: {e}[/red]")
            return None
    if renderer:
        renderer.print(f"[red]File not found: {raw}[/red]")
    return None

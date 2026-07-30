from __future__ import annotations

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.ui.styles import Token
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _app(ctx: click.Context):
    return ctx.find_root().obj["app"]


@click.group(
    cls=AliasedGroup,
    name="provider",
    aliases={"prov": "provider"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def provider():
    """Manage AI providers."""


@provider.command(name="add")
@click.argument("name", type=click.Choice(["anthropic", "openai", "local"], case_sensitive=False))
@click.option("--api-key-env", default=None, help="Name of env var holding the API key")
@click.pass_context
def provider_add(ctx, name: str, api_key_env: str | None):
    """Add and verify a model provider's credentials.

    Always performs a live test call before saving (coming soon).
    """
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).providers
    try:
        info = svc.add_provider(name, api_key_env=api_key_env)
        renderer.success(f"Provider '{info.name}' configured")
        return ExitCode.SUCCESS
    except ValueError as e:
        renderer.error(str(e))
        return ExitCode.ERROR


@provider.command(name="list")
@click.pass_context
def provider_list(ctx):
    """List all configured AI providers."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).providers
    providers = svc.list_providers()
    if not providers:
        renderer.print("[dim]No providers configured.[/dim]")
        return ExitCode.SUCCESS

    rows = []
    for p in providers:
        status = "\u25cf Configured" if p.configured else "\u25cb Not configured"
        color = Token.success if p.configured else Token.error
        rows.append([p.name, p.model, f"[{color}]{status}[/]"])
    renderer.table(["Provider", "Model", "Status"], rows)
    return ExitCode.SUCCESS


@provider.command(name="current")
@click.pass_context
def provider_current(ctx):
    """Show the currently active provider with detailed status."""
    renderer = renderer_from_ctx(ctx)
    svc = _app(ctx).providers
    p = svc.current_provider()

    config_status = "\u25cf Configured" if p.configured else "\u25cb Not configured"
    config_color = Token.success if p.configured else Token.error
    avail_status = "\u25cf Available" if p.available else "\u25cb Unavailable"
    avail_color = Token.success if p.available else Token.warning

    model_name = p.model.replace("-", " ").title()
    auth_status = "API Key Loaded" if hasattr(p, "api_key") and p.api_key else "No API Key"
    auth_color = Token.success if hasattr(p, "api_key") and p.api_key else Token.error

    items = [
        ("Provider", p.name),
        ("Model", model_name),
        ("Status", f"[{config_color}]{config_status}[/]"),
        ("Authentication", f"[{auth_color}]{auth_status}[/]"),
        ("Availability", f"[{avail_color}]{avail_status}[/]"),
    ]
    renderer.status(items, title="Provider Status")
    return ExitCode.SUCCESS

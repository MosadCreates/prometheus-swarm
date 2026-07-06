from __future__ import annotations


import click

from prometheus.services.profile_service import ProfileService
from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.commands import AliasedGroup
from prometheus.utils.exit_codes import ExitCode


def _svc() -> ProfileService:
    return ProfileService()


@click.group(
    cls=AliasedGroup,
    name="profile",
    aliases={"profiles": "profile"},
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def profile():
    """Manage environment profiles."""


@profile.command(name="list")
@click.pass_context
def profile_list(ctx):
    """List all saved profiles."""
    renderer = renderer_from_ctx(ctx)
    profiles = _svc().list()
    if not profiles:
        renderer.print("[dim]No profiles saved.[/dim]")
        return ExitCode.SUCCESS
    active = _svc().current()
    items: list[tuple[str, str]] = []
    for p in profiles:
        label = f"\u25cf {p}" if p == active else f"\u25cb {p}"
        items.append((label, ""))
    renderer.print("  [bold]Profiles[/bold]")
    for label, _ in items:
        renderer.print(f"  {label}")
    if active:
        renderer.print(f"\n  [dim]Active: {active}[/dim]")
    return ExitCode.SUCCESS


@profile.command(name="current")
@click.pass_context
def profile_current(ctx):
    """Show the active profile."""
    renderer = renderer_from_ctx(ctx)
    current = _svc().current()
    if current:
        renderer.print(f"  [bold]{current}[/bold]")
    else:
        renderer.print("[dim]No active profile.[/dim]")
    return ExitCode.SUCCESS


@profile.command(name="save")
@click.argument("name")
@click.pass_context
def profile_save(ctx, name):
    """Save current environment as a profile."""
    renderer = renderer_from_ctx(ctx)
    _svc().save(name)
    profiles_dir = ProfileService()._profiles_dir()
    renderer.success(
        f"Profile '{name}' saved.",
        detail=f"Location: {profiles_dir / name}.env",
        hint=f"prometheus profile switch {name}",
    )
    return ExitCode.SUCCESS


@profile.command(name="switch")
@click.argument("name")
@click.pass_context
def profile_switch(ctx, name):
    """Switch to a saved profile."""
    renderer = renderer_from_ctx(ctx)
    if _svc().switch(name):
        renderer.success(
            f"Switched to profile '{name}'.",
            detail=f"Active profile: {name}",
            hint="prometheus profile current",
        )
    else:
        renderer.error(f"Profile '{name}' not found.", hint="prometheus profile list")
    return ExitCode.SUCCESS


@profile.command(name="inspect")
@click.argument("name")
@click.pass_context
def profile_inspect(ctx, name):
    """Show a profile's environment variables."""
    renderer = renderer_from_ctx(ctx)
    env = _svc().inspect(name)
    if env is None:
        renderer.error(f"Profile '{name}' not found.", hint="prometheus profile list")
        return ExitCode.SUCCESS
    items: list[tuple[str, str]] = []
    for k, v in env.items():
        display = (
            "***" if "KEY" in k.upper() or "PASSWORD" in k.upper() or "SECRET" in k.upper() else v
        )
        items.append((k, display))
    renderer.status(items, title=f"Profile: {name}")
    return ExitCode.SUCCESS


@profile.command(name="delete")
@click.argument("name")
@click.confirmation_option(prompt="Delete this profile?")
@click.pass_context
def profile_delete(ctx, name):
    """Delete a saved profile."""
    renderer = renderer_from_ctx(ctx)
    if _svc().delete(name):
        renderer.success(f"Profile '{name}' deleted.")
    else:
        renderer.error(f"Profile '{name}' not found.")
    return ExitCode.SUCCESS

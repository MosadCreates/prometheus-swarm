from __future__ import annotations

import os
from pathlib import Path

import click

from prometheus.utils.exit_codes import ExitCode


_WIZARD_PROVIDER_NAMES: dict[str, str] = {
    "anthropic": "Anthropic (Claude)",
    "openai": "OpenAI",
    "local": "A local / self-hosted endpoint",
}


def _config_is_configured() -> bool:
    from prometheus.core.config import read_env_file
    from prometheus.core.project import find_project_root

    env = read_env_file(find_project_root())
    key = env.get("ANTHROPIC_API_KEY", "")
    return bool(key) and "YOUR_KEY_HERE" not in key


def _count_missions_this_week() -> int:
    from pathlib import Path as _Path

    import datetime

    outputs = _Path("outputs")
    if not outputs.exists():
        return 0
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    count = 0
    for child in outputs.iterdir():
        if child.is_dir() and (child / "trace.jsonl").exists():
            trace_path = child / "trace.jsonl"
            try:
                mtime = datetime.datetime.fromtimestamp(trace_path.stat().st_mtime)
                if mtime >= week_ago:
                    count += 1
            except (OSError, ValueError):
                pass
    return count


def _count_total_missions() -> int:
    from pathlib import Path as _Path

    outputs = _Path("outputs")
    if not outputs.exists():
        return 0
    return sum(1 for c in outputs.iterdir() if c.is_dir() and (c / "trace.jsonl").exists())


def _workspace_name() -> str:
    from prometheus.services.config_service import ConfigService

    try:
        return ConfigService().get_workspace_name()
    except Exception:
        return "unknown"


def _verify_api_key(provider: str, api_key: str) -> tuple[bool, str]:
    if not api_key:
        return False, "No key provided"
    if provider == "anthropic":
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            client.models.list(limit=1)
            return True, "connected"
        except Exception as e:
            msg = str(e)
            if "401" in msg or "unauthorized" in msg.lower() or "invalid" in msg.lower():
                return False, "Invalid API key"
            if "403" in msg:
                return False, "API key lacks permissions"
            return False, msg[:80]
    if provider == "openai":
        try:
            import openai

            client = openai.OpenAI(api_key=api_key)
            client.models.list(limit=1)
            return True, "connected"
        except Exception as e:
            return False, str(e)[:80]
    return True, "skipped (local endpoint)"


@click.command(name="init")
@click.option("--reset", is_flag=True, default=False, help="Wipe existing config and start over")
@click.option(
    "--non-interactive", is_flag=True, default=False, help="Accept all answers via flags/env"
)
@click.option(
    "--provider",
    type=click.Choice(["anthropic", "openai", "local"]),
    default=None,
    help="Model provider",
)
@click.option("--api-key-env", default=None, help="Name of env var holding the API key")
@click.option("--workspace-dir", type=click.Path(), default=None, help="Workspace directory")
@click.pass_context
def init_cmd(
    ctx: click.Context,
    reset: bool,
    non_interactive: bool,
    provider: str | None,
    api_key_env: str | None,
    workspace_dir: str | None,
) -> ExitCode:
    """Run the guided setup wizard (first-time config)."""
    from prometheus.ui.renderers import renderer_from_ctx

    renderer = renderer_from_ctx(ctx)

    if reset:
        _wipe_config(renderer)

    if _config_is_configured() and not reset:
        renderer.print(
            "[dim]Already configured. Run [bold]prometheus init --reset[/bold] to reconfigure.[/dim]"
        )
        return ExitCode.SUCCESS

    if non_interactive:
        return _run_non_interactive(ctx, renderer, provider, api_key_env, workspace_dir)

    return _run_interactive(ctx, renderer)


def _wipe_config(renderer) -> None:
    from prometheus.core.project import find_project_root

    env_path = find_project_root() / ".env"
    if env_path.exists():
        env_path.unlink()
        renderer.print("  [dim]Existing configuration wiped.[/dim]")


def _run_non_interactive(
    ctx: click.Context,
    renderer,
    provider: str | None,
    api_key_env: str | None,
    workspace_dir: str | None,
) -> ExitCode:
    from prometheus.core.project import find_project_root
    from prometheus.services.config_service import ConfigService

    from prometheus.utils.compat import check_all

    compat = check_all()
    renderer.print("  [bold]Checking environment...[/bold]")
    for r in compat:
        icon = "\u2713" if r["ok"] else "\u2717"
        color = "green" if r["ok"] else "red"
        renderer.print(
            f"    {icon} [{color}]{r['name']:<20}[/] {r['current']:<12} [dim]({r['required']})[/dim]"
        )
    if not all(r["ok"] for r in compat):
        renderer.error("Environment check failed.", hint="Run 'prometheus doctor' for details")
        return ExitCode.ERROR_CONFIG

    if not provider:
        provider = "anthropic"
    if not api_key_env:
        api_key_env = "ANTHROPIC_API_KEY"
    api_key = os.environ.get(api_key_env, "")
    ok, msg = _verify_api_key(provider, api_key)
    if not ok:
        renderer.error(
            f"Provider verification failed: {msg}", hint=f"Set {api_key_env} to a valid key"
        )
        return ExitCode.ERROR_CONFIG
    renderer.print(f"  [green]\u2713[/] {_WIZARD_PROVIDER_NAMES.get(provider, provider)} — {msg}")

    svc = ConfigService()
    svc.set_key("ANTHROPIC_API_KEY", api_key)
    svc.set_key("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if workspace_dir:
        svc.set_key("WORKSPACE_DIR", workspace_dir)

    root = find_project_root()
    renderer.success("Configuration complete", detail=f"Config at {root / '.env'}")
    renderer.print("\n  [dim]Try it now:[/dim]")
    renderer.print('  [bold]prometheus mission new "your problem, in plain English"[/bold]')
    return ExitCode.SUCCESS


def _run_interactive_wizard() -> ExitCode:
    from prometheus.ui.renderers import renderer_from_ctx as _rfc
    import click as _click

    try:
        ctx = _click.get_current_context()
    except RuntimeError:
        ctx = None
    if ctx is not None:
        renderer = _rfc(ctx)
        return _run_interactive(ctx, renderer)
    from prometheus.ui.console import console as _console
    from prometheus.ui.renderers import RichRenderer

    renderer = RichRenderer(_console)
    try:
        return _run_interactive(None, renderer)
    except SystemExit:
        return ExitCode.SUCCESS


def _run_interactive(ctx: click.Context | None, renderer) -> ExitCode:
    from prometheus.services.config_service import ConfigService

    svc = ConfigService()
    from prometheus.core.project import find_project_root as _root_for_wizard

    _root_for_wizard()

    # ── Screen 1: Welcome ─────────────────────────────────────────
    renderer.print()
    renderer.print("  [bold]PROMETHEUS[/bold]")
    renderer.print("  [dim]Six agents. One mission at a time. Nothing you can't inspect.[/dim]")
    renderer.print()
    renderer.print("  This looks like the first time you've run Prometheus here.")
    renderer.print("  Let's get you set up - it takes about a minute.")
    renderer.print()
    _press_enter(renderer)

    # ── Screen 2: Prerequisite checks ─────────────────────────────
    renderer.print()
    renderer.print("  [bold]Checking your environment...[/bold]")
    from prometheus.utils.compat import check_all as _check_all

    compat = _check_all()
    all_ok = True
    for r in compat:
        icon = "\u2713" if r["ok"] else "\u2717"
        color = "green" if r["ok"] else "red"
        renderer.print(
            f"    {icon} [{color}]{r['name']:<20}[/] {r['current']:<12} [dim]({r['required']})[/dim]"
        )
        if not r["ok"]:
            all_ok = False

    from prometheus.core.config import check_prerequisites as _check_pre
    from prometheus.core.project import find_project_root

    pre = _check_pre(find_project_root())
    for r in pre:
        icon = "\u2713" if r["ok"] else "\u2717"
        color = "green" if r["ok"] else "red"
        label = r["name"]
        detail = r.get("detail", "")
        renderer.print(f"    {icon} [{color}]{label:<20}[/] {detail:<12}")
        if not r["ok"]:
            all_ok = False

    if not all_ok:
        renderer.print()
        renderer.print(
            "  [yellow]Some checks failed. You can continue, but fix these first if things don't work.[/yellow]"
        )

    renderer.print()
    _press_enter(renderer)

    # ── Screen 3: Provider + API key ──────────────────────────────
    renderer.print()
    renderer.print("  [bold]Which model provider should Prometheus use?[/bold]")
    provider_names = ["anthropic", "openai", "local"]
    provider_labels = [_WIZARD_PROVIDER_NAMES[n] for n in provider_names]
    choice = _choose(renderer, provider_labels, default=0)
    selected_provider = provider_names[choice]

    api_key = ""
    if selected_provider != "local":
        api_key = _masked_input(renderer, "  API key: ")
        if not api_key.strip():
            renderer.print("  [yellow]No key entered — you can set it later with[/yellow]")
            renderer.print("  [bold]prometheus config set ANTHROPIC_API_KEY=your-key[/bold]")

    if api_key.strip():
        renderer.print()
        renderer.print("  [dim]Verifying key...[/dim]", end="")
        ok, msg = _verify_api_key(selected_provider, api_key.strip())
        if ok:
            renderer.print(f' [green]\u2713[/green] connected as "{msg}"')
        else:
            renderer.print(f" [red]\u2717 {msg}[/red]")
            renderer.print("  [yellow]You can continue and fix this later.[/yellow]")

    # ── Screen 4: Workspace directory ────────────────────────────
    renderer.print()
    renderer.print("  [bold]Where should Prometheus keep its work?[/bold]")
    default_dir = str(Path.home() / "prometheus-workspace")
    chosen_dir = _prompt_default(renderer, "  Workspace directory", default_dir)
    renderer.print()

    # ── Screen 5: Confirmation ───────────────────────────────────
    renderer.print("  [bold]You're set up.[/bold]")
    renderer.print()
    provider_label = _WIZARD_PROVIDER_NAMES.get(selected_provider, selected_provider)
    renderer.print(f"    Provider   {provider_label}")
    renderer.print(f"    Workspace  {chosen_dir}")
    from prometheus.core.project import find_project_root as _root

    renderer.print(f"    Config     {_root() / '.env'}")
    renderer.print()
    renderer.print("  Try it now:")
    renderer.print('  [bold]prometheus mission new "your problem, in plain English"[/bold]')
    renderer.print()

    # Write config
    if api_key.strip():
        svc.set_key("ANTHROPIC_API_KEY", api_key.strip())
    svc.set_key("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if selected_provider == "openai":
        svc.set_key("OPENAI_API_KEY", api_key.strip())
    if selected_provider:
        svc.set_key("ACTIVE_PROVIDER", selected_provider)
    if chosen_dir:
        svc.set_key("WORKSPACE_DIR", chosen_dir)

    _press_enter(renderer, label="Enter to open the shell")
    renderer.print()

    # Drop into shell
    from prometheus.repl import run_repl

    run_repl()
    return ExitCode.SUCCESS


def _press_enter(renderer, label: str = "Enter to begin") -> None:
    import sys as _sys

    if not _sys.stdin.isatty():
        return
    try:
        click.pause(info=f"[ {label} ]\n")
    except Exception:
        pass


def _choose(renderer, options: list[str], default: int = 0) -> int:
    try:
        from prometheus.ui.console import console

        for i, opt in enumerate(options):
            marker = " \u203a" if i == default else "  "
            renderer.print(f"    {marker} {opt}")
        choice = console.input("  [dim]> [/dim]").strip()
        if choice.isdigit() and 0 <= int(choice) < len(options):
            return int(choice)
        if choice.lower() in ("a", "1", "", "anthropic", "openai", "local"):
            for i, n in enumerate(["anthropic", "openai", "local"]):
                if choice.lower() == n:
                    return i
        return default
    except Exception:
        return default


def _masked_input(renderer, prompt: str) -> str:
    try:
        from prometheus.ui.console import console

        import getpass

        return getpass.getpass(prompt)
    except Exception:
        try:
            return console.input(prompt)
        except Exception:
            return ""


def _prompt_default(renderer, label: str, default: str) -> str:
    try:
        from prometheus.ui.console import console

        val = console.input(f"  {label} [{default}]: ").strip()
        return val if val else default
    except Exception:
        return default

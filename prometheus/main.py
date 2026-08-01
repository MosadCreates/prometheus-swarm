import os
import sys
import time
import traceback
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
_root_str = str(_project_root)
if _root_str not in sys.path:
    sys.path.insert(0, _root_str)
os.chdir(_project_root)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import click  # noqa: E402

from prometheus.utils.commands import AliasedGroup  # noqa: E402
from prometheus.utils.exit_codes import ExitCode  # noqa: E402

VERSION = "0.1.0"

_COMMANDS_REGISTERED = False


def _print_splash(fast: bool = False):
    import shutil

    from prometheus.ui.splash import animate_startup
    from prometheus.ui.theme import detect_color_system
    from rich.console import Console

    w = shutil.get_terminal_size().columns
    c = Console(emoji=False, force_terminal=True, width=w, color_system=detect_color_system())
    animate_startup(c, fast=fast)


def _show_splash_and_help(ctx, param, value):
    if value and not ctx.resilient_parsing:
        _print_splash(fast=True)
        click.echo(ctx.get_help(), color=ctx.color)
        ctx.exit()


def _global_exception_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.exit(130)
    from rich.panel import Panel
    from rich.text import Text

    from prometheus.ui.console import console

    text = Text()
    text.append(f"\n  {exc_value}\n", style="red")
    text.append(f"\n  [dim]{exc_type.__name__}[/dim]")
    console.print(
        Panel(
            text,
            title="[bold red]Unexpected Error[/]",
            border_style="red",
        )
    )
    if os.getenv("PROMETHEUS_DEBUG"):
        traceback.print_exception(exc_type, exc_value, exc_tb)


sys.excepthook = _global_exception_handler


def _register_commands():
    global _COMMANDS_REGISTERED
    if _COMMANDS_REGISTERED:
        return
    _COMMANDS_REGISTERED = True

    from prometheus.cli import (
        init_cmd,
        help_cmd,
        doctor_cmd,
        version_cmd,
        daemon_cmd,
        docs_cmd,
        workspace,
        agent,
        mission,
        model,
        provider,
        config,
        plugin,
        deploy,
        profile,
        evaluate,
        memory,
        planner,
    )

    # ── Noun groups ────────────────────────────────────────────────
    cli.add_command(mission)
    cli.add_command(agent)
    cli.add_command(workspace)
    cli.add_command(model)
    cli.add_command(provider)
    cli.add_command(config)
    cli.add_command(plugin)
    cli.add_command(deploy)
    cli.add_command(profile)
    cli.add_command(evaluate)
    cli.add_command(memory)
    cli.add_command(planner)

    # ── System-level commands ──────────────────────────────────────
    cli.add_command(init_cmd)
    cli.add_command(doctor_cmd)
    cli.add_command(version_cmd)
    cli.add_command(help_cmd)
    cli.add_command(daemon_cmd)
    cli.add_command(docs_cmd)


@click.group(
    cls=AliasedGroup,
    register_fn=_register_commands,
    invoke_without_command=True,
    aliases={
        # Noun-level short forms
        "ws": "workspace",
        "ag": "agent",
        "cfg": "config",
        "prov": "provider",
        "mdl": "model",
        "plug": "plugin",
        "miss": "mission",
        "eval": "evaluate",
        "mem": "memory",
        "plan": "planner",
        "dep": "deploy",
        "prof": "profile",
    },
    context_settings=dict(help_option_names=[]),
)
@click.option("-C", "--project-dir", default=None, help="Project root directory")
@click.option(
    "-w",
    "--workspace",
    default=None,
    help="Workspace directory path (overrides nearest .prometheus/ auto-detection)",
)
@click.option(
    "--no-color",
    is_flag=True,
    default=False,
    help="Disable ANSI color output",
)
@click.option(
    "--high-contrast",
    is_flag=True,
    default=False,
    help="Enable high-contrast color theme (accessibility)",
)
@click.option(
    "--font-size",
    type=click.Choice(["small", "medium", "large"]),
    default=None,
    help="Set terminal font size for Cockpit TUI (accessibility)",
)
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging and tracebacks")
@click.option(
    "--format",
    type=click.Choice(["interactive", "plain", "json"]),
    default=None,
    help="Output format (interactive=ANSI, plain=key=value, json=structured)",
)
@click.option(
    "--shell",
    is_flag=True,
    default=False,
    hidden=True,
    help="Force interactive shell mode (for testing with subprocess pipes).",
)
@click.version_option(version=VERSION)
@click.option(
    "--help",
    "-h",
    is_flag=True,
    is_eager=True,
    callback=_show_splash_and_help,
    expose_value=False,
    help="Show this message and exit.",
)
@click.pass_context
def cli(ctx, project_dir, workspace, no_color, high_contrast, font_size, debug, format, shell):
    """Prometheus Swarm — Autonomous AI Engineering System."""
    from prometheus.utils.log import setup_logging
    from prometheus.services import AppContext
    from prometheus.ui.renderers import renderer_from_ctx

    setup_logging(debug=debug)
    if debug:
        os.environ["PROMETHEUS_DEBUG"] = "1"
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["shell"] = shell
    ctx.obj["no_color"] = no_color
    if no_color:
        os.environ["NO_COLOR"] = "1"
    ctx.obj["high_contrast"] = high_contrast
    ctx.obj["font_size"] = font_size
    if high_contrast:
        os.environ["PROMETHEUS_HIGH_CONTRAST"] = "1"
    if font_size:
        os.environ["PROMETHEUS_FONT_SIZE"] = font_size
    fmt = format if format else ("interactive" if sys.stdout.isatty() else "plain")
    ctx.obj["format"] = fmt
    ctx.obj["renderer_from_ctx"] = renderer_from_ctx
    ctx.obj["_start"] = time.perf_counter()
    if "app" not in ctx.obj:
        ctx.obj["app"] = AppContext.create()
    app = ctx.obj["app"]
    cmd_name = ctx.invoked_subcommand or "repl"
    try:
        app.plugins.dispatch_command(cmd_name, [])
    except Exception:
        pass
    if workspace:
        root = Path(workspace).resolve()
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        ctx.obj["project_root"] = root
        os.chdir(str(root))
    elif project_dir:
        root = Path(project_dir).resolve()
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        ctx.obj["project_root"] = root
    else:
        ctx.obj["project_root"] = _project_root

    if ctx.invoked_subcommand is None:
        is_tty = sys.stdin.isatty()
        if not is_tty and not shell:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit(0)

        from prometheus.cli.init import _config_is_configured

        if not _config_is_configured():
            from prometheus.cli.init import _run_interactive_wizard

            try:
                _run_interactive_wizard()
            except SystemExit:
                pass
            ctx.exit(0)

        # Clear screen to hide shell prompt before splash
        import shutil

        shutil.os.system("cls" if shutil.os.name == "nt" else "clear")

        from prometheus.ui.console import console as shared_console
        from prometheus.ui.claude.splash import splash as claude_splash

        claude_splash(shared_console)

        from prometheus.repl import run_repl

        run_repl()
        ctx.exit()


def _command_path(ctx: click.Context) -> str:
    parts: list[str] = []
    while ctx.parent:
        if ctx.info_name:
            parts.insert(0, ctx.info_name)
        ctx = ctx.parent
    if ctx.info_name and (not parts or parts[0] != ctx.info_name):
        parts.insert(0, ctx.info_name)
    return " ".join(parts)


@cli.result_callback()
@click.pass_context
def _process_result(ctx, result, **kwargs):
    start = ctx.obj.pop("_start", None)
    if start:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        cmd_name = _command_path(ctx) or ctx.info_name or "unknown"
        exit_code = 0
        if isinstance(result, ExitCode):
            exit_code = result.value
        elif isinstance(result, int):
            exit_code = result
        from prometheus.utils.telemetry import _record

        _record(
            {
                "command": cmd_name,
                "duration_ms": duration_ms,
                "exit_code": exit_code,
                "success": exit_code == 0,
            }
        )
    if isinstance(result, ExitCode):
        ctx.exit(result.value)
    elif isinstance(result, int):
        ctx.exit(result)

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

import click  # noqa: E402

from prometheus.utils.commands import AliasedGroup  # noqa: E402
from prometheus.utils.exit_codes import ExitCode  # noqa: E402

VERSION = "0.1.0"

_COMMANDS_REGISTERED = False


def _print_splash():
    import shutil

    from prometheus.ui.splash import animate_startup
    from rich.console import Console

    w = shutil.get_terminal_size().columns
    c = Console(emoji=False, force_terminal=True, width=w)
    animate_startup(c, version=VERSION)


def _show_splash_and_help(ctx, param, value):
    if value and not ctx.resilient_parsing:
        _print_splash()
        click.echo(ctx.get_help(), color=ctx.color)
        ctx.exit()


def _global_exception_handler(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
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
        help_cmd,
        commands_cmd,
        search_cmd,
        doctor_cmd,
        version_cmd,
        cheatsheet_cmd,
        docs_cmd,
        diagnostics_cmd,
        workspace,
        agent,
        job,
        config,
        provider,
        swarm,
        deploy,
        logs,
        memory,
        tool,
        profile,
        plugin,
        solve,
        explain,
        replay,
        report,
        planner,
        benchmark,
        reproduce,
        evaluate,
    )

    cli.add_command(workspace)
    cli.add_command(agent)
    cli.add_command(job)
    cli.add_command(config)
    cli.add_command(provider)
    cli.add_command(swarm)
    cli.add_command(deploy)
    cli.add_command(logs)
    cli.add_command(memory)
    cli.add_command(tool)
    cli.add_command(profile)
    cli.add_command(plugin)
    cli.add_command(solve)
    cli.add_command(explain)
    cli.add_command(replay)
    cli.add_command(report)
    cli.add_command(planner)
    cli.add_command(benchmark)
    cli.add_command(reproduce)
    cli.add_command(evaluate)

    cli.add_command(help_cmd)
    cli.add_command(commands_cmd)
    cli.add_command(search_cmd)
    cli.add_command(doctor_cmd)
    cli.add_command(version_cmd)
    cli.add_command(cheatsheet_cmd)
    cli.add_command(docs_cmd)
    cli.add_command(diagnostics_cmd)


@click.group(
    cls=AliasedGroup,
    register_fn=_register_commands,
    invoke_without_command=True,
    aliases={
        "ws": "workspace",
        "ag": "agent",
        "cfg": "config",
        "prov": "provider",
        "mem": "memory",
        "jb": "job",
        "sv": "solve",
        "ex": "explain",
        "rp": "replay",
        "rpt": "report",
    },
    context_settings=dict(help_option_names=[]),
)
@click.option("-C", "--project-dir", default=None, help="Project root directory")
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging and tracebacks")
@click.option(
    "--format",
    type=click.Choice(["rich", "json", "yaml", "plain"]),
    default="rich",
    help="Output format",
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
def cli(ctx, project_dir, debug, format):
    """Prometheus Swarm — Autonomous AI Engineering System."""
    from prometheus.utils.log import setup_logging
    from prometheus.services import AppContext
    from prometheus.ui.renderers import renderer_from_ctx

    setup_logging(debug=debug)
    if debug:
        os.environ["PROMETHEUS_DEBUG"] = "1"
    ctx.ensure_object(dict)
    ctx.obj["debug"] = debug
    ctx.obj["format"] = format
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
    if project_dir:
        root = Path(project_dir).resolve()
        root_str = str(root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        ctx.obj["project_root"] = root
    else:
        ctx.obj["project_root"] = _project_root

    if ctx.invoked_subcommand is None:
        _print_splash()
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

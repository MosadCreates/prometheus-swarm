import os
import shlex

import click
from rich.text import Text

from prometheus.main import cli, VERSION
from prometheus.ui.styles import Token
from prometheus.ui.console import console


def run_repl():
    echo = console.print
    _history: list[str] = []

    while True:
        try:
            prompt = Text()
            prompt.append("prometheus ", style=Token.secondary)
            prompt.append("\u276f ", style=Token.status_text)
            line = console.input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            echo()
            break

        if not line:
            continue

        _history.append(line)

        if line in ("exit", "quit", "q"):
            break

        if line == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            continue

        if line == "history":
            for i, h in enumerate(_history, 1):
                echo(f"  [dim]{i:>3}[/]  {h}")
            continue

        if line == "!":
            echo("  [dim]No previous command.[/dim]")
            continue

        if line.startswith("!"):
            try:
                idx = int(line.lstrip("!"))
                if 1 <= idx <= len(_history):
                    line = _history[idx - 1]
                else:
                    continue
            except ValueError:
                pass

        try:
            parts = shlex.split(line, comments=True)
        except ValueError as e:
            echo(f"  [red]{e}[/]")
            continue

        cmd = parts[0]
        args = parts[1:]

        if args and args[-1] == "?":
            args[-1] = "--help"

        if cmd in ("help", "?"):
            _repl_help(echo)
            continue

        if cmd == "??":
            from prometheus.registry import list_by_category
            from prometheus.ui.renderers import CategorizedCommandTable

            console.print(CategorizedCommandTable(list_by_category()))
            continue

        try:
            cli([cmd] + args, standalone_mode=False)
        except SystemExit as e:
            if e.code and e.code != 0:
                from prometheus.registry import suggest_command

                hint = suggest_command(cmd)
                if hint:
                    echo(f"  [dim]Did you mean '[bold]{hint}[/bold]'?[/dim]")
        except click.NoSuchOption as e:
            from prometheus.registry import suggest_command

            hint = suggest_command(cmd)
            msg = str(e)
            if hint:
                msg += f"\n  [dim]Did you mean '[bold]{hint}[/bold]'?[/dim]"
            echo(f"  [red]{msg}[/]")
        except click.BadParameter as e:
            echo(f"  [red]{e.format_message()}[/]")
        except Exception as e:
            echo(f"  [red]{e}[/]")

    echo("  Swarm offline.")


def _repl_help(echo):
    echo()
    echo(f"  [bold]Prometheus Swarm {VERSION}[/bold]")
    echo(f"  [{Token.border}]\u2500" + "\u2500" * 38 + "[/]")
    echo(f"  [{Token.secondary}]help|?[/]        Show this list")
    echo(f"  [{Token.secondary}]??[/]             Show categorized commands")
    echo(f"  [{Token.secondary}]<cmd> --help[/]   Show help for a command")
    echo(f"  [{Token.secondary}]<cmd> ?[/]        Show help for a command")
    echo(f"  [{Token.secondary}]history[/]        Show command history")
    echo(f"  [{Token.secondary}]!<n>[/]           Re-run command #n from history")
    echo(f"  [{Token.secondary}]clear[/]          Clear screen")
    echo(f"  [{Token.secondary}]exit[/]           Exit")
    echo()

    from prometheus.registry import COMMANDS

    impl = [c for c in COMMANDS if c.tier == 1]
    if impl:
        echo("  [bold]Available Commands[/bold]")
        for c in impl:
            echo(f"  [{Token.secondary}]{c.name:<26}[/] [dim]{c.description}[/]")
    echo()

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Callable

import click
from rich.text import Text

from prometheus.main import cli, VERSION
from prometheus.ui.styles import Token
from prometheus.ui.console import console
from prometheus.ui.input import read_input
from prometheus.utils.slugs import workspace_name, count_missions_this_week

_COMMAND_NOUNS = frozenset(
    {
        "mission",
        "agent",
        "workspace",
        "model",
        "provider",
        "config",
        "plugin",
        "help",
        "init",
        "doctor",
        "version",
        "daemon",
        # Redirect stubs (valid commands that print a redirect message)
        "benchmark",
        "deploy",
        "evaluate",
        "explain",
        "job",
        "logs",
        "memory",
        "planner",
        "profile",
        "replay",
        "report",
        "reproduce",
        "solve",
        "swarm",
        "tool",
    }
)

_MISSION_VERBS = frozenset(
    {"new", "watch", "list", "status", "resume", "cancel", "report", "replay", "logs"}
)
_AGENT_VERBS = frozenset({"list", "inspect", "trace"})
_MODEL_VERBS = frozenset({"list", "show", "export"})
_CONFIG_VERBS = frozenset({"get", "set"})
_PROVIDER_VERBS = frozenset({"list", "add", "current"})
_PLUGIN_VERBS = frozenset({"install", "remove", "list"})

_AGENT_NAMES = ["Scout", "Forge", "Furnace", "Dissect", "Arbiter", "Harbor"]


def _mission_ids_from_outputs() -> list[str]:
    """Scan outputs/ for mission directories (UUIDs or slug names)."""
    try:
        p = Path("outputs")
        if p.is_dir():
            return sorted(d.name for d in p.iterdir() if d.is_dir())
    except OSError:
        pass
    return []


def _workspace_names_from_config() -> list[str]:
    """Load workspace names from the app config file."""
    try:
        from prometheus.services.config_service import ConfigService

        cfg = ConfigService()
        raw = cfg.root / ".prometheus" / "config.toml"
        if raw.exists():
            import tomllib

            data = tomllib.loads(raw.read_text())
            return sorted(data.get("workspaces", []))
    except Exception:
        pass
    return []


def _make_completer() -> Callable[[str], list[str]]:
    """Build a tab-complete function for the shared input handler.

    Returns a callable ``(line_text: str) -> list[str]`` suitable as a
    ``completer`` argument to ``read_input()``.
    """

    def _complete_current_word(line: str) -> list[str]:
        words = line.split()
        # Determine the prefix (last word or empty if trailing space)
        if not words or line.endswith(" "):
            text = words[-1] if words else ""
            candidates = _all_words()
            return sorted(w for w in candidates if w.startswith(text))

        text = words[-1]
        noun = words[0].lower()

        # mission <verb> <tab> — offer mission IDs
        if noun == "mission" and len(words) >= 2:
            verb = words[1].lower()
            if verb in _MISSION_VERBS:
                return [mid for mid in _mission_ids_from_outputs() if mid.startswith(text)]

        # agent <verb> <tab> — offer agent names
        if noun == "agent" and len(words) >= 2:
            verb = words[1].lower()
            if verb in ("inspect", "trace"):
                return [a for a in _AGENT_NAMES if a.startswith(text)]

        # model <verb> <tab> — offer mission IDs
        if noun == "model" and len(words) >= 2:
            verb = words[1].lower()
            if verb in ("show", "export"):
                return [mid for mid in _mission_ids_from_outputs() if mid.startswith(text)]

        # workspace use <tab> — offer workspace names
        if noun == "workspace" and len(words) >= 2:
            verb = words[1].lower()
            if verb == "use":
                return [w for w in _workspace_names_from_config() if w.startswith(text)]

        # Fallback: match against any known word
        return sorted(w for w in _all_words() if w.startswith(text))

    return _complete_current_word


def _all_words() -> set[str]:
    words: set[str] = set(_COMMAND_NOUNS)
    words.update(_MISSION_VERBS, _AGENT_VERBS, _MODEL_VERBS)
    words.update(_CONFIG_VERBS, _PROVIDER_VERBS, _PLUGIN_VERBS)
    words.update({"init", "use", "current", "add", "get", "set", "install", "remove"})
    return words


def print_header() -> None:
    width = _terminal_width()
    name = workspace_name()
    count = count_missions_this_week()
    header = f"prometheus \u00b7 {name} \u00b7 {count} mission{'s' if count != 1 else ''} this week"
    sep = "\u2500" * min(width - 4, 50)
    console.print(f"  {header}")
    console.print(f"  [dim]{sep}[/dim]")
    console.print()


def run_repl() -> None:
    completer = _make_completer()
    echo = console.print
    _history: list[str] = []

    console.print()

    while True:
        w = _terminal_width()
        sep = _separator(w)
        echo(sep)

        try:
            raw = read_input(
                prompt="\u276f ",
                history=_history,
                multiline=False,
                completer=completer,
                console=console,
            )
            line = raw.strip()
        except KeyboardInterrupt:
            echo(sep)
            continue
        except EOFError:
            echo()
            break

        echo(sep)

        if not line:
            continue

        _history.append(line)

        if line in ("exit", "quit", "q"):
            break

        if line in ("help", "?"):
            _repl_help(echo)
            echo(_status_bar(w))
            continue

        if line == "??":
            _repl_categories(echo)
            echo(_status_bar(w))
            continue

        if line == "clear":
            os.system("cls" if os.name == "nt" else "clear")
            echo(sep)
            continue

        if line == "history":
            for i, h in enumerate(_history, 1):
                echo(f"  [dim]{i:>3}[/]  {h}")
            echo(_status_bar(w))
            continue

        # Alt+key command shortcuts (Alt+D → :doctor, etc.)
        _HANDLED_SHORTCUTS = {
            "doctor": "doctor",
            "list": "mission list",
            "report": "mission report",
            "solve": "solve",
            "explain": "explain",
            "memory": "memory stats",
            "benchmark": "benchmark summary",
            "workspace": "workspace status",
        }
        if line.startswith(":") and line[1:] in _HANDLED_SHORTCUTS:
            cmd = _HANDLED_SHORTCUTS[line[1:]]
            echo(f"  [dim]\u21b7 {cmd}[/dim]")
            try:
                cli(cmd.split(), standalone_mode=False)
            except SystemExit:
                pass
            except Exception as exc:
                echo(f"  [{Token.error}]{exc}[/]")
            echo(_status_bar(w))
            continue

        if line == "!":
            echo("  [dim]No previous command.[/dim]")
            echo(_status_bar(w))
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
            echo(_status_bar(w))
            continue

        cmd = parts[0]
        args = parts[1:]

        if args and args[-1] == "?":
            args[-1] = "--help"

        if cmd.lower() == "mode":
            _REPL_STATE.cycle_mode()
            echo(f"  Switched to [bold]{_REPL_STATE.mode}[/] mode.")
            echo(_status_bar(w))
            continue

        first_noun = cmd.lower()
        if first_noun not in _COMMAND_NOUNS:
            echo("  [dim]\u2192 starting a new mission from this description[/dim]")
            desc_text = " ".join(parts)
            try:
                cli(["mission", "new", desc_text], standalone_mode=False)
            except SystemExit:
                pass
            echo(_status_bar(w))
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
        echo(_status_bar(w))

    echo("  Swarm offline.")


def _repl_help(echo):
    echo()
    echo(f"  [bold]Prometheus Swarm {VERSION}[/bold]")
    echo(f"  [{Token.border}]\u2500" + "\u2500" * 38 + "[/]")
    echo(f"  [{Token.secondary}]help|?[/]        Show this list")
    echo(f"  [{Token.secondary}]<noun> --help[/]  Show help for a command group")
    echo(f"  [{Token.secondary}]<noun> <verb> ?[/]  Show help for a command")
    echo(f"  [{Token.secondary}]<natural text>[/]  Start a new mission from plain English")
    echo(f"  [{Token.secondary}]history[/]        Show command history")
    echo(f"  [{Token.secondary}]!<n>[/]           Re-run command #n from history")
    echo(f"  [{Token.secondary}]clear[/]          Clear screen")
    echo(f"  [{Token.secondary}]exit[/]           Exit")
    echo()

    echo("  [bold]Nouns[/bold]")
    for noun in sorted(_COMMAND_NOUNS):
        echo(f"  [{Token.secondary}]{noun:<12}[/]")
    echo()


def _repl_categories(echo):
    echo()
    echo("  [bold]Categories[/bold]")
    echo(f"  [{Token.border}]\u2500" + "\u2500" * 38 + "[/]")
    echo("  [bold]System[/bold]")
    echo(f"    [{Token.secondary}]version[/]     Show version")
    echo(f"    [{Token.secondary}]doctor[/]      Run diagnostics")
    echo(f"    [{Token.secondary}]init[/]        Setup wizard")
    echo(f"    [{Token.secondary}]clear[/]       Clear screen")
    echo(f"    [{Token.secondary}]exit[/]        Exit the shell")
    echo()
    echo("  [bold]Mission[/bold]")
    echo(f"    [{Token.secondary}]<text>[/]      Start a new mission from description")
    echo(f"    [{Token.secondary}]mission new[/]  Submit a new mission")
    echo(f"    [{Token.secondary}]mission list[/] List recent missions")
    echo(f"    [{Token.secondary}]mission status[/]  Check mission status")
    echo(f"    [{Token.secondary}]mission logs[/]    View mission logs")
    echo()
    echo("  [bold]Config[/bold]")
    echo(f"    [{Token.secondary}]provider[/]    Manage AI providers")
    echo(f"    [{Token.secondary}]config[/]      Configure settings")
    echo(f"    [{Token.secondary}]workspace[/]   Manage workspace")
    echo()
    echo("  [bold]Agents[/bold]")
    echo(f"    [{Token.secondary}]agent[/]       Manage swarm agents")
    echo(f"    [{Token.secondary}]model[/]       Inspect trained models")
    echo(f"    [{Token.secondary}]plugin[/]      Manage plugins")
    echo()


class _ReplState:
    mode: str = "manual"

    def cycle_mode(self) -> None:
        self.mode = "auto" if self.mode == "manual" else "manual"


_REPL_STATE = _ReplState()


def _separator(width: int) -> str:
    bar = "\u2500" * width
    return f"[{Token.border}]{bar}[/]"


def _status_bar(width: int) -> str:
    mode_symbol = "\u23f8" if _REPL_STATE.mode == "manual" else "\u2713"
    parts = [
        f"{mode_symbol} {_REPL_STATE.mode} mode on",
        "? for shortcuts",
        "\u2190 for agents",
        "\u2191 for history",
    ]
    line = " \u00b7 ".join(parts)
    return f"  [{Token.secondary}]{line}[/]"


def _terminal_width() -> int:
    import shutil

    return shutil.get_terminal_size().columns

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import click


def fuzzy_suggest(bad_name: str, valid_names: list[str]) -> str | None:
    best = None
    best_ratio = 0.0
    for name in valid_names:
        ratio = SequenceMatcher(None, bad_name.lower(), name.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = name
    return best if best_ratio > 0.4 else None


class AliasedGroup(click.Group):
    def __init__(
        self,
        *args: Any,
        aliases: dict[str, str] | None = None,
        register_fn: callable | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.aliases: dict[str, str] = aliases or {}
        self._register_fn = register_fn

    def _ensure_commands(self) -> None:
        if self._register_fn and not self.commands:
            self._register_fn()

    def add_command(self, cmd: click.Command, name: str | None = None) -> None:
        super().add_command(cmd, name)

    def list_commands(self, ctx: click.Context) -> list[str]:
        self._ensure_commands()
        return super().list_commands(ctx)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        self._ensure_commands()
        cmd_name = self.aliases.get(cmd_name, cmd_name)
        cmd = super().get_command(ctx, cmd_name)
        if cmd is not None:
            return cmd

        valid = list(self.commands.keys()) + list(self.aliases.keys())
        suggestion = self._fuzzy_match(cmd_name, valid)
        if suggestion:
            resolved = self.aliases.get(suggestion, suggestion)
            msg = f"Unknown command '{cmd_name}'.\n\nDid you mean '{resolved}'?"
        else:
            msg = f"Unknown command '{cmd_name}'."
        raise click.NoSuchOption(msg)

    def _fuzzy_match(self, bad: str, valid: list[str]) -> str | None:
        bad_lower = bad.lower()
        best, best_ratio = None, 0.0
        for v in valid:
            v_lower = v.lower()
            if v_lower == bad_lower:
                return v
            ratio = SequenceMatcher(None, bad_lower, v_lower).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best = v
        return best if best_ratio > 0.4 else None

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        rows: list[tuple[str, str]] = []
        for sub in self.list_commands(ctx):
            cmd = self.get_command(ctx, sub)
            if cmd is None or cmd.hidden:
                continue
            aliases_str = ""
            for alias, target in self.aliases.items():
                if target == sub:
                    aliases_str = f" [{alias}]"
                    break
            label = f"{sub}{aliases_str}"
            rows.append((label, cmd.short_help or ""))
        if rows:
            with formatter.section("Commands"):
                formatter.write_dl(rows)


def not_implemented(command_path: str, planned_version: str = "v0.2.0") -> str:
    from rich.panel import Panel
    from rich.text import Text

    text = Text()
    text.append("\n  This feature is planned but not yet implemented.\n", style="yellow")
    text.append(f"  Planned for: {planned_version}\n", style="dim")
    return Panel(text, title=f"[bold yellow]{command_path}[/]", border_style="yellow")


def error_panel(title: str, message: str, hint: str | None = None) -> str:
    from rich.panel import Panel
    from rich.text import Text

    text = Text()
    text.append(f"\n  {message}\n", style="red")
    if hint:
        text.append(f"\n  [dim]Try:[/dim] [bold]{hint}[/bold]\n", style="white")
    return Panel(text, title=f"[bold red]{title}[/]", border_style="red")


def success_panel(title: str, message: str) -> str:
    from rich.panel import Panel
    from rich.text import Text

    text = Text()
    text.append(f"\n  {message}\n", style="green")
    return Panel(text, title=f"[bold green]{title}[/]", border_style="green")


def record_command_usage(command: str, args: list[str], duration: float, success: bool) -> None:
    pass

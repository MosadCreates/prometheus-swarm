from __future__ import annotations

from prometheus.registry.command import Command
from prometheus.registry.generate import build_from_cli


def _build() -> list[Command]:
    """Build the command registry from the live click command tree.

    The registry is derived from the commands actually registered on the root
    ``prometheus`` group, so it can never drift from what ``prometheus <cmd>``
    accepts. See :mod:`prometheus.registry.generate`.
    """
    return build_from_cli()


_commands: list[Command] | None = None
_categories: list[str] | None = None


def _get_commands() -> list[Command]:
    global _commands
    if _commands is None:
        _commands = _build()
    return _commands


def get_commands() -> list[Command]:
    return _get_commands()


def get_categories() -> list[str]:
    global _categories
    if _categories is None:
        seen: set[str] = set()
        cats: list[str] = []
        for cmd in _get_commands():
            if cmd.category not in seen:
                cats.append(cmd.category)
                seen.add(cmd.category)
        _categories = cats
    return _categories


def get_command(name: str) -> Command | None:
    for cmd in _get_commands():
        if cmd.name == name:
            return cmd
        if name in cmd.aliases:
            return cmd
    return None


def list_by_category() -> dict[str, list[Command]]:
    result: dict[str, list[Command]] = {}
    for cmd in _get_commands():
        if cmd.hidden:
            continue
        result.setdefault(cmd.category, []).append(cmd)
    return result


def __getattr__(name: str):
    if name == "COMMANDS":
        return _get_commands()
    if name == "CATEGORIES":
        return get_categories()
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

"""Generate the command registry from the live click command tree.

The registry is the single source of truth for ``help``/``search``/``docs``.
Instead of a hand-maintained static list (which drifted from the real CLI), we
introspect the commands actually registered on the root ``prometheus`` group so
the registry can never advertise a command that does not exist.

Import contract: this module must NOT import ``prometheus.main`` at module
level. ``prometheus/cli/system.py`` imports ``prometheus.registry`` at module
level, so a top-level ``from prometheus.main import cli`` here would create the
cycle ``main -> cli/system -> registry -> generate -> main``. The root CLI is
therefore imported lazily inside ``_get_root_cli()``.
"""

from __future__ import annotations

import click

from prometheus.registry.command import Command

# Top-level noun group -> help category. Anything not listed (init, doctor,
# version, help, daemon, ...) falls under "System".
GROUP_CATEGORIES: dict[str, str] = {
    "mission": "Mission",
    "agent": "Agents",
    "workspace": "Workspace",
    "model": "Model",
    "provider": "Provider",
    "config": "Config",
    "plugin": "Plugin",
    "evaluate": "Evaluate",
    "memory": "Memory",
    "planner": "Planner",
    "deploy": "Deploy",
    "profile": "Profile",
}


def category_for(group_name: str) -> str:
    """Return the help category for a top-level command name."""
    return GROUP_CATEGORIES.get(group_name, "System")


def _get_root_cli() -> click.Group:
    """Return the registered root CLI group, forcing lazy registration."""
    # Lazy import avoids the import cycle described in the module docstring.
    from prometheus.main import cli

    # cli.commands is a plain dict in click 8.x; the lazy register_fn fires via
    # AliasedGroup.list_commands/get_command. Discard the (alphabetical) result
    # and read cli.commands directly for registration order.
    cli.list_commands(None)
    return cli


def _description(cmd: click.Command) -> str:
    """One-line description: first sentence of the docstring."""
    text = (cmd.help or cmd.short_help or "").strip()
    first = text.splitlines()[0].strip() if text else ""
    return first.rstrip(".") or first


def _leaf_aliases(
    group: click.Group,
    group_name: str,
    sub_name: str,
    root_aliases: dict[str, str],
) -> list[str]:
    """Derive full-path aliases for one leaf command.

    Examples:
    - root alias ``ws -> workspace`` => ``workspace init`` gets ``ws init``
    - nested alias ``ls -> list`` on ``agent`` => ``agent list`` gets ``agent ls``
    - self alias ``plugins -> plugin`` => ``plugin list`` gets ``plugins list``
    """
    aliases: set[str] = set()
    for alias, target in root_aliases.items():
        if target == group_name and " " not in target:
            aliases.add(f"{alias} {sub_name}")
    for alias, target in getattr(group, "aliases", {}).items():
        if target == sub_name:
            aliases.add(f"{group_name} {alias}")
        elif target == group_name:
            aliases.add(f"{alias} {sub_name}")
    return sorted(aliases)


def _single_aliases(root_aliases: dict[str, str], name: str) -> list[str]:
    """Aliases for a top-level leaf command (e.g. ``help``)."""
    return sorted(alias for alias, target in root_aliases.items() if target == name)


def build_from_cli() -> list[Command]:
    """Introspect the registered click tree and produce the Command list."""
    cli = _get_root_cli()
    root_aliases = getattr(cli, "aliases", {})
    commands: list[Command] = []

    # System commands (leaves) first, then noun groups — this yields the
    # "System" category first in get_categories()/list_by_category().
    leaves = [(n, c) for n, c in cli.commands.items() if not isinstance(c, click.Group)]
    groups = [(n, c) for n, c in cli.commands.items() if isinstance(c, click.Group)]

    for name, cmd in leaves:
        commands.append(
            Command(
                name=name,
                category=category_for(name),
                description=_description(cmd),
                aliases=_single_aliases(root_aliases, name),
                tier=1,
                hidden=bool(getattr(cmd, "hidden", False)),
            )
        )

    for gname, group in groups:
        for sub_name, sub in group.commands.items():
            if isinstance(sub, click.Group):
                # Only one level of nesting is registered today.
                continue
            commands.append(
                Command(
                    name=f"{gname} {sub_name}",
                    category=category_for(gname),
                    description=_description(sub),
                    aliases=_leaf_aliases(group, gname, sub_name, root_aliases),
                    tier=2,
                    hidden=bool(getattr(sub, "hidden", False)),
                )
            )

    return commands

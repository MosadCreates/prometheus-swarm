import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from click import Command as ClickCommand, Group as ClickGroup

from prometheus.main import cli
from prometheus.registry import (
    CATEGORIES,
    COMMANDS,
    get_command,
    list_by_category,
    search_commands,
)


def _walk_click_commands(
    group: ClickGroup,
    prefix: str = "",
) -> set[str]:
    names: set[str] = set()
    for name, cmd in group.commands.items():
        if not isinstance(cmd, ClickGroup):
            full = f"{prefix} {name}" if prefix else name
            names.add(full)
        else:
            names |= _walk_click_commands(cmd, prefix=name)
    return names


CLICK_COMMANDS = _walk_click_commands(cli)
REGISTRY_NAMES = {c.name for c in COMMANDS}
IMPLEMENTED_REGISTRY_NAMES = {c.name for c in COMMANDS if c.implemented}


def _find_click_cmd(name: str) -> ClickCommand | None:
    parts = name.split()
    if len(parts) == 1:
        return cli.commands.get(name)
    group = cli.commands.get(parts[0])
    if isinstance(group, ClickGroup):
        return group.commands.get(parts[1])
    return None


@pytest.mark.validation
class TestRegistryValidation:
    def test_registry_commands_resolve(self):
        for cmd in COMMANDS:
            found = get_command(cmd.name)
            assert found is not None, f"get_command('{cmd.name}') returned None"
            assert found.name == cmd.name

    def test_no_orphan_commands(self):
        missing = IMPLEMENTED_REGISTRY_NAMES - CLICK_COMMANDS
        assert not missing, f"Registry implemented commands missing from Click: {sorted(missing)}"

    def test_no_duplicate_command_names(self):
        seen: set[str] = set()
        dupes: set[str] = set()
        for cmd in COMMANDS:
            if cmd.name in seen:
                dupes.add(cmd.name)
            seen.add(cmd.name)
        assert not dupes, f"Duplicate command names: {sorted(dupes)}"

    def test_no_duplicate_aliases(self):
        alias_map: dict[str, list[str]] = {}
        for cmd in COMMANDS:
            for alias in cmd.aliases:
                alias_map.setdefault(alias, []).append(cmd.name)
        conflicts = {a: n for a, n in alias_map.items() if len(n) > 1}
        assert not conflicts, f"Aliases mapping to multiple commands: {conflicts}"

    def test_no_alias_ambiguity(self):
        alias_targets: dict[str, set[str]] = {}
        for cmd in COMMANDS:
            for alias in cmd.aliases:
                resolved = get_command(alias)
                assert resolved is not None, f"Alias '{alias}' does not resolve"
                alias_targets.setdefault(alias, set()).add(resolved.name)
        ambiguous = {a: t for a, t in alias_targets.items() if len(t) > 1}
        assert not ambiguous, f"Aliases resolving to multiple commands: {ambiguous}"

    def test_all_categories_valid(self):
        known = set(CATEGORIES)
        for cmd in COMMANDS:
            assert (
                cmd.category in known
            ), f"Command '{cmd.name}' has unknown category '{cmd.category}'"

    def test_all_tiers_valid(self):
        for cmd in COMMANDS:
            assert cmd.tier in (1, 2, 3), f"Command '{cmd.name}' has invalid tier {cmd.tier}"

    def test_all_implemented_have_description(self):
        for cmd in COMMANDS:
            if cmd.implemented:
                assert (
                    cmd.description
                ), f"Command '{cmd.name}' is implemented but has no description"

    def test_help_generates(self):
        for cmd in COMMANDS:
            if not cmd.implemented:
                continue
            click_cmd = _find_click_cmd(cmd.name)
            assert click_cmd is not None, f"No Click command found for '{cmd.name}'"
            from click import Context

            ctx = Context(click_cmd, info_name=cmd.name)
            help_text = click_cmd.get_help(ctx)
            assert (
                isinstance(help_text, str) and len(help_text) > 0
            ), f"get_help() returned empty for '{cmd.name}'"

    def test_click_registry_parity(self):
        for click_name in CLICK_COMMANDS:
            assert (
                click_name in REGISTRY_NAMES
            ), f"Click command '{click_name}' has no registry entry"

        for reg_name in IMPLEMENTED_REGISTRY_NAMES:
            assert (
                reg_name in CLICK_COMMANDS
            ), f"Registry implemented command '{reg_name}' has no matching Click command"


@pytest.mark.validation
class TestRegistryCompleteness:
    def test_search_returns_implemented_commands(self):
        for cmd in COMMANDS:
            if cmd.implemented:
                results = search_commands(cmd.name, threshold=0.0)
                assert any(
                    c.name == cmd.name for c, _ in results
                ), f"search_commands('{cmd.name}') did not return '{cmd.name}'"

    def test_get_command_by_alias(self):
        for cmd in COMMANDS:
            for alias in cmd.aliases:
                found = get_command(alias)
                assert found is not None, f"Alias '{alias}' for '{cmd.name}' did not resolve"
                assert found.name == cmd.name

    def test_list_by_category_includes_all(self):
        categorized = list_by_category()
        listed = {c.name for cat in categorized.values() for c in cat}
        visible = {c.name for c in COMMANDS if not c.hidden}
        assert listed == visible, f"list_by_category() missing: {sorted(visible - listed)}"

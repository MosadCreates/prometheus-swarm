from prometheus.registry.command import Command
from prometheus.registry.registry import get_commands, get_categories, get_command, list_by_category
from prometheus.registry.search import search_commands, suggest_command


def __getattr__(name: str):
    from prometheus.registry.registry import __getattr__ as _registry_getattr

    return _registry_getattr(name)


__all__ = [
    "Command",
    "get_commands",
    "get_categories",
    "get_command",
    "list_by_category",
    "search_commands",
    "suggest_command",
]

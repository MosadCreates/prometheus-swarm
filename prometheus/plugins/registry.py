from __future__ import annotations

from prometheus.plugins.base import PluginABC


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, PluginABC] = {}

    def register(self, plugin: PluginABC) -> None:
        self._plugins[plugin.name] = plugin
        plugin.on_load()

    def unregister(self, name: str) -> None:
        plugin = self._plugins.pop(name, None)
        if plugin:
            plugin.on_unload()

    def get(self, name: str) -> PluginABC | None:
        return self._plugins.get(name)

    def list(self) -> list[PluginABC]:
        return list(self._plugins.values())

    def dispatch_command(self, command: str, args: list[str]) -> None:
        for plugin in self._plugins.values():
            plugin.on_command(command, args)

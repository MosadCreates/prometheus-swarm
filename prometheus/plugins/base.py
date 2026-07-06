from __future__ import annotations

from abc import ABC, abstractmethod


class PluginABC(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def version(self) -> str: ...

    def on_load(self) -> None:
        """Called when the plugin is registered."""

    def on_unload(self) -> None:
        """Called when the plugin is unregistered."""

    def on_command(self, command: str, args: list[str]) -> None:
        """Called before a command is executed."""

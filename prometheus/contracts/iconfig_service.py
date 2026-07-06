from __future__ import annotations

from abc import ABC, abstractmethod


class IConfigService(ABC):
    @abstractmethod
    def show(self) -> dict[str, str]: ...

    @abstractmethod
    def set_key(self, key: str, value: str) -> bool: ...

    @abstractmethod
    def check_prerequisites(self) -> list[dict]: ...

    @abstractmethod
    def get_workspace_name(self) -> str: ...

    @abstractmethod
    def get_version(self) -> str: ...

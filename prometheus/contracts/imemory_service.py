from __future__ import annotations

from abc import ABC, abstractmethod


class IMemoryService(ABC):
    @abstractmethod
    def stats(self) -> dict: ...

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[dict]: ...

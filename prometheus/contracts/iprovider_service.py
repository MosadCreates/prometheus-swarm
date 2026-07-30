from __future__ import annotations

from abc import ABC, abstractmethod

from prometheus.dto.provider_dto import ProviderInfo


class IProviderService(ABC):
    @abstractmethod
    def add_provider(self, name: str, api_key_env: str | None = None) -> ProviderInfo: ...

    @abstractmethod
    def list_providers(self) -> list[ProviderInfo]: ...

    @abstractmethod
    def current_provider(self) -> ProviderInfo: ...

    @abstractmethod
    def is_configured(self) -> bool: ...

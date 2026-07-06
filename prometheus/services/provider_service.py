from __future__ import annotations

import os

from prometheus.dto.provider_dto import ProviderInfo
from prometheus.contracts import IProviderService


class ProviderService(IProviderService):
    def list_providers(self) -> list[ProviderInfo]:
        current_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        configured = bool(os.getenv("ANTHROPIC_API_KEY"))
        return [
            ProviderInfo(
                name="Anthropic", model=current_model, configured=configured, available=configured
            ),
            ProviderInfo(
                name="OpenAI", model="(not configured)", configured=False, available=False
            ),
        ]

    def current_provider(self) -> ProviderInfo:
        return self.list_providers()[0]

    def is_configured(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

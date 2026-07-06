from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from prometheus.services.provider_service import ProviderService


class TestProviderService:
    @pytest.fixture
    def svc(self) -> ProviderService:
        return ProviderService()

    def test_list_providers_returns_two(self, svc: ProviderService):
        providers = svc.list_providers()
        assert len(providers) == 2

    def test_list_providers_includes_anthropic(self, svc: ProviderService):
        names = [p.name for p in svc.list_providers()]
        assert "Anthropic" in names

    def test_current_provider_returns_anthropic(self, svc: ProviderService):
        current = svc.current_provider()
        assert current.name == "Anthropic"
        assert current.model

    def test_is_configured_reflects_env(self, svc: ProviderService):
        key = os.getenv("ANTHROPIC_API_KEY")
        expected = bool(key)
        assert svc.is_configured() == expected

    def test_current_provider_model_from_env(self, svc: ProviderService):
        current = svc.current_provider()
        expected_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        assert current.model == expected_model

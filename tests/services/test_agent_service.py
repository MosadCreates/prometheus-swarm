from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from prometheus.services.agent_service import AgentService


class TestAgentService:
    @pytest.fixture
    def svc(self) -> AgentService:
        return AgentService()

    def test_list_agents_returns_all_six(self, svc: AgentService):
        agents = svc.list_agents()
        assert len(agents) == 6
        names = [a.name for a in agents]
        assert "scout" in names
        assert "forge" in names
        assert "furnace" in names
        assert "dissect" in names
        assert "arbiter" in names
        assert "harbor" in names

    def test_list_agents_returns_agent_summary_dtos(self, svc: AgentService):
        for agent in svc.list_agents():
            assert agent.name
            assert agent.display_name
            assert agent.status
            assert isinstance(agent.tools, int)

    def test_inspect_agent_scout(self, svc: AgentService):
        detail = svc.inspect_agent("scout")
        assert detail is not None
        assert detail.name == "scout"
        assert detail.display_name == "Scout"
        assert detail.capabilities

    def test_inspect_agent_forge(self, svc: AgentService):
        detail = svc.inspect_agent("forge")
        assert detail is not None
        assert detail.name == "forge"
        assert detail.role == "Forge"

    def test_inspect_agent_unknown(self, svc: AgentService):
        detail = svc.inspect_agent("nonexistent")
        assert detail is None

    def test_count_agents(self, svc: AgentService):
        assert svc.count_agents() == 6

    def test_count_tools(self, svc: AgentService):
        count = svc.count_tools()
        assert isinstance(count, int)
        assert count >= 0

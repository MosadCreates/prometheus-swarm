from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from prometheus.dto.agent_dto import AgentDetail, AgentSummary
from prometheus.dto.provider_dto import ProviderInfo
from prometheus.dto.workspace_dto import ScanResult, WorkspaceInfo
from prometheus.services.app_context import AppContext


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def mock_agent_service() -> MagicMock:
    svc = MagicMock()
    svc.list_agents.return_value = [
        AgentSummary(name="scout", display_name="Scout", status="idle", tools=5),
        AgentSummary(name="forge", display_name="Forge", status="idle", tools=3),
        AgentSummary(name="furnace", display_name="Furnace", status="idle", tools=7),
        AgentSummary(name="dissect", display_name="Dissect", status="idle", tools=4),
        AgentSummary(name="arbiter", display_name="Arbiter", status="idle", tools=6),
        AgentSummary(name="harbor", display_name="Harbor", status="idle", tools=8),
    ]
    svc.inspect_agent.return_value = AgentDetail(
        name="scout",
        display_name="Scout",
        status="idle",
        role="Scout",
        version="0.1.0",
        tools=["scout.load_data", "scout.summarize"],
        capabilities=["Exploratory data analysis"],
    )
    svc.count_agents.return_value = 6
    svc.count_tools.return_value = 33
    return svc


@pytest.fixture
def mock_workspace_service() -> MagicMock:
    svc = MagicMock()
    svc.get_info.return_value = WorkspaceInfo(
        root=str(Path.cwd()),
        name="test-workspace",
        version="0.1.0",
        has_env=True,
        has_docker=True,
        files=42,
        agents=6,
        last_indexed=None,
    )
    svc.scan.return_value = ScanResult(
        total_files=100,
        directories=20,
        supported_files=80,
        size_kb=1024,
    )
    svc.status.return_value = "5/5 checks passed"
    return svc


@pytest.fixture
def mock_provider_service() -> MagicMock:
    svc = MagicMock()
    svc.list_providers.return_value = [
        ProviderInfo(name="Anthropic", model="claude-sonnet-4-6", configured=True, available=True),
        ProviderInfo(name="OpenAI", model="(not configured)", configured=False, available=False),
    ]
    svc.current_provider.return_value = ProviderInfo(
        name="Anthropic",
        model="claude-sonnet-4-6",
        configured=True,
        available=True,
    )
    svc.is_configured.return_value = True
    return svc


@pytest.fixture
def mock_config_service() -> MagicMock:
    svc = MagicMock()
    svc.show.return_value = {"ANTHROPIC_API_KEY": "sk-...", "REDIS_HOST": "localhost"}
    svc.check_prerequisites.return_value = [
        {"check": ".env", "ok": True},
        {"check": ".git", "ok": True},
        {"check": "Python 3.11+", "ok": True},
    ]
    return svc


@pytest.fixture
def mock_job_service() -> MagicMock:
    svc = MagicMock()
    svc.list_jobs.return_value = []
    return svc


@pytest.fixture
def mock_memory_service() -> MagicMock:
    svc = MagicMock()
    return svc


@pytest.fixture
def mock_app_context(
    mock_agent_service: MagicMock,
    mock_workspace_service: MagicMock,
    mock_provider_service: MagicMock,
    mock_config_service: MagicMock,
    mock_job_service: MagicMock,
    mock_memory_service: MagicMock,
) -> MagicMock:
    ctx = MagicMock(spec=AppContext)
    ctx.agents = mock_agent_service
    ctx.workspace = mock_workspace_service
    ctx.providers = mock_provider_service
    ctx.config = mock_config_service
    ctx.jobs = mock_job_service
    ctx.memory = mock_memory_service
    return ctx

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from prometheus.services.workspace_service import WorkspaceService


class TestWorkspaceService:
    @pytest.fixture
    def svc(self) -> WorkspaceService:
        return WorkspaceService()

    def test_get_info_returns_workspace_info(self, svc: WorkspaceService):
        info = svc.get_info()
        assert info.root
        assert info.name
        assert isinstance(info.has_env, bool)
        assert isinstance(info.has_docker, bool)
        assert isinstance(info.files, int)
        assert isinstance(info.agents, int)

    def test_get_info_root_is_directory(self, svc: WorkspaceService):
        info = svc.get_info()
        root = Path(info.root)
        assert root.is_dir()

    def test_scan_returns_scan_result(self, svc: WorkspaceService):
        result = svc.scan()
        assert isinstance(result.total_files, int)
        assert isinstance(result.directories, int)
        assert isinstance(result.supported_files, int)
        assert isinstance(result.size_kb, int)

    def test_scan_positive_counts(self, svc: WorkspaceService):
        result = svc.scan()
        assert result.total_files > 0
        assert result.directories > 0
        assert result.size_kb > 0

    def test_status_returns_string(self, svc: WorkspaceService):
        status = svc.status()
        assert isinstance(status, str)
        assert "checks" in status

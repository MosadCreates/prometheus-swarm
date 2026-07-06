from __future__ import annotations

import os
import subprocess
from pathlib import Path

from prometheus.dto.workspace_dto import ScanResult, WorkspaceInfo
from prometheus.contracts import IWorkspaceService
from prometheus.core.project import find_project_root


class WorkspaceService(IWorkspaceService):
    def __init__(self) -> None:
        self._root: Path | None = None

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = find_project_root()
        return self._root

    def get_info(self) -> WorkspaceInfo:
        root = self.root
        pyproject = root / "pyproject.toml"
        version = None
        name = root.name
        if pyproject.exists():
            try:
                import tomllib

                data = tomllib.loads(pyproject.read_text())
                project = data.get("project", {})
                name = project.get("name", name)
                version = project.get("version")
            except Exception:
                pass
        return WorkspaceInfo(
            root=str(root),
            name=name,
            version=version,
            has_env=(root / ".env").exists(),
            has_docker=(root / "docker-compose.yml").exists(),
            files=self._count_files(),
            agents=(
                sum(
                    1
                    for d in (root / "agents").iterdir()
                    if d.is_dir() and not d.name.startswith("_")
                )
                if (root / "agents").exists()
                else 0
            ),
            last_indexed=None,
        )

    def scan(self) -> ScanResult:
        root = self.root
        total = 0
        dirs = 0
        supported = 0
        size = 0
        exts = {
            ".py",
            ".toml",
            ".yaml",
            ".yml",
            ".json",
            ".md",
            ".env",
            ".txt",
            ".sh",
            ".ps1",
            ".csv",
        }
        for path in root.rglob("*"):
            if any(part.startswith(".") for part in path.parts):
                continue
            if path.is_dir():
                dirs += 1
            elif path.is_file():
                total += 1
                if path.suffix in exts:
                    supported += 1
                size += path.stat().st_size
        return ScanResult(
            total_files=total, directories=dirs, supported_files=supported, size_kb=size // 1024
        )

    def status(self) -> str:
        root = self.root
        checks = {
            "pyproject.toml": (root / "pyproject.toml").exists(),
            ".env": (root / ".env").exists(),
            "agents/": (root / "agents").exists(),
            "docker-compose.yml": (root / "docker-compose.yml").exists(),
            ".git": (root / ".git").exists(),
        }
        passed = sum(1 for v in checks.values() if v)
        total = len(checks)
        return f"{passed}/{total} checks passed"

    def _count_files(self) -> int:
        count = 0
        for path in self.root.rglob("*"):
            if any(part.startswith(".") for part in path.parts):
                continue
            if path.is_file():
                count += 1
        return count

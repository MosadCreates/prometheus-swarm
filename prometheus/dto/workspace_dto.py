from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceInfo:
    root: str
    name: str
    version: str | None
    has_env: bool
    has_docker: bool
    files: int
    agents: int
    last_indexed: str | None


@dataclass(frozen=True)
class ScanResult:
    total_files: int
    directories: int
    supported_files: int
    size_kb: int

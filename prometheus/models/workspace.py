from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Workspace:
    root: str
    name: str
    version: str | None = None
    has_env: bool = False
    has_docker: bool = False
    total_files: int = 0
    last_indexed: str | None = None

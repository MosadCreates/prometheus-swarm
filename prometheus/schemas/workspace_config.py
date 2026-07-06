from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WorkspaceConfig:
    root: str = ""
    auto_index: bool = True
    exclude_patterns: tuple[str, ...] = ("__pycache__", ".git", ".venv", "node_modules")

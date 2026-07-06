from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from prometheus.contracts import IConfigService
from prometheus.core.project import find_project_root


class ConfigService(IConfigService):
    def __init__(self) -> None:
        self._root: Path | None = None

    @property
    def root(self) -> Path:
        if self._root is None:
            self._root = find_project_root()
        return self._root

    def show(self) -> dict[str, str]:
        from prometheus.core.config import read_env_file

        return read_env_file(self.root)

    def set_key(self, key: str, value: str) -> bool:
        env_path = self.root / ".env"
        lines = env_path.read_text().splitlines() if env_path.exists() else []
        found = False
        new_lines: list[str] = []
        for line in lines:
            if line.strip().startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                found = True
            else:
                new_lines.append(line)
        if not found:
            new_lines.append(f"{key}={value}")
        env_path.write_text("\n".join(new_lines) + "\n")
        return True

    def check_prerequisites(self) -> list[dict]:
        from prometheus.core.config import check_prerequisites

        return check_prerequisites(self.root)

    def get_workspace_name(self) -> str:
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib

                return (
                    tomllib.loads(pyproject.read_text())
                    .get("project", {})
                    .get("name", self.root.name)
                )
            except Exception:
                pass
        return self.root.name

    def get_version(self) -> str:
        pyproject = self.root / "pyproject.toml"
        if pyproject.exists():
            try:
                import tomllib

                return (
                    tomllib.loads(pyproject.read_text()).get("project", {}).get("version", "0.0.0")
                )
            except Exception:
                pass
        return "0.0.0"

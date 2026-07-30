from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from shutil import copy2

from prometheus.contracts import IConfigService
from prometheus.core.project import find_project_root

logger = logging.getLogger(__name__)

_KNOWN_CREDENTIAL_PREFIXES = frozenset(
    {
        "sk-ant-",  # Anthropic
        "sk-proj-",  # OpenAI project keys
        "sk-",  # OpenAI (generic — keep last, it's a substring risk)
    }
)
_BACKUP_SUFFIX = ".backup"


class ConfigService(IConfigService):
    def __init__(self, root: Path | None = None) -> None:
        self._root = root

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
        if env_path.exists():
            self._backup(env_path)
            self._guard_credential_overwrite(env_path, key, value)

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

    def _backup(self, env_path: Path) -> None:
        backup_path = env_path.with_name(env_path.name + _BACKUP_SUFFIX)
        try:
            copy2(str(env_path), str(backup_path))
        except OSError:
            logger.warning("Failed to create .env.backup at %s", backup_path)

    def _guard_credential_overwrite(self, env_path: Path, key: str, new_value: str) -> None:
        current_value = self._read_current_value(env_path, key)
        if not current_value:
            return
        if self._looks_like_credential(current_value) and not self._looks_like_credential(
            new_value
        ):
            logger.warning(
                "Overwriting %s: old value looks like a real credential "
                "(prefix match), new value does not. "
                "old='%s...' new='%s'",
                key,
                current_value[:8],
                new_value,
            )

    @staticmethod
    def _read_current_value(env_path: Path, key: str) -> str | None:
        if not env_path.exists():
            return None
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith(f"{key}="):
                return line[len(key) + 1 :]
        return None

    @staticmethod
    def _looks_like_credential(value: str) -> bool:
        if not value:
            return False
        for prefix in _KNOWN_CREDENTIAL_PREFIXES:
            if value.startswith(prefix):
                return True
        return False

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

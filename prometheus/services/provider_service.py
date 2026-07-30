from __future__ import annotations

import os

from pathlib import Path

from prometheus.dto.provider_dto import ProviderInfo
from prometheus.contracts import IProviderService


_SUPPORTED = frozenset({"anthropic", "openai", "local"})


class ProviderService(IProviderService):
    def __init__(self) -> None:
        self._env_path: Path | None = None

    @property
    def _env_file(self) -> Path:
        if self._env_path is None:
            from prometheus.core.project import find_project_root

            self._env_path = find_project_root() / ".env"
        return self._env_path

    def _read_env(self) -> dict[str, str]:
        env: dict[str, str] = {}
        if self._env_file.exists():
            for line in self._env_file.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip().strip('"').strip("'")
        return env

    def _write_env(self, updates: dict[str, str]) -> None:
        current = self._read_env()
        current.update(updates)
        lines: list[str] = []
        if self._env_file.exists():
            lines = self._env_file.read_text().splitlines()
        written_keys: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                new_lines.append(line)
                continue
            k = stripped.partition("=")[0].strip()
            if k in updates:
                new_lines.append(f"{k}={updates[k]}")
                written_keys.add(k)
            else:
                new_lines.append(line)
        for k, v in updates.items():
            if k not in written_keys:
                new_lines.append(f"{k}={v}")
        self._env_file.parent.mkdir(parents=True, exist_ok=True)
        self._env_file.write_text("\n".join(new_lines) + "\n")

    def add_provider(self, name: str, api_key_env: str | None = None) -> ProviderInfo:
        name_lower = name.lower()
        if name_lower not in _SUPPORTED:
            raise ValueError(
                f"Unsupported provider '{name}'. Choose from: {', '.join(sorted(_SUPPORTED))}"
            )

        env_updates: dict[str, str] = {}
        if name_lower == "anthropic":
            env_updates["ANTHROPIC_MODEL"] = "claude-sonnet-4-6"
            if api_key_env:
                import shlex

                val = os.getenv(api_key_env, "")
                if not val:
                    raise ValueError(f"Environment variable {api_key_env} is not set or empty")
                env_updates["ANTHROPIC_API_KEY"] = shlex.quote(val) if " " in val else val
        elif name_lower == "openai":
            if api_key_env:
                import shlex

                val = os.getenv(api_key_env, "")
                if not val:
                    raise ValueError(f"Environment variable {api_key_env} is not set or empty")
                env_updates["OPENAI_API_KEY"] = shlex.quote(val) if " " in val else val
        elif name_lower == "local":
            pass

        self._write_env(env_updates)
        return ProviderInfo(
            name=name,
            model=env_updates.get("ANTHROPIC_MODEL", "local"),
            configured=True,
            available=True,
        )

    def list_providers(self) -> list[ProviderInfo]:
        current_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        configured = bool(os.getenv("ANTHROPIC_API_KEY"))
        return [
            ProviderInfo(
                name="Anthropic", model=current_model, configured=configured, available=configured
            ),
            ProviderInfo(
                name="OpenAI", model="(not configured)", configured=False, available=False
            ),
        ]

    def current_provider(self) -> ProviderInfo:
        return self.list_providers()[0]

    def is_configured(self) -> bool:
        return bool(os.getenv("ANTHROPIC_API_KEY"))

from __future__ import annotations

import os
from pathlib import Path

_PROFILES_DIR = Path.home() / ".prometheus" / "profiles"
_ACTIVE_FILE = Path.home() / ".prometheus" / "active_profile"


class ProfileService:
    def __init__(self) -> None:
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[str]:
        if not _PROFILES_DIR.exists():
            return []
        return sorted(f.stem for f in _PROFILES_DIR.iterdir() if f.suffix == ".env")

    def current(self) -> str | None:
        if _ACTIVE_FILE.exists():
            name = _ACTIVE_FILE.read_text(encoding="utf-8").strip()
            if name and (self._profile_path(name).exists()):
                return name
        return None

    def inspect(self, name: str) -> dict[str, str] | None:
        path = self._profile_path(name)
        if not path.exists():
            return None
        return self._load_env(path)

    def save(self, name: str, env: dict[str, str] | None = None) -> None:
        path = self._profile_path(name)
        source = env if env is not None else dict(os.environ)
        lines = [f"{k}={v}\n" for k, v in sorted(source.items())]
        path.write_text("".join(lines), encoding="utf-8")

    def switch(self, name: str) -> bool:
        path = self._profile_path(name)
        if not path.exists():
            return False
        _ACTIVE_FILE.write_text(name, encoding="utf-8")
        return True

    def delete(self, name: str) -> bool:
        path = self._profile_path(name)
        if not path.exists():
            return False
        path.unlink()
        if _ACTIVE_FILE.exists() and _ACTIVE_FILE.read_text(encoding="utf-8").strip() == name:
            _ACTIVE_FILE.unlink()
        return True

    @staticmethod
    def _profile_path(name: str) -> Path:
        return _PROFILES_DIR / f"{name}.env"

    @staticmethod
    def _load_env(path: Path) -> dict[str, str]:
        env: dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
        return env

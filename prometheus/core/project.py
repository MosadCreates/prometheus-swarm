import os
import sys
from pathlib import Path


def find_project_root(start: str | None = None) -> Path:
    env_home = os.getenv("PROMETHEUS_HOME")
    if env_home:
        return Path(env_home).resolve()

    current = Path(start or os.getcwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "CLAUDE.md").exists():
            return candidate

    return current


def ensure_on_path(project_root: Path) -> None:
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

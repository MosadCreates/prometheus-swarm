from __future__ import annotations

import importlib.metadata
import platform
import sys
from typing import Any


_DEPS: list[dict[str, Any]] = [
    {"name": "click", "min": "8.1"},
    {"name": "rich", "min": "13.0"},
    {"name": "shellingham", "min": "1.5"},
]


def check_python() -> dict[str, Any]:
    version = sys.version_info
    ok = version.major >= 3 and version.minor >= 10
    return {
        "name": "Python",
        "current": f"{version.major}.{version.minor}.{version.micro}",
        "required": ">=3.10",
        "ok": ok,
    }


def check_os() -> dict[str, Any]:
    system = platform.system()
    ok = system in ("Windows", "Linux", "Darwin")
    return {
        "name": "OS",
        "current": f"{system} {platform.release()}",
        "required": "Windows/Linux/macOS",
        "ok": ok,
    }


def check_disk_space() -> dict[str, Any]:
    try:
        import shutil

        usage = shutil.disk_usage(".")
        free_gb = usage.free / (1024**3)
        ok = free_gb >= 5.0
        return {
            "name": "Disk space",
            "current": f"{free_gb:.1f} GB free",
            "required": ">= 5.0 GB",
            "ok": ok,
        }
    except Exception as e:
        return {
            "name": "Disk space",
            "current": str(e),
            "required": ">= 5.0 GB",
            "ok": False,
        }


def check_dependency(dep: dict[str, Any]) -> dict[str, Any]:
    name = dep["name"]
    required = dep["min"]
    try:
        ver = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return {"name": name, "current": "not installed", "required": f">={required}", "ok": False}
    from packaging.version import parse as parse_version

    ok = parse_version(ver) >= parse_version(required)
    return {"name": name, "current": ver, "required": f">={required}", "ok": ok}


def check_all() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = [check_python(), check_os(), check_disk_space()]
    for dep in _DEPS:
        results.append(check_dependency(dep))
    return results

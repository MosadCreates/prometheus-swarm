"""Reproducibility context — full version/configuration snapshot per job.

Every job records git commit, config hash, Python/dependency versions,
agent versions, and dataset fingerprint. Ensures every benchmark result
can be reproduced months later.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory.schemas import ReproducibilityContext

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Key files whose contents are hashed for configuration fingerprint
_CONFIG_FILES = [
    ".env.example",
    "requirements.txt",
    "pyproject.toml",
    "docker-compose.yml",
]

# Agent modules that report a version string
_AGENT_MODULES = {
    "scout": "agents.scout",
    "forge": "agents.forge",
    "furnace": "agents.furnace",
    "dissect": "agents.dissect",
    "arbiter": "agents.arbiter",
    "harbor": "agents.harbor",
}


def _git_commit() -> tuple[str, str, bool]:
    """Return (commit_hash, branch, has_uncommitted_changes)."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=5,
        ).stdout.strip()
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=5,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, cwd=_REPO_ROOT, timeout=5,
        ).stdout.strip()
        return commit, branch, bool(status)
    except Exception:
        return "", "", False


def _config_hash() -> str:
    """SHA256 of concatenated config file contents."""
    hasher = hashlib.sha256()
    for name in _CONFIG_FILES:
        path = _REPO_ROOT / name
        if path.exists():
            try:
                content = path.read_bytes()
                hasher.update(name.encode())
                hasher.update(content)
            except Exception:
                pass
    return hasher.hexdigest()[:16]


def _dependency_versions() -> dict[str, str]:
    """Read pinned dependency versions from requirements.txt."""
    deps: dict[str, str] = {}
    req_path = _REPO_ROOT / "requirements.txt"
    if not req_path.exists():
        return deps
    try:
        for line in req_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "==" not in line:
                continue
            parts = line.split("==")
            if len(parts) == 2:
                deps[parts[0].strip()] = parts[1].strip()
    except Exception:
        pass
    return deps


def _installed_versions() -> dict[str, str]:
    """Get actually installed versions for key packages."""
    key_packages = [
        "prometheus-swarm",
        "anthropic",
        "redis",
        "chromadb",
        "pydantic",
        "fastapi",
        "lightgbm",
        "xgboost",
        "torch",
        "transformers",
        "pandas",
        "numpy",
        "scikit-learn",
        "optuna",
    ]
    versions: dict[str, str] = {}
    for pkg in key_packages:
        try:
            mod = __import__(pkg.replace("-", "_"))
            ver = getattr(mod, "__version__", None)
            if ver:
                versions[pkg] = ver
        except (ImportError, AttributeError):
            try:
                import importlib.metadata
                ver = importlib.metadata.version(pkg)
                versions[pkg] = ver
            except Exception:
                pass
    return versions


def _agent_versions() -> dict[str, str]:
    """Try to get version string from each agent module."""
    versions: dict[str, str] = {}
    for name, module_path in _AGENT_MODULES.items():
        try:
            mod = __import__(module_path, fromlist=["__version__"])
            ver = getattr(mod, "__version__", None)
            if ver:
                versions[name] = str(ver)
            else:
                versions[name] = "unknown"
        except Exception:
            versions[name] = "unknown"
    return versions


def _dataset_fingerprint(file_path: str) -> dict[str, Any]:
    """Compute a lightweight fingerprint of the dataset file.

    Uses file size + first 1MB + last 1MB to avoid reading large files entirely.
    """
    fp: dict[str, Any] = {
        "file_path": file_path,
        "exists": False,
        "size_bytes": 0,
        "content_hash": "",
    }
    path = Path(file_path)
    if not path.exists():
        return fp

    fp["exists"] = True
    try:
        size = path.stat().st_size
        fp["size_bytes"] = size

        hasher = hashlib.sha256()
        hasher.update(str(size).encode())
        hasher.update(str(path.stat().st_mtime_ns).encode())
        hasher.update(file_path.encode())

        # Sample first 1MB
        with open(path, "rb") as f:
            head = f.read(1_048_576)
            hasher.update(head)

        # Sample last 1MB if file is larger than 2MB
        if size > 2_097_152:
            with open(path, "rb") as f:
                f.seek(-1_048_576, os.SEEK_END)
                tail = f.read(1_048_576)
                hasher.update(tail)

        fp["content_hash"] = hasher.hexdigest()[:16]
    except Exception as e:
        logger.warning(f"Dataset fingerprint failed for {file_path}: {e}")

    return fp


def _get_python_version() -> str:
    return f"{platform.python_implementation()} {platform.python_version()}"


async def gather_reproducibility_context(
    job_id: str,
    dataset_path: str = "",
) -> ReproducibilityContext:
    """Gather full reproducibility context for a job.

    Called at job submission time before Scout begins.
    All errors are caught and logged — a failure to gather context
    never blocks job submission.
    """
    commit, branch, dirty = "", "", False
    config_hash = ""
    deps: dict[str, str] = {}
    installed: dict[str, str] = {}
    agent_vers: dict[str, str] = {}
    ds_fp: dict[str, Any] = {}

    try:
        commit, branch, dirty = _git_commit()
    except Exception as e:
        logger.warning(f"Git info failed: {e}")

    try:
        config_hash = _config_hash()
    except Exception as e:
        logger.warning(f"Config hash failed: {e}")

    try:
        deps = _dependency_versions()
    except Exception as e:
        logger.warning(f"Dependency versions failed: {e}")

    try:
        installed = _installed_versions()
    except Exception as e:
        logger.warning(f"Installed versions failed: {e}")

    try:
        agent_vers = _agent_versions()
    except Exception as e:
        logger.warning(f"Agent versions failed: {e}")

    if dataset_path:
        try:
            ds_fp = _dataset_fingerprint(dataset_path)
        except Exception as e:
            logger.warning(f"Dataset fingerprint failed: {e}")

    # Merge pinned + installed versions
    all_deps = {**deps, **installed}

    return ReproducibilityContext(
        job_id=job_id,
        git_commit=commit,
        git_branch=branch,
        has_uncommitted_changes=dirty,
        configuration_hash=config_hash,
        python_version=_get_python_version(),
        dependency_versions=all_deps,
        mission_spec_version="2.0",
        execution_plan_version="1.0",
        planner_version="1.0",
        agent_versions=agent_vers,
        dataset_fingerprint=ds_fp,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


async def record_reproducibility(
    redis: Any, context: ReproducibilityContext
) -> None:
    """Store reproducibility context in Redis.

    Args:
        redis: Redis async client (or anything with a set_json / set_str method)
        context: The context to store
    """
    key = f"job:{context.job_id}:reproducibility"
    try:
        if hasattr(redis, "set_json"):
            await redis.set_json(key, context.model_dump())
        elif hasattr(redis, "set_str"):
            await redis.set_str(key, context.model_dump_json())
        else:
            await redis.set(key, context.model_dump_json())
        logger.info(
            f"[job={context.job_id}] Reproducibility recorded: "
            f"git={context.git_commit[:8] if context.git_commit else 'none'} "
            f"deps={len(context.dependency_versions)}"
        )
    except Exception as e:
        logger.warning(f"[job={context.job_id}] Reproducibility record failed: {e}")

"""RuntimePaths — single source of truth for all filesystem paths.

Every agent imports RuntimePaths. Nobody constructs paths manually.
Host paths → Docker mount paths → Container paths are all consistent.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from contracts.domain import SCHEMA_VERSION_V1


class RuntimePaths(BaseModel):
    """Central path registry — all paths derive from environment once.

    Usage:
        paths = RuntimePaths.resolve()
        job = paths.for_job("job-uuid")
        ckpt = job.checkpoint_path  # Path object
        volumes = job.docker_mounts  # dict for Docker SDK
        env = job.container_env      # dict for container env vars
    """

    schema_version: str = SCHEMA_VERSION_V1

    # ── Resolved absolute paths (computed from env, never relative) ──
    workspace: Path = Field(default_factory=lambda: Path.cwd())
    data: Path = Field(default_factory=lambda: _resolve_dir("DATA_DIR", "./data"))
    outputs: Path = Field(default_factory=lambda: _resolve_dir("OUTPUTS_DIR", "./outputs"))
    scripts: Path = Field(default_factory=lambda: _resolve_dir("SCRIPTS_DIR", "./scripts"))
    research: Path = Field(default_factory=lambda: _resolve_dir("RESEARCH_DIR", "./research"))
    patch_log: Path = Field(
        default_factory=lambda: _resolve_path("PATCH_LOG_PATH", "./research/patch_log.jsonl")
    )

    # ── Container paths (what the Docker container sees) ──
    # These are Linux paths — always forward-slash, never Path on Windows
    container_data: str = "/app/data"
    container_outputs: str = "/app/outputs"
    container_scripts: str = "/app/scripts"

    # ── Well-known filenames (used across all agents) ──
    checkpoint_filename: str = "best.ckpt"
    eval_report_pattern: str = "eval_report_{job_id}.json"
    diagnostic_report_pattern: str = "diagnostic_{job_id}.json"
    training_script_pattern: str = "training_script_{job_id}.py"
    mission_state_filename: str = "mission_state.json"
    deploy_config_filename: str = "deploy_config.json"

    @classmethod
    def resolve(cls) -> RuntimePaths:
        """Create RuntimePaths from environment. Cached — call once at startup."""
        return cls()

    def for_job(self, job_id: str) -> JobPaths:
        """Create per-job path provider."""
        return JobPaths(base=self, job_id=job_id)


class JobPaths:
    """Per-job path provider. All paths derive from RuntimePaths + job_id."""

    def __init__(self, base: RuntimePaths, job_id: str) -> None:
        self._base = base
        self.job_id = job_id

    # ── Directories ──────────────────────────────────────────────────

    @property
    def job_dir(self) -> Path:
        return self._base.outputs / self.job_id

    @property
    def checkpoints_dir(self) -> Path:
        return self.job_dir / "checkpoints"

    @property
    def logs_dir(self) -> Path:
        return self.job_dir / "logs"

    @property
    def metrics_dir(self) -> Path:
        return self.job_dir / "metrics"

    @property
    def plots_dir(self) -> Path:
        return self.job_dir / "plots"

    @property
    def artifacts_dir(self) -> Path:
        return self.job_dir / "artifacts"

    @property
    def temp_dir(self) -> Path:
        return self.job_dir / "temp"

    @property
    def serving_dir(self) -> Path:
        return self.job_dir / "serving"

    def retry_dir(self, attempt: int) -> Path:
        return self.job_dir / f"retry_{attempt}"

    # ── Well-known files ─────────────────────────────────────────────

    @property
    def checkpoint_path(self) -> Path:
        return self.checkpoints_dir / self._base.checkpoint_filename

    @property
    def script_path(self) -> Path:
        return self._base.scripts / f"training_script_{self.job_id}.py"

    @property
    def eval_report_path(self) -> Path:
        return self.job_dir / f"eval_report_{self.job_id}.json"

    @property
    def diagnostic_report_path(self) -> Path:
        return self.job_dir / f"diagnostic_{self.job_id}.json"

    @property
    def mission_state_path(self) -> Path:
        return self.job_dir / self._base.mission_state_filename

    @property
    def trace_path(self) -> Path:
        return self.job_dir / "trace.jsonl"

    @property
    def mission_brief_path(self) -> Path:
        return self.job_dir / "mission_brief.json"

    @property
    def deploy_config_path(self) -> Path:
        return self.serving_dir / self._base.deploy_config_filename

    @property
    def retry_history_path(self) -> Path:
        return self.job_dir / "retry_history.json"

    # ── Workspace management ─────────────────────────────────────────

    def ensure_workspace(self) -> Path:
        """Create all job subdirectories. Returns job_dir."""
        for d in [
            self.checkpoints_dir,
            self.logs_dir,
            self.metrics_dir,
            self.artifacts_dir,
            self.temp_dir,
            self.plots_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)
        return self.job_dir

    # ── Docker volume mounts ─────────────────────────────────────────

    @property
    def docker_mounts(self) -> dict[str, dict[str, str]]:
        """Consistent Docker volume mounts for training/sandbox containers.

        Returns:
            {host_path: {"bind": container_path, "mode": "ro|rw"}}
        """
        return {
            self._base.scripts.resolve().as_posix(): {
                "bind": self._base.container_scripts,
                "mode": "ro",
            },
            self._base.data.resolve().as_posix(): {
                "bind": self._base.container_data,
                "mode": "ro",
            },
            self.job_dir.resolve().as_posix(): {
                "bind": self._base.container_outputs,
                "mode": "rw",
            },
        }

    @property
    def container_env(self) -> dict[str, str]:
        """Environment variables to pass into the Docker container."""
        return {
            "JOB_ID": self.job_id,
            "DATA_DIR": self._base.container_data,
            "OUTPUTS_DIR": self._base.container_outputs,
            "SCRIPTS_DIR": self._base.container_scripts,
            "PYTHONUNBUFFERED": "1",
        }

    # ── Training data ────────────────────────────────────────────────

    @property
    def training_data_csv_path(self) -> Path:
        return self.job_dir / "training_data.csv"

    def dataset_copy_target(self, filename: str) -> Path:
        return self._base.data / filename

    # ── String helpers (for ergonomics in f-strings) ─────────────────

    def __str__(self) -> str:
        return str(self.job_dir)

    def __fspath__(self) -> str:
        return str(self.job_dir)


# ── Helpers ────────────────────────────────────────────────────────────────


def _resolve_dir(env_var: str, default: str) -> Path:
    raw = os.getenv(env_var, default)
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def _resolve_path(env_var: str, default: str) -> Path:
    raw = os.getenv(env_var, default)
    p = Path(raw)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


# ── Path resolution (resolves fresh from env each call) ──────────────────


def get_paths() -> RuntimePaths:
    return RuntimePaths.resolve()


def get_job_paths(job_id: str) -> JobPaths:
    return RuntimePaths.resolve().for_job(job_id)

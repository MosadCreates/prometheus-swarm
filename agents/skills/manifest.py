"""SkillManifest — validated schema for a skill's SKILL.md YAML frontmatter.

The manifest is the single source of truth for routing (``agents``), typing
(``code`` vs ``instruction``), execution bounds (``max_runtime_s``,
``max_memory_mb``), and authenticity (``publisher`` / ``signature``). Designed
so the production schema is final from day one — no retrofitting later.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

# Agent names are lowercase-normalized everywhere (scout, forge, furnace,
# dissect, arbiter, harbor). Manifest files may use any case.
VALID_AGENTS = {"scout", "forge", "furnace", "dissect", "arbiter", "harbor"}
VALID_TYPES = {"code", "instruction"}
VALID_SOURCES = {"local", "git", "registry", "md"}

_NAME_RE = re.compile(r"^[a-z0-9_]+$")

DEFAULT_MAX_RUNTIME_S = 30
DEFAULT_MAX_MEMORY_MB = 512


class SkillManifest(BaseModel):
    """Validated skill manifest. Scan-time fields (path/root/instruction_body)
    are populated by the loader, not by the author."""

    # ── Author fields (SKILL.md frontmatter) ───────────────────────────
    name: str
    version: str = "1.0.0"
    description: str = ""
    category: str = "general"
    agents: list[str] = Field(default_factory=lambda: ["all"])
    type: str = "code"
    deterministic: bool = True
    requires_llm: bool = False
    entry_class: str | None = None
    entry_module: str = "skill.py"
    dependencies: list[str] = Field(default_factory=list)
    min_prometheus_version: str | None = None
    inputs_schema: dict[str, Any] = Field(default_factory=dict)
    outputs_schema: dict[str, Any] = Field(default_factory=dict)
    permissions: list[str] = Field(default_factory=list)
    publisher: str | None = None
    signature: str | None = None
    trusted: bool = False
    source: str = "local"
    source_url: str | None = None
    # Execution bounds (subprocess isolation / Cross-cutting contract #2).
    max_runtime_s: int = DEFAULT_MAX_RUNTIME_S
    max_memory_mb: int = DEFAULT_MAX_MEMORY_MB

    # ── Scan/install-time fields (not authored) ────────────────────────
    path: str = ""
    root: str = ""  # "bundled" | "installed"
    instruction_body: str = ""

    @field_validator("name")
    @classmethod
    def _name_must_be_snake(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                f"skill name {v!r} must be lowercase snake_case (letters/digits/underscore)"
            )
        return v

    @field_validator("type")
    @classmethod
    def _type_valid(cls, v: str) -> str:
        if v not in VALID_TYPES:
            raise ValueError(f"type must be one of {sorted(VALID_TYPES)}")
        return v

    @field_validator("source")
    @classmethod
    def _source_valid(cls, v: str) -> str:
        if v not in VALID_SOURCES:
            raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}")
        return v

    @field_validator("agents")
    @classmethod
    def _agents_valid(cls, v: list[str]) -> list[str]:
        normalized = [a.strip().lower() for a in v]
        for a in normalized:
            if a != "all" and a not in VALID_AGENTS:
                raise ValueError(f"unknown agent {a!r}; valid: {sorted(VALID_AGENTS)}")
        return normalized

    @field_validator("max_runtime_s", "max_memory_mb")
    @classmethod
    def _bounds_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("execution bounds must be positive")
        return v

    def routes_to(self, agent: str) -> bool:
        """True if this skill is routable to ``agent`` (lowercase)."""
        return "all" in self.agents or agent.lower() in self.agents

    def is_instruction(self) -> bool:
        return self.type == "instruction"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into (frontmatter dict, body). Empty dict if absent."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    if len(lines) < 2:
        return {}, text
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text
    block = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :]).strip()
    try:
        data = yaml.safe_load(block) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, body


def load_manifest_from_dir(skill_dir: Path, root: str = "installed") -> SkillManifest | None:
    """Read + validate SKILL.md in ``skill_dir``.

    Returns ``None`` when the dir has no valid SKILL.md — the loader's
    tolerance for a mid-install state (a concurrent ``install --force`` must
    never yield a torn skill to a running job).
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return None
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    data, body = parse_frontmatter(text)
    if not data:
        return None
    try:
        m = SkillManifest.model_validate(data)
    except Exception:
        return None
    m.path = str(skill_dir.resolve())
    m.root = root
    if m.is_instruction():
        m.instruction_body = body
    return m


def check_min_version(min_version: str | None) -> bool:
    """True if ``min_version`` is satisfied by the current Prometheus version.

    The version constant lives in ``prometheus/main.py`` — imported lazily so
    that importing ``agents.skills`` never drags in the click CLI. Falls back
    to ``True`` (no constraint) when the constant cannot be read.
    """
    if not min_version:
        return True
    try:
        from packaging.version import Version

        from prometheus.main import VERSION

        return Version(VERSION) >= Version(min_version)
    except Exception:
        return True

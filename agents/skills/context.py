"""SkillContext / SkillResult — the JSON-safe contract every skill speaks.

Cross-cutting contract #1: both payloads must round-trip through JSON in BOTH
execution modes (in-process and subprocess worker). No DataFrames, no `Path`
objects, no numpy arrays. ``paths`` is a plain ``dict[str, str]``; heavy
outputs (DataFrames, generated scripts, plots) are written to the per-skill
``work_dir`` and returned as file paths in ``SkillResult.artifacts`` — never
embedded in ``detail``. This is what lets a skill migrate bundled→installed
without changing a line.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class SkillContext(BaseModel):
    """Everything a skill needs to do useful work, JSON-serializable.

    ``brief`` / ``spec`` / ``paths`` hold the *serializable subset* of an
    agent's mission context (job brief, mission spec, engineering plan). A
    skill that needs a DataFrame reads its CSV from ``paths`` and writes heavy
    outputs into ``work_dir``.
    """

    job_id: str = ""
    agent: str = ""
    brief: dict[str, Any] = Field(default_factory=dict)
    spec: dict[str, Any] = Field(default_factory=dict)
    paths: dict[str, str] = Field(default_factory=dict)
    work_dir: str = ""
    kwargs: dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class SkillResult(BaseModel):
    """Result of a skill run. ``ok=False`` is the *contract* — never an exception.

    ``reason`` carries a human/machine-readable failure explanation so the
    agent's fallback path (Cross-cutting contract #4) knows why the skill
    could not deliver.
    """

    skill: str = ""
    ok: bool = False
    detail: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    skill_version: str = ""
    reason: str = ""

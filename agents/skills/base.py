"""Skill ABC — the contract every skill entry class implements.

Class attributes mirror the manifest's routing/typing fields and are the
structural-check target for the install validation gate (a skill must subclass
``Skill`` and implement ``async run``). The manifest's YAML frontmatter remains
the authoritative source for routing; these attributes are what the loader and
installer can verify without parsing YAML.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agents.skills.context import SkillContext, SkillResult


class Skill(ABC):
    """Base class for all skills (code skills). Subclass and implement ``run``."""

    name: str = ""
    description: str = ""
    category: str = "general"
    #: Agent routing — "all" or a subset of {scout, forge, furnace, dissect,
    #: arbiter, harbor}. Read-only: never mutate a shared class attribute.
    agents: tuple[str, ...] = ("all",)
    type: str = "code"
    deterministic: bool = True
    requires_llm: bool = False

    @abstractmethod
    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        """Execute the skill against ``ctx`` and return a ``SkillResult``.

        Never raise to report failure — return ``SkillResult(ok=False,
        reason=...)`` instead (Cross-cutting contract #4).
        """

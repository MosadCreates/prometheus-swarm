"""Summarize a Dissect cascade attempt into a compact stats block.

Deterministic, pure. Aggregates the cascade path (levels tried + outcomes)
plus the final resolution into a compact summary that Dissect logs after
``run_cascade`` — the research evidence of which cascade level resolves which
error category.
"""

from __future__ import annotations

from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult


class CascadeStatsSkill(Skill):
    name = "cascade_stats"
    description = "Summarize a cascade attempt (levels tried, resolution) compactly"
    category = "analysis"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        level = kwargs.get("level")
        resolved = kwargs.get("resolved", False)
        is_terminal = kwargs.get("is_terminal", False)
        cascade_path = kwargs.get("cascade_path", []) or []
        category = kwargs.get("category", "") or ""

        steps = [s for s in cascade_path if isinstance(s, dict)]
        levels_tried = sorted({s.get("level") for s in steps})
        outcomes = [str(s.get("outcome", "?")) for s in steps]
        summary = (
            f"cascade: levels=[{','.join(str(lvl) for lvl in levels_tried) or '-'}] "
            f"outcomes=[{','.join(outcomes) or '-'}] "
            f"final_level={level} resolved={resolved} terminal={is_terminal}"
            + (f" category={category}" if category else "")
        )
        return SkillResult(
            skill=self.name,
            ok=True,
            detail={
                "levels_tried": levels_tried,
                "outcomes": outcomes,
                "final_level": level,
                "resolved": bool(resolved),
                "is_terminal": bool(is_terminal),
                "summary": summary,
            },
        )

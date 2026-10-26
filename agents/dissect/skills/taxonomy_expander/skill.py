"""Suggest a candidate taxonomy category for a weakly-classified crash.

Deterministic, pure. When the taxonomy's match confidence is low, propose a
candidate category + regex from keyword heuristics in the exception message,
so *unseen* error shapes surface to the researcher (the raw material for
expanding the taxonomy). Never auto-applies.
"""

from __future__ import annotations

import re
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

_HINTS = [
    ("out_of_memory", r"out of memory|killed|insufficient memory|cuda.*memory|allocate"),
    ("shape_mismatch", r"shapes?\b.*(?:not aligned|broadcast|mismatch)|incompatible dimensions"),
    ("missing_column", r"column.*not (?:found|present)|keyerror:?.*'[\w ]+'"),
    ("label_leakage", r"\bleak|target.*in (?:features|train)|label.*column"),
    ("dataset_empty", r"\bempty\b|no (?:samples|rows)|not enough (?:data|samples)"),
    ("dtype_mismatch", r"\bdtype\b|cannot cast|expected.*got"),
    ("convergence_failure", r"convergence|divergen|explod|gradient.*nan|\bnan\b"),
    ("unsupported_argument", r"unsupported|got an unexpected keyword|invalid argument"),
]


class TaxonomyExpanderSkill(Skill):
    name = "taxonomy_expander"
    description = "Propose a candidate taxonomy category for weakly-matched crashes"
    category = "analysis"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        exception_message = kwargs.get("exception_message", "") or ""
        exception_type = kwargs.get("exception_type", "") or ""
        current = kwargs.get("category", "") or ""
        try:
            confidence = float(kwargs.get("confidence", 1.0) or 1.0)
        except (TypeError, ValueError):
            confidence = 1.0

        if confidence >= 0.5:
            return SkillResult(
                skill=self.name, ok=True, detail={"suggested": None, "reason": "high confidence"}
            )

        text = f"{exception_type} {exception_message}".lower()
        matches = [name for name, pattern in _HINTS if re.search(pattern, text)]
        if not matches:
            return SkillResult(
                skill=self.name,
                ok=True,
                detail={"suggested": None, "reason": "no known hint", "low_confidence": True},
            )
        suggested = matches[0]
        return SkillResult(
            skill=self.name,
            ok=True,
            detail={
                "suggested": suggested,
                "current": current,
                "reason": f"matched hint '{suggested}' at low confidence",
                "low_confidence": True,
                "candidate_pattern": next(p for n, p in _HINTS if n == suggested),
            },
        )

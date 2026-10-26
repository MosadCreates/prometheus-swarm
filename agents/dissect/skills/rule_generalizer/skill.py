"""Generalize a successful patch into a reusable message-pattern rule.

Deterministic, pure. Derives a rule from a successful repair: the error
category, a regex built by blanking out volatile tokens (numbers, hex, quoted
literals) in the exception message, and the patch diff that fixed it. Surfaced
for the researcher; never auto-applied.
"""

from __future__ import annotations

import re
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

_TOKEN = re.compile(r"0x[0-9a-fA-F]+|\b\d[\d,.:]*\b|'[^']*'|\"[^\"]*\"")


def _pattern_regex(message: str) -> str:
    """Build a regex from ``message`` with volatile tokens as ``.*?`` wildcards."""
    parts: list[str] = []
    last = 0
    for m in _TOKEN.finditer(message):
        parts.append(re.escape(message[last : m.start()]))
        parts.append(".*?")
        last = m.end()
    parts.append(re.escape(message[last:]))
    return "^" + "".join(parts) + "$"


class RuleGeneralizerSkill(Skill):
    name = "rule_generalizer"
    description = "Generalize a successful repair into a reusable message-pattern rule"
    category = "learning"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        category = kwargs.get("category", "") or ""
        exception_message = kwargs.get("exception_message", "") or ""
        diff = kwargs.get("diff", "") or ""
        patch_id = kwargs.get("patch_id", "") or ""

        message = exception_message.strip()
        if not message:
            return SkillResult(
                skill=self.name, ok=True, detail={"rule": None, "reason": "empty message"}
            )
        readable = _TOKEN.sub("<*>", message)
        rule = {
            "category": category,
            "message_pattern": readable,
            "message_pattern_regex": _pattern_regex(message),
            "patch_diff": diff[:500],
            "patch_id": patch_id,
        }
        return SkillResult(skill=self.name, ok=True, detail={"rule": rule})

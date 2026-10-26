"""Generate structural post-conditions a patched script must satisfy.

Deterministic, pure. Emits named assertions about the *patched* script that
Dissect logs alongside the sandbox result. Never fatal — returns ``ok=True``
with the assertion list so the caller decides how to use it.
"""

from __future__ import annotations

import ast
import re
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

#   name 'foo' is not defined  |  cannot import name 'foo'  |  No module named 'foo'
_QUOTED = re.compile(r"'([^']+)'")
_ENTRY_CALL = re.compile(r"\b(train|fit|run_?training)\b")
_DEF_RE = re.compile(r"^(?:class|def|async def)\s+([A-Za-z_][A-Za-z0-9_]*)")


class PatchAssertionGeneratorSkill(Skill):
    name = "patch_assertion_generator"
    description = "Generate structural post-conditions for a patched training script"
    category = "validation"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        original = ctx.kwargs.get("original_script", "") or ""
        patched = ctx.kwargs.get("patched_script", "") or ""
        exception_message = ctx.kwargs.get("exception_message", "") or ""
        exception_type = ctx.kwargs.get("exception_type", "") or ""
        diff = ctx.kwargs.get("diff", "") or ""

        if not patched:
            return SkillResult(
                skill=self.name, ok=True, detail={"assertions": [], "reason": "no patched script"}
            )

        results = [
            ("patch_is_ast_valid", self._ast_valid(patched)),
            (
                "no_duplicate_top_level_defs",
                self._no_duplicate_defs(patched),
            ),
            (
                "crash_name_resolved",
                self._crash_name_resolved(exception_type, exception_message, patched),
            ),
            ("entry_preserved", self._entry_preserved(original, patched)),
        ]
        assertions = [{"name": n, "passed": p, "detail": ""} for n, p in results]
        return SkillResult(
            skill=self.name,
            ok=True,
            detail={
                "assertions": assertions,
                "diff": diff,
                "passed": all(a["passed"] for a in assertions),
            },
        )

    @staticmethod
    def _ast_valid(code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError:
            return False

    @staticmethod
    def _no_duplicate_defs(code: str) -> bool:
        seen = set()
        for line in code.splitlines():
            m = _DEF_RE.match(line.strip())
            if m:
                if m.group(1) in seen:
                    return False
                seen.add(m.group(1))
        return True

    @staticmethod
    def _crash_name_resolved(exception_type: str, message: str, code: str) -> bool:
        if exception_type not in ("NameError", "ImportError"):
            return True
        m = _QUOTED.search(message or "")
        if not m:
            return True
        name = m.group(1)
        return bool(re.search(rf"\b{re.escape(name)}\b", code or ""))

    @staticmethod
    def _entry_preserved(original: str, patched: str) -> bool:
        if not _ENTRY_CALL.search(original or ""):
            return True
        return bool(_ENTRY_CALL.search(patched or ""))

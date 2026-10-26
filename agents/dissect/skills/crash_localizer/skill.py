"""Locate the failing frame of a training crash from its traceback.

Deterministic, pure: parses the ``traceback`` string (and falls back to the
exception message) to find the script-local frame where the failure occurred.
Returns ``ok=True`` always — a non-locatable crash is a *successful negative*
result, not a skill failure — with ``locatable=False`` in that case.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

#   File "C:/.../scripts/training_script_abc.py", line 42, in <module>
_FRAME_RE = re.compile(r'File "([^"]+)", line (\d+), in (.+)$')
#   line 42, in train
_LINE_RE = re.compile(r"line (\d+), in ([^ ]+)$")


def _script_basename(path: str) -> str:
    try:
        return Path(path).name
    except Exception:
        return ""


class CrashLocalizerSkill(Skill):
    name = "crash_localizer"
    description = "Locate the failing script frame/line from a crash traceback"
    category = "debugging"
    agents = ("dissect",)
    deterministic = True

    async def run(self, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        script_path = ctx.paths.get("script_path") or ctx.kwargs.get("script_path", "") or ""
        traceback_text = ctx.kwargs.get("traceback", "") or ""
        exc_message = ctx.kwargs.get("exception_message", "") or ""
        script_snippet = ctx.kwargs.get("script_snippet", "") or ""

        frames = self._parse_frames(traceback_text)
        target = _script_basename(script_path)

        # Prefer a frame inside the failing training script; else the last frame.
        chosen = None
        for f in frames:
            if target and _script_basename(f["file"]) == target:
                chosen = f
                break
        if chosen is None and frames:
            chosen = frames[-1]

        if chosen is not None:
            return SkillResult(
                skill=self.name,
                ok=True,
                detail={
                    "locatable": True,
                    "file": chosen["file"],
                    "line": chosen["line"],
                    "function": chosen["function"],
                    "snippet": self._snippet_for(script_snippet, chosen["line"]),
                    "confidence": 0.9 if _script_basename(chosen["file"]) else 0.6,
                },
            )

        # No traceback: try the message form "line 42, in train"
        m = _LINE_RE.search(exc_message)
        if m:
            return SkillResult(
                skill=self.name,
                ok=True,
                detail={
                    "locatable": True,
                    "file": "",
                    "line": int(m.group(1)),
                    "function": m.group(2),
                    "snippet": "",
                    "confidence": 0.4,
                },
            )
        return SkillResult(
            skill=self.name,
            ok=True,
            detail={
                "locatable": False,
                "line": None,
                "function": None,
                "snippet": "",
                "confidence": 0.0,
            },
        )

    @staticmethod
    def _parse_frames(traceback_text: str) -> list[dict[str, Any]]:
        frames = []
        for line in traceback_text.splitlines():
            m = _FRAME_RE.match(line.strip())
            if m:
                frames.append({"file": m.group(1), "line": int(m.group(2)), "function": m.group(3)})
        return frames

    @staticmethod
    def _snippet_for(script_snippet: str, line: int) -> str:
        if not script_snippet:
            return ""
        lines = script_snippet.splitlines()
        if 1 <= line <= len(lines):
            return lines[line - 1].strip()[:120]
        return ""

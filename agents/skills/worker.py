"""Subprocess worker entry — ``python -m agents.skills.worker <skill_dir> <ctx.json>``.

The security boundary for installed skills: the parent spawns this module in a
subprocess, writes the JSON-serialized ``SkillContext`` to a file, and the
worker loads the skill, runs it, and prints a JSON ``SkillResult`` on stdout.
The parent kills the process on timeout / memory cap, so even a hung or
runaway skill can only take down itself — never the orchestrator.

Errors are **reported, not raised**: any failure becomes a ``SkillResult(
ok=False, reason=...)`` on stdout so the parent's fallback path (Cross-cutting
contract #4) always has something to degrade to.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from agents.skills.context import SkillContext, SkillResult
from agents.skills.loader import load_skill_class
from agents.skills.manifest import load_manifest_from_dir


def _emit(result: SkillResult) -> None:
    try:
        payload = result.model_dump_json()
    except Exception as e:
        payload = SkillResult(
            skill=result.skill,
            ok=False,
            reason=f"result not JSON-serializable: {e}",
        ).model_dump_json()
    print(payload)
    sys.stdout.flush()


async def _main(skill_dir: str, ctx_file: str) -> None:
    manifest = load_manifest_from_dir(Path(skill_dir), root="installed")
    if manifest is None:
        _emit(SkillResult(skill="", ok=False, reason=f"no valid SKILL.md in {skill_dir}"))
        return
    if manifest.is_instruction():
        _emit(
            SkillResult(
                skill=manifest.name, ok=False, reason="instruction skill has no runnable entry"
            )
        )
        return
    try:
        ctx = SkillContext.model_validate_json(Path(ctx_file).read_text(encoding="utf-8"))
    except Exception as e:
        _emit(SkillResult(skill=manifest.name, ok=False, reason=f"invalid context: {e}"))
        return
    cls = load_skill_class(manifest)
    if cls is None:
        _emit(
            SkillResult(skill=manifest.name, ok=False, reason="no Skill subclass in entry module")
        )
        return
    try:
        skill = cls()
        result = await skill.run(ctx, **ctx.kwargs)
        if not isinstance(result, SkillResult):
            result = SkillResult(
                skill=manifest.name, ok=False, reason="run() returned a non-SkillResult"
            )
    except Exception as e:
        result = SkillResult(
            skill=manifest.name, ok=False, reason=f"skill raised: {type(e).__name__}: {e}"
        )
    if not result.skill:
        result.skill = manifest.name
    _emit(result)


def main() -> None:
    if len(sys.argv) < 3:
        _emit(
            SkillResult(
                skill="",
                ok=False,
                reason="usage: python -m agents.skills.worker <skill_dir> <ctx.json>",
            )
        )
        return
    asyncio.run(_main(sys.argv[1], sys.argv[2]))


if __name__ == "__main__":
    main()

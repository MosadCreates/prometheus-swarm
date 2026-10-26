"""SkillRegistry — the agent's single entry point to skills.

``SkillRegistry.for_agent(agent_name)`` returns a registry scoped to one
agent (mounted on ``BaseAgent`` as ``self.skills`` in Phase 1). It scans the
filesystem **on construction** — so a freshly installed skill is picked up by
the next job's agents with no daemon restart (the hot-reload mechanism; the
orchestrator constructs agents per job).

Cross-cutting contract #4 (failure fallback): ``run()`` **never raises**. A
missing / uninstalled / broken / halted skill returns
``SkillResult(ok=False, reason=...)`` so the agent's deterministic fallback
path stays authoritative until the skill proves stable.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult
from agents.skills.loader import load_skill_class, scan_roots
from agents.skills.manifest import SkillManifest, check_min_version
from agents.skills.subprocess_runner import run_skill_subprocess
from shared.metrics import SKILL_RUN_DURATION, SKILL_RUNS


class SkillRegistry:
    """Scanned skill index + dispatcher. Scoped to an agent when ``agent`` given."""

    def __init__(
        self,
        agent: str | None = None,
        *,
        skills_root: Path | None = None,
        bundled_roots: list[Path] | None = None,
        scan: bool = True,
    ) -> None:
        #: Agent scope (lowercase). ``None`` = unscoped (all skills visible).
        self.agent = agent.lower() if agent else None
        self.skills_root = skills_root
        self.bundled_roots = bundled_roots
        #: Optional attached Redis client used to record the evidence-gate
        #: stats; the agent connector attaches its already-connected client.
        self.redis_client: Any = None
        #: Job context for agent-event emission (attached by ``BaseAgent``).
        self.job_id: str | None = None
        self._manifests: dict[str, SkillManifest] = {}
        self._classes: dict[str, type[Skill] | None] = {}
        if scan:
            self.reload()

    @classmethod
    def for_agent(cls, agent_name: str) -> "SkillRegistry":
        """Agent-scoped registry — what ``BaseAgent`` constructs (Phase 1)."""
        return cls(agent=agent_name)

    def reload(self) -> None:
        """Re-scan roots. Installed skills shadow same-named bundled ones."""
        by_name: dict[str, SkillManifest] = {}
        for m in scan_roots(bundled_roots=self.bundled_roots, skills_root=self.skills_root):
            prev = by_name.get(m.name)
            if prev is None or (prev.root == "bundled" and m.root == "installed"):
                by_name[m.name] = m
        self._manifests = by_name
        self._classes = {}

    # ── Index views ────────────────────────────────────────────────────

    def _routes(self, m: SkillManifest) -> bool:
        return self.agent is None or m.routes_to(self.agent)

    def get_all(self) -> list[SkillManifest]:
        return list(self._manifests.values())

    def list(self) -> list[SkillManifest]:
        """Manifests visible to this registry's agent scope."""
        return [m for m in self._manifests.values() if self._routes(m)]

    def get(self, name: str) -> SkillManifest | None:
        m = self._manifests.get(name)
        return m if m is not None and self._routes(m) else None

    def instruction_skills(self, agent: str | None = None) -> list[SkillManifest]:
        """Trusted instruction skills routable to ``agent`` (or this scope)."""
        scope = (agent or self.agent or "").lower()
        out = []
        for m in self._manifests.values():
            if not m.is_instruction() or not m.trusted:
                continue
            if not scope or m.routes_to(scope):
                out.append(m)
        return out

    def instruction_text(self, agent: str | None = None, *, max_chars: int = 6000) -> str:
        """Concatenated bodies of trusted instruction skills routable to ``agent``.

        Returns an empty string when there are none, so call sites can append
        unconditionally. Bodies are bounded by ``max_chars`` — a runaway skill
        doc must never blow up an LLM prompt. Only ``trusted`` instruction
        skills are injected; deterministic run paths never touch them.
        """
        blocks: list[str] = []
        used = 0
        for m in self.instruction_skills(agent):
            body = (m.instruction_body or "").strip()
            if not body:
                continue
            block = f"## Skill: {m.name} ({m.description})\n{body}"
            if used + len(block) > max_chars:
                block = block[: max_chars - used]
            blocks.append(block)
            used += len(block)
            if used >= max_chars:
                break
        return "\n\n".join(blocks)

    # ── Execution ──────────────────────────────────────────────────────

    async def run(self, name: str, ctx: SkillContext, **kwargs: Any) -> SkillResult:
        """Run ``name`` and return a SkillResult. **Never raises.**

        Bundled skills run in-process; installed skills run in the subprocess
        worker (the security boundary). Optional ``inputs_schema`` /
        ``outputs_schema`` are enforced here when declared.
        """
        m = self.get(name)
        if m is None:
            return SkillResult(
                skill=name, ok=False, reason="skill not found or not routed to this agent"
            )
        if m.is_instruction():
            return SkillResult(
                skill=name, ok=False, reason="instruction skill has no runnable entry"
            )
        if not check_min_version(m.min_prometheus_version):
            return SkillResult(
                skill=name,
                ok=False,
                reason=f"skill requires prometheus >= {m.min_prometheus_version}",
            )
        if m.inputs_schema and not _schema_matches(m.inputs_schema, ctx.model_dump()):
            return SkillResult(
                skill=name, ok=False, reason="inputs_schema mismatch on SkillContext"
            )
        ctx = ctx.model_copy(update={"kwargs": {**ctx.kwargs, **kwargs}})

        started = time.perf_counter()
        try:
            if m.root == "installed":
                result = await run_skill_subprocess(m, ctx)
            else:
                result = await self._run_in_process(m, ctx)
        except Exception as e:  # runner-level failure — never raises to the agent
            result = SkillResult(
                skill=name, ok=False, reason=f"skill runner failed: {type(e).__name__}: {e}"
            )
        if not result.skill:
            result.skill = name
        result.duration_ms = int((time.perf_counter() - started) * 1000)

        if m.outputs_schema and not _schema_matches(m.outputs_schema, result.model_dump()):
            result = SkillResult(
                skill=name,
                ok=False,
                reason="outputs_schema mismatch on SkillResult",
                duration_ms=result.duration_ms,
            )

        try:  # metrics must never break a skill run
            SKILL_RUNS.labels(
                agent=self.agent or "", skill=name, ok="true" if result.ok else "false"
            ).inc()
            SKILL_RUN_DURATION.labels(agent=self.agent or "", skill=name).observe(
                result.duration_ms / 1000.0
            )
        except Exception:
            pass
        await self._record_stats(name, result.ok)
        await self._emit_subaction(name, result)
        return result

    async def _emit_subaction(self, name: str, result: SkillResult) -> None:
        """Surface the skill invocation on the subaction stream (guarded).

        The stream renderer turns this into a per-skill line ("Scout used
        skill dataset_profiler") for free — no agent code changes needed. Pure
        best-effort: a missing Redis client, a job-less registry, or a publish
        failure all silently no-op.
        """
        r = self.redis_client
        if r is None or not self.job_id:
            return
        try:
            from bus.agent_events import emit_subaction_progress

            agent_label = self.agent.title() if self.agent else "Agent"
            await emit_subaction_progress(
                r,
                self.job_id,
                agent_label,
                f"used skill {name}",
                1.0,
                "done" if result.ok else "error",
            )
        except Exception:
            pass

    async def _run_in_process(self, m: SkillManifest, ctx: SkillContext) -> SkillResult:
        cls = self._class_for(m)
        if cls is None:
            return SkillResult(skill=m.name, ok=False, reason="could not load skill entry class")
        try:
            skill = cls()
            result = await skill.run(ctx, **ctx.kwargs)
            if not isinstance(result, SkillResult):
                result = SkillResult(
                    skill=m.name, ok=False, reason="run() returned a non-SkillResult"
                )
        except Exception as e:
            result = SkillResult(
                skill=m.name, ok=False, reason=f"skill raised: {type(e).__name__}: {e}"
            )
        if not result.skill:
            result.skill = m.name
        return result

    def _class_for(self, m: SkillManifest) -> type[Skill] | None:
        if m.name not in self._classes:
            self._classes[m.name] = load_skill_class(m)
        return self._classes[m.name]

    # ── Evidence-gate stats (promotion mechanism) ──────────────────────

    async def record_fallback(self, name: str) -> None:
        """Call-site hook: a fallback branch fired for ``name``. Best-effort."""
        r = self.redis_client
        if r is None:
            return
        key = self._stats_key(name)
        try:
            await r.hincrby(key, "fallback_fired", 1)
            await r.hset(key, "consecutive_ok", 0)
        except Exception:
            pass

    async def _record_stats(self, name: str, ok: bool) -> None:
        r = self.redis_client
        if r is None:
            return
        key = self._stats_key(name)
        try:
            await r.hincrby(key, "total_runs", 1)
            if ok:
                await r.hincrby(key, "ok_runs", 1)
                await r.hincrby(key, "consecutive_ok", 1)
            else:
                await r.hset(key, "consecutive_ok", 0)
        except Exception:
            pass

    def _stats_key(self, name: str) -> str:
        return f"skill:{name}:{self.agent or 'all'}:stats"


def _schema_matches(schema: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Minimal structural check: required keys exist with a compatible type.

    ``schema`` maps a key to a type name in {"str", "int", "float", "bool",
    "list", "dict"}. Missing/extra keys are allowed unless listed under
    ``required``. This is the declare-or-skip enforcement point — the optional
    ``inputs_schema``/``outputs_schema`` contract, kept deliberately shallow so
    the bundled-skill roadmap does not drown in schema debt.
    """
    TYPE_CHECKERS = {
        "str": lambda v: isinstance(v, str),
        "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "bool": lambda v: isinstance(v, bool),
        "list": lambda v: isinstance(v, list),
        "dict": lambda v: isinstance(v, dict),
    }
    fields = schema.get("fields", schema)
    required = schema.get("required", [])
    if not isinstance(fields, dict):
        return True
    for key in required:
        if key not in payload:
            return False
    for key, type_name in fields.items():
        if key in payload and payload[key] is not None:
            checker = TYPE_CHECKERS.get(type_name)
            if checker is not None and not checker(payload[key]):
                return False
    return True

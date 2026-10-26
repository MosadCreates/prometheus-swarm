"""SkillService — the CLI's window onto the skill platform.

Owns the promotion store (``~/.prometheus/promotions.json``) and the
evidence-gate reads (Redis ``skill:{name}:{agent}:stats``) on top of the
Phase 0/1 platform (``agents/skills``). All paths and the Redis client are
constructor-overridable so the CLI and its tests share one wiring.

Promotion semantics (from the plan):
- a skill is *stable* only after an **evidence gate** (N consecutive ok runs,
  zero fallbacks, recorded by ``SkillRegistry.run``) **and** a human
  ``skill promote`` — ``stable`` lives in promotion state, never in the signed
  SKILL.md (mutating the signed manifest would break its signature);
- removal stays a code change: ``check_orphans()`` lists stable skills whose
  agent call site still carries a fallback branch, so "proven stable →
  fallback removed" is mechanically checkable instead of a forgotten TODO.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.skills import (
    InstallResult,
    SkillManifest,
    SkillRegistry,
    add_publisher,
    build_dry_run_context,
    default_skills_root,
    install_source,
    is_trusted_publisher,
    load_publishers,
    save_publishers,
    validate_structural,
    verify_manifest_signature,
)

DEFAULT_PROMOTE_CONSECUTIVE_OK = 10


# ── Promotion store (~/.prometheus/promotions.json) ───────────────────────


def promotions_path() -> Path:
    return Path.home() / ".prometheus" / "promotions.json"


def load_promotions(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or promotions_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_promotions(store: dict[str, dict[str, Any]], path: Path | None = None) -> None:
    p = path or promotions_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(store, indent=2, sort_keys=True), encoding="utf-8")


def _repo_agents_root() -> Path:
    """agents/ dir of this repo (call sites for check-orphans)."""
    return Path(__file__).resolve().parents[2] / "agents"


class SkillService:
    """Wraps the platform for the CLI; every method degrades to a clear message."""

    def __init__(
        self,
        *,
        skills_root: Path | None = None,
        publishers: Path | None = None,
        promotions: Path | None = None,
        agents_root: Path | None = None,
        redis_client: Any = None,
        promote_consecutive_ok: int = DEFAULT_PROMOTE_CONSECUTIVE_OK,
    ) -> None:
        self.skills_root = skills_root
        self.publishers = publishers
        self.promotions = promotions
        self.agents_root = agents_root or _repo_agents_root()
        #: Evidence-gate Redis client (aioredis in production; injected in tests).
        self.redis_client = redis_client
        self.promote_consecutive_ok = promote_consecutive_ok

    # ── Registry ─────────────────────────────────────────────────────────

    def _registry(self, agent: str | None = None) -> SkillRegistry:
        reg = SkillRegistry(agent=agent, skills_root=self.skills_root)
        reg.redis_client = self.redis_client
        return reg

    def find(self, name: str, agent: str | None = None) -> SkillManifest | None:
        return self._registry(agent).get(name)

    def info(self, name: str) -> SkillManifest | None:
        return self._registry().get(name)

    def list(self, agent: str | None = None, installed_only: bool = False) -> list[SkillManifest]:
        reg = self._registry(agent)
        out = []
        for m in reg.get_all():
            if installed_only and m.root != "installed":
                continue
            if agent and not m.routes_to(agent):
                continue
            out.append(m)
        return out

    def status(self, m: SkillManifest) -> tuple[str, str]:
        """Cheap (no-import) active/inactive status + one-line reason."""
        if m.is_instruction():
            if not (m.instruction_body or "").strip():
                return "inactive", "instruction body is empty"
            return "active", "ok"
        module = Path(m.path) / m.entry_module
        if not module.is_file():
            return "inactive", f"missing {m.entry_module}"
        return "active", "ok"

    def structural(self, m: SkillManifest) -> tuple[bool, str, list[str]]:
        """Deep structural validation (imports skill code) — for ``skill info``."""
        return validate_structural(m)

    # ── Install / remove / update ───────────────────────────────────────

    async def install(
        self,
        source: str,
        *,
        source_type: str | None = None,
        agents: str | None = None,
        trust: bool = False,
        force: bool = False,
        no_verify: bool = False,
        name: str | None = None,
    ) -> InstallResult:
        return await install_source(
            source,
            source_type=source_type,
            agents=agents,
            trust=trust,
            force=force,
            no_verify=no_verify,
            name=name,
            skills_root=self.skills_root,
            publishers=self.publishers,
        )

    def remove(self, name: str) -> tuple[bool, str]:
        m = self.info(name)
        if m is None:
            return False, f"skill '{name}' not found"
        if m.root == "bundled":
            return False, f"'{name}' is a bundled skill and cannot be removed"
        target = (self.skills_root or default_skills_root()) / m.name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return True, f"removed '{name}'"

    async def update(self, name: str) -> tuple[bool, str]:
        m = self.info(name)
        if m is None:
            return False, f"skill '{name}' not found"
        if m.source != "git" or not m.source_url:
            return False, f"'{name}' is not git-sourced — nothing to update"
        res = await install_source(
            m.source_url,
            source_type="git",
            agents=",".join(m.agents) if m.agents != ["all"] else None,
            trust=m.trusted,
            force=True,
            name=m.name,
            skills_root=self.skills_root,
            publishers=self.publishers,
        )
        if res.ok:
            return True, f"updated '{name}'"
        return False, res.reason

    # ── Create (scaffold) ───────────────────────────────────────────────

    def create(self, name: str, agent: str = "scout") -> tuple[bool, str]:
        target = (self.skills_root or default_skills_root()) / name
        if target.exists():
            return False, f"'{name}' already exists"
        target.mkdir(parents=True, exist_ok=True)
        manifest = (
            "---\n"
            f"name: {name}\n"
            f'version: "0.1.0"\n'
            f"description: A new {agent} skill\n"
            "category: general\n"
            f"agents: [{agent}]\n"
            "type: code\n"
            "---\n\n"
            "# {name}\n".replace("{name}", name)
        )
        skill_py = (
            "from agents.skills.base import Skill\n"
            "from agents.skills.context import SkillContext, SkillResult\n"
            "\n"
            "\n"
            f"class EntrySkill(Skill):\n"
            f"    name = {name!r}\n"
            "\n"
            "    async def run(self, ctx: SkillContext, **kwargs) -> SkillResult:\n"
            "        # ctx.brief / ctx.spec / ctx.paths are available (JSON-safe subset)\n"
            f"        return SkillResult(skill=self.name, ok=True, detail={{'job': ctx.job_id}})\n"
        )
        (target / "SKILL.md").write_text(manifest, encoding="utf-8")
        (target / "skill.py").write_text(skill_py, encoding="utf-8")
        return True, str(target)

    # ── Trust / verify ──────────────────────────────────────────────────

    def trust_publisher(self, publisher: str, public_key_pem: str) -> None:
        add_publisher(publisher, public_key_pem, path=self.publishers)

    def untrust_publisher(self, publisher: str) -> bool:
        store = load_publishers(self.publishers)
        if publisher not in store:
            return False
        del store[publisher]
        save_publishers(store, self.publishers)
        return True

    def is_publisher_trusted(self, publisher: str) -> bool:
        return is_trusted_publisher(publisher, self.publishers)

    def verify(self, name: str) -> tuple[bool, str]:
        m = self.info(name)
        if m is None:
            return False, f"skill '{name}' not found"
        if not m.publisher:
            return False, "manifest declares no publisher"
        return verify_manifest_signature(m, path=self.publishers)

    # ── Smoke test on demand ────────────────────────────────────────────

    async def test(self, name: str, agent: str | None = None) -> tuple[SkillManifest | None, Any]:
        m = self.info(name)
        if m is None:
            return None, f"skill '{name}' not found"
        if m.is_instruction():
            return m, None
        test_agent = agent or self._first_routable_agent(m)
        ctx = build_dry_run_context(test_agent, m)
        res = await self._registry(test_agent).run(m.name, ctx)
        return m, res

    @staticmethod
    def _first_routable_agent(m: SkillManifest) -> str:
        if m.agents and m.agents != ["all"]:
            return m.agents[0]
        return "scout"

    # ── Promotion (evidence-gated) ──────────────────────────────────────

    async def evidence(self, agent: str, name: str) -> dict[str, Any] | None:
        r = self.redis_client
        if r is None:
            return None
        key = f"skill:{name}:{agent}:stats"
        try:
            raw = await r.hgetall(key)
        except Exception:
            return None
        if not raw:
            return None

        def _coerce(v: Any) -> Any:
            if isinstance(v, bytes):
                v = v.decode("utf-8", errors="replace")
            if isinstance(v, str) and v.lstrip("-").isdigit():
                return int(v)
            return v

        return {k: _coerce(v) for k, v in raw.items()}

    async def promote(self, name: str, agent: str) -> tuple[bool, str, dict[str, Any] | None]:
        m = self.info(name)
        if m is None:
            return False, f"skill '{name}' not found", None
        agent = agent.lower()
        if not m.routes_to(agent):
            return False, f"skill '{name}' does not route to agent '{agent}'", None
        evidence = await self.evidence(agent, name)
        required = self.promote_consecutive_ok
        if evidence is None:
            return (
                False,
                f"evidence gate not met: no stats recorded for {name} on '{agent}' "
                f"(need {required} consecutive ok runs, zero fallbacks)",
                None,
            )
        consec = evidence.get("consecutive_ok", 0)
        if consec < required:
            return (
                False,
                f"evidence gate not met: {consec}/{required} consecutive ok runs",
                evidence,
            )
        if evidence.get("fallback_fired", 0):
            return False, "evidence gate not met: fallback branch has fired", evidence
        key = f"{name}:{agent}"
        store = load_promotions(self.promotions)
        store[key] = {
            "stable": True,
            "promoted_at": datetime.now(timezone.utc).isoformat(),
            "evidence": evidence,
        }
        save_promotions(store, self.promotions)
        return True, f"promoted '{name}' for agent '{agent}'", evidence

    def check_orphans(self) -> list[dict[str, Any]]:
        """Stable skills whose agent call site still carries a fallback branch."""
        store = load_promotions(self.promotions)
        orphans = []
        for key, info in store.items():
            if not info.get("stable"):
                continue
            name, _, agent = key.partition(":")
            if self._has_fallback_call_site(name):
                orphans.append(
                    {
                        "key": key,
                        "name": name,
                        "agent": agent,
                        "promoted_at": info.get("promoted_at", ""),
                    }
                )
        return orphans

    def _has_fallback_call_site(self, name: str) -> bool:
        """True if any agent source still calls ``skills.run(<name>)`` behind a guard.

        The call-site pattern Phase 3 uses is::

            result = await self.skills.run("skill_name", ctx)
            if not result.ok:
                <fallback>

        "Proven stable → fallback removed" means that guard (and usually the
        call) is deleted from the agent code. If a stable skill still has a
        guarded call site, it is an orphan awaiting cleanup.
        """
        pat = re.compile(rf'skills\.run\(\s*["\']{re.escape(name)}["\']')
        base = Path(self.agents_root)
        if not base.is_dir():
            return False
        for py in base.rglob("*.py"):
            try:
                lines = py.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines):
                if not pat.search(line):
                    continue
                for nxt in lines[i + 1 : i + 4]:
                    if re.search(r"if\s+not\s+\w+\.ok\b", nxt) or "fallback" in nxt.lower():
                        return True
        return False

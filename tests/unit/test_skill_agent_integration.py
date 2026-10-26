"""Phase 1 agent-integration tests.

Covers the four things that tie the Phase 0 platform to the six agents:
the ``BaseAgent`` mount (agent-scoped, every construction path), the
hot-reload mechanism (a freshly installed skill is picked up by the *next*
job's agents — no daemon restart), the subaction event emission, and the
trusted-only instruction-skill injection into Dissect's live LLM prompt and
Forge's system prompt. Bundled-vs-installed execution parity and the
run-never-raises fallback contract are re-proved here through the agent-facing
``self.skills.run(...)`` interface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agents.base import BaseAgent
from agents.dissect.agent import DissectAgent
from agents.forge.agent import FORGE_SYSTEM_PROMPT, ForgeAgent
from agents.skills.context import SkillContext
from agents.skills.registry import SkillRegistry


# ── Helpers ───────────────────────────────────────────────────────────────


def _write_skill(
    root: Path,
    name: str,
    *,
    agents=("scout",),
    type_="code",
    manifest: dict | None = None,
    code: str | None = None,
    body: str = "",
) -> Path:
    """Create a skill folder (SKILL.md + optional skill.py) and return its path."""
    skill_dir = root / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    m = {
        "name": name,
        "version": "1.0.0",
        "description": "test skill",
        "agents": list(agents),
        "type": type_,
    }
    m.update(manifest or {})
    frontmatter = "---\n" + yaml.safe_dump(m, sort_keys=False).rstrip() + "\n---\n"
    (skill_dir / "SKILL.md").write_text(frontmatter + "\n" + body, encoding="utf-8")
    if code is not None:
        (skill_dir / "skill.py").write_text(code, encoding="utf-8")
    return skill_dir


def _ok_code(name: str) -> str:
    return f"""
from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

class EntrySkill(Skill):
    name = "{name}"
    async def run(self, ctx: SkillContext, **kwargs):
        return SkillResult(skill=self.name, ok=True, detail={{"agent": ctx.agent, "job": ctx.job_id}})
"""


class _Agent(BaseAgent):
    """Minimal BaseAgent subclass — proves the mount without agent run loops."""

    @property
    def agent_name(self) -> str:
        return "Scout"

    @property
    def system_prompt(self) -> str:
        return "system prompt"

    async def run(self) -> None:
        pass


class RecordingRedis:
    """In-memory Redis stand-in recording hash writes and XADD messages."""

    def __init__(self) -> None:
        self.h: dict[str, dict] = {}
        self.streams: dict[str, list[dict]] = {}

    async def hincrby(self, key, field, amount=1):
        self.h.setdefault(key, {})
        self.h[key][field] = self.h[key].get(field, 0) + amount
        return self.h[key][field]

    async def hset(self, key, field, value):
        self.h.setdefault(key, {})[field] = value
        return 1

    async def xadd(self, stream, fields):
        self.streams.setdefault(stream, []).append(dict(fields))
        return f"{len(self.streams[stream])}-0"


def _scoped_registry(tmp_path: Path, agent: str, bundled: str) -> SkillRegistry:
    return SkillRegistry(
        agent=agent,
        bundled_roots=[tmp_path / bundled],
        skills_root=tmp_path / "none",
    )


# ── 1. BaseAgent mounts an agent-scoped registry ─────────────────────────


def test_base_agent_mount_is_agent_scoped():
    """Every agent construction mounts ``self.skills`` scoped to its own name."""
    f = ForgeAgent("j1")
    d = DissectAgent("j1")
    assert f.skills.agent == "forge"
    assert d.skills.agent == "dissect"
    assert f.skills.job_id == "j1"
    assert d.skills.job_id == "j1"


# ── 2. Hot-reload: next job's agents pick up a freshly installed skill ───


def test_new_agent_sees_freshly_installed_skill(tmp_path, monkeypatch):
    """Construction-time scan is the only reload mechanism.

    A registry built before install must not see the skill; a registry built
    after install must. Real agents are constructed per job, so this is the
    "no daemon restart" story — exercised through the real ``for_agent`` mount.
    """
    import agents.skills.loader as loader_mod

    installed_root = tmp_path / "installed"
    monkeypatch.setattr(loader_mod, "default_skills_root", lambda: installed_root)
    monkeypatch.setattr(loader_mod, "default_bundled_roots", lambda: [])

    before = _Agent("j1")
    assert before.skills.get("late_skill") is None

    _write_skill(installed_root, "late_skill", agents=("scout",), code=_ok_code("late_skill"))

    after = _Agent("j2")
    assert after.skills.get("late_skill") is not None
    # the pre-install registry stays stale — no live reload mid-job
    assert before.skills.get("late_skill") is None


# ── 3. Bundled (in-process) vs installed (subprocess) agree ──────────────


@pytest.mark.asyncio
async def test_agent_run_bundled_and_installed_agree(tmp_path):
    """One ``self.skills.run(name, ctx)`` contract for both execution modes."""
    _write_skill(tmp_path / "bundled", "echo", code=_ok_code("echo"))
    _write_skill(tmp_path / "installed", "echo", code=_ok_code("echo"))

    agent = _Agent("j1")
    agent.skills = _scoped_registry(tmp_path, "scout", "bundled")
    bundled = await agent.skills.run("echo", SkillContext(job_id="j1", agent="scout"))
    assert bundled.ok
    assert agent.skills.get("echo").root == "bundled"

    agent.skills = SkillRegistry(
        agent="scout",
        bundled_roots=[tmp_path / "empty"],
        skills_root=tmp_path / "installed",
    )
    installed = await agent.skills.run("echo", SkillContext(job_id="j1", agent="scout"))
    assert installed.ok
    assert agent.skills.get("echo").root == "installed"
    assert installed.detail == bundled.detail == {"agent": "scout", "job": "j1"}


# ── 4. Fallback contract: a missing/broken skill never raises to the agent ─


@pytest.mark.asyncio
async def test_agent_skill_missing_never_raises(tmp_path):
    agent = _Agent("j1")
    agent.skills = _scoped_registry(tmp_path, "scout", "empty")
    res = await agent.skills.run("missing", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "not found" in res.reason


# ── 5. Skill invocation surfaces on the subaction stream ─────────────────


@pytest.mark.asyncio
async def test_skill_run_emits_subaction_event(tmp_path):
    _write_skill(tmp_path / "bundled", "echo", code=_ok_code("echo"))
    agent = _Agent("j1")
    agent.skills = _scoped_registry(tmp_path, "scout", "bundled")
    redis = RecordingRedis()
    agent.skills.redis_client = redis
    agent.skills.job_id = "j1"

    res = await agent.skills.run("echo", SkillContext(job_id="j1", agent="scout"))
    assert res.ok

    from bus.events import STREAM_SUBACTION

    msgs = redis.streams.get(STREAM_SUBACTION, [])
    assert msgs, "expected a subaction event for the skill run"
    event = msgs[0]
    assert event["agent"] == "Scout"  # capitalised label for the stream renderer
    assert event["detail"] == "used skill echo"
    assert event["state"] == "done"


# ── 6. Dissect prompt: trusted instruction skills inject, untrusted don't ─


def test_dissect_prompt_injects_trusted_instruction_only(tmp_path):
    _write_skill(
        tmp_path / "bundled",
        "repair_guide",
        type_="instruction",
        agents=("dissect",),
        body="# ALWAYS check label encoding first",
        manifest={"trusted": True},
    )
    _write_skill(
        tmp_path / "bundled",
        "suspicious",
        type_="instruction",
        agents=("dissect",),
        body="# NEVER trust this body",
    )

    agent = DissectAgent("j1")
    agent.skills = _scoped_registry(tmp_path, "dissect", "bundled")

    script = tmp_path / "training_script.py"
    script.write_text("model.fit(x, y)", encoding="utf-8")
    crash = {
        "script_path": str(script),
        "exception_type": "ValueError",
        "exception_message": "shapes (32, 3) and (5,) not aligned",
    }
    prompt = agent._build_prompt(crash, "shape_mismatch", "reshape", None)

    assert "ALWAYS check label encoding first" in prompt
    assert "repair_guide" in prompt
    assert "NEVER trust this body" not in prompt
    # the crash context survives — injection is additive, never replacing
    assert "ValueError" in prompt and "model.fit(x, y)" in prompt


# ── 7. Forge system prompt: trusted instruction skills ride on it ────────


def test_forge_system_prompt_injects_trusted_instruction_only(tmp_path):
    _write_skill(
        tmp_path / "bundled",
        "forge_guide",
        type_="instruction",
        agents=("forge",),
        body="# Prefer LightGBM for tabular < 1M rows",
        manifest={"trusted": True},
    )
    _write_skill(
        tmp_path / "bundled",
        "untrusted_forge",
        type_="instruction",
        agents=("forge",),
        body="# NEVER inject this",
    )

    agent = ForgeAgent("j1")
    agent.skills = _scoped_registry(tmp_path, "forge", "bundled")

    prompt = agent.system_prompt
    assert FORGE_SYSTEM_PROMPT in prompt  # base prompt preserved
    assert "Prefer LightGBM for tabular < 1M rows" in prompt
    assert "NEVER inject this" not in prompt


# ── 8. instruction_text is bounded (a runaway doc can't blow up a prompt) ─


def test_instruction_text_bounded(tmp_path):
    long_body = "# pad\n" + ("x" * 20000)
    _write_skill(
        tmp_path / "bundled",
        "big",
        type_="instruction",
        agents=("scout",),
        body=long_body,
        manifest={"trusted": True},
    )
    reg = _scoped_registry(tmp_path, "scout", "bundled")
    text = reg.instruction_text(max_chars=1000)
    assert len(text) <= 1000
    # header survives the truncation — the bounded prefix stays usable
    assert text.startswith("## Skill: big")
    assert "x" in text

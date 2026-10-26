"""Phase 0 contract tests — the four cross-cutting contracts are the spec.

Built test-first (per the approved plan): JSON-safe round-trip, timeout +
memory kill, atomic install, and run-never-raises are pinned here before the
loader/installer logic that depends on them is trusted. Plus manifest
validation, two-tier discovery, agent routing, signing, and the install gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agents.skills import (
    SkillContext,
    SkillManifest,
    SkillRegistry,
    SkillResult,
    add_publisher,
    check_min_version,
    generate_keypair,
    install_source,
    load_manifest_from_dir,
    load_publishers,
    parse_frontmatter,
    sign_manifest,
    verify_manifest,
    verify_manifest_signature,
)


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


class FakeRedis:
    """Stub RedisClient recording hash writes — no live Redis in unit tests."""

    def __init__(self) -> None:
        self.h: dict[str, dict] = {}

    async def hincrby(self, key, field, amount=1):
        # Explicit two-statement form. The one-liner
        # `self.h.setdefault(key, {})[field] = self.h[key].get(field, 0) + amount`
        # raises KeyError: CPython evaluates the RHS (`self.h[key]`) before the
        # LHS container's `setdefault()` call, so the key is not yet inserted.
        self.h.setdefault(key, {})
        self.h[key][field] = self.h[key].get(field, 0) + amount
        return self.h[key][field]

    async def hset(self, key, field, value):
        self.h.setdefault(key, {})[field] = value
        return 1


# ── Contract 1: JSON-safe round-trip ──────────────────────────────────────


def test_context_result_json_roundtrip():
    ctx = SkillContext(
        job_id="j1",
        agent="scout",
        brief={"nested": {"a": 1, "b": [1, 2]}},
        paths={"data": "data/titanic.csv"},
    )
    assert SkillContext.model_validate_json(ctx.model_dump_json()) == ctx
    res = SkillResult(skill="x", ok=True, detail={"k": 1}, artifacts=["a.csv"], duration_ms=5)
    assert SkillResult.model_validate_json(res.model_dump_json()) == res


@pytest.mark.asyncio
async def test_worker_roundtrips_dataframe_artifact(tmp_path):
    """A heavy (DataFrame) output goes to work_dir, returned as a file path."""
    df_code = """
import os
import pandas as pd
from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

class EntrySkill(Skill):
    name = "dfwriter"
    async def run(self, ctx: SkillContext, **kwargs):
        out = os.path.join(ctx.work_dir, "table.csv")
        pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_csv(out, index=False)
        return SkillResult(skill=self.name, ok=True, detail={"rows": 2}, artifacts=[out])
"""
    _write_skill(tmp_path / "installed", "dfwriter", code=df_code)
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("dfwriter", SkillContext(job_id="j1", agent="scout"))
    assert res.ok, res.reason
    assert len(res.artifacts) == 1
    assert Path(res.artifacts[0]).is_file()
    back = SkillResult.model_validate_json(res.model_dump_json())
    assert back.artifacts == res.artifacts


@pytest.mark.asyncio
async def test_non_json_safe_output_degrades_to_ok_false(tmp_path):
    """A skill smuggling a non-JSON-serializable object into detail is rejected.

    Note: pydantic stringifies ``Path``, so a Path in ``detail`` is actually
    JSON-safe (it round-trips to its string form) — the contract is about
    objects pydantic *cannot* serialize, which must be written to ``work_dir``
    and returned as artifact paths instead.
    """
    leaky_code = """
from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

class EntrySkill(Skill):
    name = "leaky"
    async def run(self, ctx, **kwargs):
        return SkillResult(skill=self.name, ok=True, detail={"obj": object()})
"""
    _write_skill(tmp_path / "installed", "leaky", code=leaky_code)
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("leaky", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "serializ" in res.reason.lower()


# ── Contract 2: timeout + memory cap kill the subprocess ─────────────────

HANG_CODE = """
from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

class EntrySkill(Skill):
    name = "hang"
    async def run(self, ctx, **kwargs):
        while True:
            pass
"""

MEM_CODE = """
from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult

class EntrySkill(Skill):
    name = "eater"
    async def run(self, ctx, **kwargs):
        data = bytearray()
        while True:
            data += b"x" * (1024 * 1024)
"""


@pytest.mark.asyncio
async def test_timeout_kills_hung_skill(tmp_path):
    _write_skill(tmp_path / "installed", "hang", code=HANG_CODE, manifest={"max_runtime_s": 1})
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("hang", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "timed out" in res.reason
    assert res.duration_ms >= 900


@pytest.mark.asyncio
async def test_memory_cap_kills_runaway_skill(tmp_path):
    # Cap well above the worker's import baseline (~40-50MB) so startup is never
    # mistaken for a runaway allocation; the skill then grows past 200MB fast.
    _write_skill(tmp_path / "installed", "eater", code=MEM_CODE, manifest={"max_memory_mb": 200})
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("eater", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "memory" in res.reason


# ── Contract 3: atomic install leaves no partial dir ──────────────────────


@pytest.mark.asyncio
async def test_atomic_reinstall_with_force_leaves_no_partial(tmp_path):
    src_dir = tmp_path / "src"
    _write_skill(src_dir, "atomic", code=_ok_code("atomic"), manifest={"version": "1.0.0"})
    skills_root = tmp_path / "installed"

    r1 = await install_source(str(src_dir / "atomic"), skills_root=skills_root)
    assert r1.ok, r1.reason

    # same version, no --force → refused, old install intact
    r2 = await install_source(str(src_dir / "atomic"), skills_root=skills_root)
    assert not r2.ok and "already installed" in r2.reason
    assert (skills_root / "atomic" / "SKILL.md").is_file()

    # version bump with --force → new version live, no staging/old leftovers
    _write_skill(src_dir, "atomic", code=_ok_code("atomic"), manifest={"version": "2.0.0"})
    r3 = await install_source(str(src_dir / "atomic"), skills_root=skills_root, force=True)
    assert r3.ok, r3.reason
    m = load_manifest_from_dir(skills_root / "atomic", root="installed")
    assert m.version == "2.0.0"
    leftovers = [p.name for p in skills_root.iterdir() if p.name.startswith(".atomic.")]
    assert leftovers == []


@pytest.mark.asyncio
async def test_failed_gate_leaves_no_partial_install(tmp_path):
    skills_root = tmp_path / "installed"
    src = _write_skill(tmp_path / "src", "crashy", code=_ok_code("crashy") + "syntax error {{{")
    res = await install_source(str(src), skills_root=skills_root)
    assert not res.ok
    assert not skills_root.exists() or list(skills_root.iterdir()) == []  # nothing half-installed
    assert not list(tmp_path.glob("*.staging-*"))


# ── Contract 4: run() never raises ────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_missing_skill_returns_ok_false(tmp_path):
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "none")
    res = await reg.run("ghost", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "not found" in res.reason


@pytest.mark.asyncio
async def test_run_instruction_skill_returns_ok_false(tmp_path):
    _write_skill(tmp_path / "installed", "guide", type_="instruction", body="# do this")
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("guide", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "instruction" in res.reason


RAISE_CODE = """
from agents.skills.base import Skill
from agents.skills.context import SkillResult

class EntrySkill(Skill):
    name = "boom"
    async def run(self, ctx, **kwargs):
        raise RuntimeError("boom")
"""

BAD_RETURN_CODE = """
from agents.skills.base import Skill

class EntrySkill(Skill):
    name = "badret"
    async def run(self, ctx, **kwargs):
        return {"not": "a result"}
"""


@pytest.mark.asyncio
async def test_run_skill_that_raises_returns_ok_false(tmp_path):
    _write_skill(tmp_path / "installed", "boom", code=RAISE_CODE)
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("boom", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "raised" in res.reason


@pytest.mark.asyncio
async def test_run_skill_that_returns_non_result_returns_ok_false(tmp_path):
    _write_skill(tmp_path / "installed", "badret", code=BAD_RETURN_CODE)
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("badret", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert "non-SkillResult" in res.reason


@pytest.mark.asyncio
async def test_run_installed_broken_import_never_raises(tmp_path):
    _write_skill(tmp_path / "installed", "broken", code="this is not python {{{")
    reg = SkillRegistry(agent="scout", skills_root=tmp_path / "installed")
    res = await reg.run("broken", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False
    assert res.reason


@pytest.mark.asyncio
async def test_run_bundled_broken_import_never_raises(tmp_path):
    _write_skill(tmp_path / "bundled", "b2", code="import nonexistent_module_xyz")
    reg = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none"
    )
    res = await reg.run("b2", SkillContext(job_id="j1", agent="scout"))
    assert res.ok is False


# ── Manifest validation ───────────────────────────────────────────────────


def test_manifest_validators():
    m = SkillManifest(name="ok_skill", agents=["SCOUT", "all"])
    assert m.agents == ["scout", "all"]
    with pytest.raises(ValidationError):
        SkillManifest(name="Bad Name")
    with pytest.raises(ValidationError):
        SkillManifest(name="x", agents=["chef"])
    with pytest.raises(ValidationError):
        SkillManifest(name="x", type="binary")
    with pytest.raises(ValidationError):
        SkillManifest(name="x", max_memory_mb=0)


def test_parse_frontmatter_splits():
    data, body = parse_frontmatter("---\nname: a\nagents: [scout]\n---\n\nBody here")
    assert data["name"] == "a" and body == "Body here"
    data2, body2 = parse_frontmatter("no frontmatter")
    assert data2 == {} and body2 == "no frontmatter"


def test_min_version_check():
    assert check_min_version(None) is True
    assert check_min_version("0.0.1") is True  # current VERSION is 0.1.0
    assert check_min_version("99.0.0") is False


# ── Two-tier discovery + routing ──────────────────────────────────────────


def test_agent_routing(tmp_path):
    _write_skill(tmp_path / "bundled", "for_scout", agents=("scout",), code=_ok_code("for_scout"))
    _write_skill(tmp_path / "bundled", "for_all", agents=("all",), code=_ok_code("for_all"))
    s = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none"
    )
    assert {m.name for m in s.list()} == {"for_scout", "for_all"}
    h = SkillRegistry(
        agent="harbor", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none"
    )
    assert {m.name for m in h.list()} == {"for_all"}
    assert s.get("for_scout") is not None
    assert h.get("for_scout") is None


def test_installed_shadows_bundled(tmp_path):
    _write_skill(tmp_path / "bundled", "dup", code=_ok_code("dup"), manifest={"version": "1.0.0"})
    _write_skill(tmp_path / "installed", "dup", code=_ok_code("dup"), manifest={"version": "2.0.0"})
    reg = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "installed"
    )
    m = reg.get("dup")
    assert m is not None and m.version == "2.0.0" and m.root == "installed"


def test_instruction_skills_trusted_only(tmp_path):
    _write_skill(
        tmp_path / "bundled",
        "trusted_guide",
        type_="instruction",
        agents=("dissect",),
        body="# a",
        manifest={"trusted": True},
    )
    _write_skill(
        tmp_path / "bundled",
        "untrusted_guide",
        type_="instruction",
        agents=("dissect",),
        body="# b",
    )
    _write_skill(tmp_path / "bundled", "codey", agents=("dissect",), code=_ok_code("codey"))
    reg = SkillRegistry(
        agent="dissect", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none"
    )
    assert {m.name for m in reg.instruction_skills()} == {"trusted_guide"}


def test_scan_tolerates_broken_and_missing_manifests(tmp_path):
    skills_root = tmp_path / "installed"
    _write_skill(skills_root, "ok", code=_ok_code("ok"))
    _write_skill(skills_root, "broken", code="syntax error {{")
    (skills_root / "no_manifest").mkdir()
    (skills_root / "junk").mkdir()
    (skills_root / "junk" / "SKILL.md").write_text("not frontmatter")
    reg = SkillRegistry(agent="scout", skills_root=skills_root)  # must not raise / import
    names = {m.name for m in reg.list()}
    assert "ok" in names and "broken" in names
    assert "no_manifest" not in names and "junk" not in names


@pytest.mark.asyncio
async def test_bundled_and_installed_modes_agree(tmp_path):
    _write_skill(tmp_path / "bundled", "echo", code=_ok_code("echo"))
    _write_skill(tmp_path / "installed", "echo", code=_ok_code("echo"))
    b_reg = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none2"
    )
    i_reg = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "empty"], skills_root=tmp_path / "installed"
    )
    ctx = SkillContext(job_id="j1", agent="scout")
    rb = await b_reg.run("echo", ctx)
    ri = await i_reg.run("echo", ctx)
    assert rb.ok and ri.ok
    assert rb.detail == ri.detail == {"agent": "scout", "job": "j1"}


# ── Evidence-gate stats (promotion mechanism) ────────────────────────────


@pytest.mark.asyncio
async def test_evidence_gate_stats_recorded(tmp_path):
    _write_skill(tmp_path / "bundled", "st", code=_ok_code("st"))
    reg = SkillRegistry(
        agent="scout", bundled_roots=[tmp_path / "bundled"], skills_root=tmp_path / "none"
    )
    fake = FakeRedis()
    reg.redis_client = fake

    res = await reg.run("st", SkillContext(job_id="j1", agent="scout"))
    assert res.ok
    stats = fake.h["skill:st:scout:stats"]
    assert stats["total_runs"] == 1 and stats["ok_runs"] == 1 and stats["consecutive_ok"] == 1

    await reg.run(
        "boom_does_not_exist", SkillContext(job_id="j1", agent="scout")
    )  # missing → no stats
    assert "skill:boom_does_not_exist:scout:stats" not in fake.h

    await reg.record_fallback("st")
    stats2 = fake.h["skill:st:scout:stats"]
    assert stats2["fallback_fired"] == 1 and stats2["consecutive_ok"] == 0


# ── Signing (authenticity layer) ──────────────────────────────────────────


def test_signature_verifies_and_rejects_tampering(tmp_path):
    priv, pub = generate_keypair()
    skill_dir = _write_skill(tmp_path / "s", "signed_skill")
    m = load_manifest_from_dir(skill_dir, root="installed")
    m.publisher = "acme"
    m.signature = sign_manifest(m, priv)
    assert verify_manifest(m, pub)
    m.description = "tampered"
    assert not verify_manifest(m, pub)


def test_publisher_store_and_gate(tmp_path):
    priv, pub = generate_keypair()
    pub_file = tmp_path / "publishers.json"
    add_publisher("acme", pub, path=pub_file)
    assert "acme" in load_publishers(pub_file)

    skill_dir = _write_skill(tmp_path / "s", "signed2")
    m = load_manifest_from_dir(skill_dir, root="installed")
    m.publisher = "acme"
    m.signature = sign_manifest(m, priv)
    ok, reason = verify_manifest_signature(m, path=pub_file)
    assert ok, reason

    m2 = load_manifest_from_dir(skill_dir, root="installed")
    m2.publisher = "evil"
    m2.signature = m.signature
    ok2, reason2 = verify_manifest_signature(m2, path=pub_file)
    assert not ok2 and "not trusted" in reason2

    m3 = load_manifest_from_dir(skill_dir, root="installed")
    m3.publisher = "acme"
    ok3, reason3 = verify_manifest_signature(m3, path=pub_file)
    assert not ok3 and "no signature" in reason3


# ── Install gate (4 steps) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_install_local_success(tmp_path):
    src = _write_skill(tmp_path / "src", "happy", code=_ok_code("happy"))
    skills_root = tmp_path / "installed"
    res = await install_source(str(src), skills_root=skills_root)
    assert res.ok, res.reason
    assert (skills_root / "happy" / "SKILL.md").is_file()
    assert all(c["ok"] for c in res.checks)
    assert SkillRegistry(agent="scout", skills_root=skills_root).get("happy") is not None


@pytest.mark.asyncio
async def test_install_agent_override_revalidates(tmp_path):
    src = _write_skill(tmp_path / "src", "multi", agents=("scout",), code=_ok_code("multi"))
    res = await install_source(str(src), agents="scout,forge", skills_root=tmp_path / "installed")
    assert res.ok, res.reason
    m = load_manifest_from_dir(tmp_path / "installed" / "multi", root="installed")
    assert m.agents == ["scout", "forge"]


@pytest.mark.asyncio
async def test_install_rejects_bad_manifest_name(tmp_path):
    src = _write_skill(tmp_path / "src", "Bad Name", code=_ok_code("x"))
    res = await install_source(str(src), skills_root=tmp_path / "installed")
    assert not res.ok
    assert any(c["step"] == "manifest" for c in res.checks)


@pytest.mark.asyncio
async def test_install_rejects_unknown_agent(tmp_path):
    src = _write_skill(tmp_path / "src", "weird", agents=("chef",), code=_ok_code("weird"))
    res = await install_source(str(src), skills_root=tmp_path / "installed")
    assert not res.ok and "manifest" in res.reason


@pytest.mark.asyncio
async def test_install_gate_reports_smoke_failure(tmp_path):
    src = _write_skill(tmp_path / "src", "crashy", code=RAISE_CODE)
    res = await install_source(str(src), skills_root=tmp_path / "installed")
    assert not res.ok
    assert any(c["step"] == "smoke:scout" and not c["ok"] for c in res.checks)


@pytest.mark.asyncio
async def test_install_rejects_non_skill_class(tmp_path):
    src = _write_skill(
        tmp_path / "src",
        "notaskill",
        code="""
class EntrySkill:
    def run(self, ctx):
        return None
""",
    )
    res = await install_source(str(src), skills_root=tmp_path / "installed")
    assert not res.ok
    assert any(c["step"] == "structural" and not c["ok"] for c in res.checks)


@pytest.mark.asyncio
async def test_install_md_requires_trust_and_sets_trusted(tmp_path):
    md = tmp_path / "hints.md"
    md.write_text("# Use class weights\nAlways add class_weight for imbalance.\n", encoding="utf-8")
    skills_root = tmp_path / "installed"

    res = await install_source(
        str(md), source_type="md", name="imbalance_hint", skills_root=skills_root
    )
    assert not res.ok and "trust" in res.reason

    res2 = await install_source(
        str(md), source_type="md", name="imbalance_hint", trust=True, skills_root=skills_root
    )
    assert res2.ok, res2.reason
    m = load_manifest_from_dir(skills_root / "imbalance_hint", root="installed")
    assert m.is_instruction() and m.trusted is True


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
@pytest.mark.asyncio
async def test_install_git_verifies_signature(tmp_path):
    priv, pub = generate_keypair()
    repo = tmp_path / "repo"
    # _write_skill(root, name) creates root/name/ — pass the repo as root so
    # the skill sits at repo/hello_skill (one nesting level, matching the
    # installer's single-skill-subdir discovery).
    skill_dir = _write_skill(repo, "hello_skill", code=_ok_code("hello_skill"))
    # parse_frontmatter, not yaml.safe_load: the file also carries the closing
    # `---`, which safe_load would read as a second document.
    data, _ = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    m = load_manifest_from_dir(skill_dir, root="installed")
    m.publisher = "acme"
    data["publisher"] = "acme"
    data["signature"] = sign_manifest(m, priv)
    (skill_dir / "SKILL.md").write_text(
        "---\n" + yaml.safe_dump(data, sort_keys=False).rstrip() + "\n---\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    pub_file = tmp_path / "publishers.json"
    add_publisher("acme", pub, path=pub_file)
    res = await install_source(
        repo.as_uri(), source_type="git", skills_root=tmp_path / "installed", publishers=pub_file
    )
    assert res.ok, res.reason
    assert (tmp_path / "installed" / "hello_skill").is_dir()

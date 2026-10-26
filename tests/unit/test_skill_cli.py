"""Phase 2 CLI tests — ``prometheus skill`` driven through CliRunner.

The whole command surface runs against a temp-configured ``SkillService``
(monkeypatched onto ``AppContext.skills``), so no real ``~/.prometheus`` state
is touched: install (local / git / trusted-md, each with its gate), list /
info / verify / test / remove / update / create, trust / untrust, promote
(evidence-gated) with the promotion store, and check-orphans.

Note on output capture: the renderers write through the rich console singleton
bound to the *real* stdout at import, so CliRunner's ``result.output`` only
carries ``click.echo`` text (help). The ``console_buf`` fixture swaps that
singleton for a StringIO-backed console so renderer messages are assertable
too; the primary assertions are exit codes and filesystem/promotion side
effects, which are the real behavior contract.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from rich.console import Console

import agents.skills.loader as loader_mod
from agents.skills import (
    generate_keypair,
    load_manifest_from_dir,
    load_publishers,
    parse_frontmatter,
    sign_manifest,
)
from prometheus.main import cli
from prometheus.services.skill_service import SkillService, load_promotions


# ── Helpers (mirror the Phase 0 platform tests) ───────────────────────────


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


def _sign_skill_dir(skill_dir: Path, priv: bytes) -> None:
    """Write publisher + detached signature into an already-written SKILL.md."""
    data, _ = parse_frontmatter((skill_dir / "SKILL.md").read_text(encoding="utf-8"))
    m = load_manifest_from_dir(skill_dir, root="installed")
    m.publisher = "acme"
    data["publisher"] = "acme"
    data["signature"] = sign_manifest(m, priv)
    (skill_dir / "SKILL.md").write_text(
        "---\n" + yaml.safe_dump(data, sort_keys=False).rstrip() + "\n---\n", encoding="utf-8"
    )


def _signed_git_repo(tmp_path: Path, name: str = "hello_skill") -> tuple[Path, bytes]:
    """A local git repo containing one signed skill. Returns (repo, pub_key)."""
    priv, pub = generate_keypair()
    repo = tmp_path / "repo"
    skill_dir = _write_skill(repo, name, code=_ok_code(name))
    _sign_skill_dir(skill_dir, priv)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=repo,
        check=True,
    )
    return repo, pub


class FakeRedis:
    """In-memory Redis stand-in answering evidence-gate ``hgetall`` reads."""

    def __init__(self, stats: dict[str, dict] | None = None) -> None:
        self.stats = stats or {}

    async def hgetall(self, key: str) -> dict:
        return dict(self.stats.get(key, {}))


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def console_buf(monkeypatch):
    """Redirect renderer output (rich singleton) into a StringIO."""
    import prometheus.ui.renderers.output as out_mod

    buf = io.StringIO()
    monkeypatch.setattr(
        out_mod, "rich_console", Console(file=buf, no_color=True, force_terminal=False)
    )
    return buf


def _make_service(
    tmp_path: Path, *, redis=None, agents_root: Path | None = None, promote_n: int = 10
) -> SkillService:
    return SkillService(
        skills_root=tmp_path / "skills",
        publishers=tmp_path / "publishers.json",
        promotions=tmp_path / "promotions.json",
        agents_root=agents_root or tmp_path / "agents",
        redis_client=redis,
        promote_consecutive_ok=promote_n,
    )


def _use_service(monkeypatch, svc: SkillService) -> None:
    import prometheus.services.app_context as ac_mod

    monkeypatch.setattr(ac_mod.AppContext, "skills", property(lambda self: svc))


def _promote_env(
    tmp_path, monkeypatch, *, stats: dict, agents_root: Path | None = None, promote_n: int = 10
) -> SkillService:
    _write_skill(tmp_path / "skills", "proven", code=_ok_code("proven"))
    redis = FakeRedis({"skill:proven:scout:stats": stats})
    svc = _make_service(tmp_path, redis=redis, agents_root=agents_root, promote_n=promote_n)
    _use_service(monkeypatch, svc)
    return svc


def _agents_with_call(tmp_path: Path, name: str, *, guarded: bool = True) -> Path:
    agents_root = tmp_path / "agents"
    (agents_root / "scout").mkdir(parents=True, exist_ok=True)
    line = f'result = await self.skills.run("{name}", ctx)'
    if guarded:
        line += "\nif not result.ok:\n    _fallback()"
    (agents_root / "scout" / "agent.py").write_text(line + "\n", encoding="utf-8")
    return agents_root


# ── Group registration + alias ────────────────────────────────────────────


def test_skill_group_and_alias_registered(runner):
    r = runner.invoke(cli, ["skill", "--help"])
    assert r.exit_code == 0
    for cmd in (
        "install",
        "list",
        "info",
        "verify",
        "test",
        "remove",
        "update",
        "create",
        "trust",
        "untrust",
        "promote",
        "check-orphans",
    ):
        assert cmd in r.output
    # the "skills" alias resolves to the same group
    r2 = runner.invoke(cli, ["skills", "list"])
    assert r2.exit_code == 0


# ── Install (local / md trust-gated / git signature-gated) ────────────────


def test_install_local_success(runner, tmp_path, monkeypatch):
    src = _write_skill(tmp_path / "src", "hello", code=_ok_code("hello"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "install", str(src)])
    assert r.exit_code == 0, r.output
    assert (tmp_path / "skills" / "hello" / "SKILL.md").is_file()
    assert (tmp_path / "skills" / "hello" / "skill.py").is_file()


def test_install_md_requires_trust(runner, tmp_path, monkeypatch, console_buf):
    md = tmp_path / "hints.md"
    md.write_text("# Use class weights\nAlways add class_weight for imbalance.\n", encoding="utf-8")
    _use_service(monkeypatch, _make_service(tmp_path))

    r = runner.invoke(
        cli, ["skill", "install", str(md), "--type", "md", "--name", "imbalance_hint"]
    )
    assert r.exit_code == 1
    assert "trust" in console_buf.getvalue()
    assert not (tmp_path / "skills" / "imbalance_hint").exists()

    r2 = runner.invoke(
        cli, ["skill", "install", str(md), "--type", "md", "--name", "imbalance_hint", "--trust"]
    )
    assert r2.exit_code == 0, console_buf.getvalue()
    m = load_manifest_from_dir(tmp_path / "skills" / "imbalance_hint", root="installed")
    assert m.is_instruction() and m.trusted is True


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_install_git_signature_gate(runner, tmp_path, monkeypatch):
    repo, pub = _signed_git_repo(tmp_path)
    _use_service(monkeypatch, _make_service(tmp_path))

    # untrusted publisher → gate fails before anything is installed
    r = runner.invoke(cli, ["skill", "install", repo.as_uri(), "--type", "git"])
    assert r.exit_code == 1
    assert not (tmp_path / "skills" / "hello_skill").exists()

    # trust the publisher → signed install succeeds end-to-end
    pub_file = tmp_path / "acme.pem"
    pub_file.write_bytes(pub)
    assert runner.invoke(cli, ["skill", "trust", "acme", "--key", str(pub_file)]).exit_code == 0
    r2 = runner.invoke(cli, ["skill", "install", repo.as_uri(), "--type", "git"])
    assert r2.exit_code == 0, r2.output
    assert (tmp_path / "skills" / "hello_skill").is_dir()


# ── Inspect: list / info / verify / test ──────────────────────────────────


def test_list_shows_skills(runner, tmp_path, monkeypatch):
    _write_skill(tmp_path / "skills", "alpha", code=_ok_code("alpha"))
    _write_skill(
        tmp_path / "skills",
        "beta_guide",
        type_="instruction",
        body="# beta",
        manifest={"trusted": True},
    )
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "list"])
    assert r.exit_code == 0
    assert "alpha" in r.output and "beta_guide" in r.output
    assert "instruction" in r.output and "code" in r.output
    r2 = runner.invoke(cli, ["skill", "list", "--agent", "scout"])
    assert r2.exit_code == 0 and "alpha" in r2.output


def test_info_shows_manifest_and_status(runner, tmp_path, monkeypatch):
    _write_skill(tmp_path / "skills", "hello", code=_ok_code("hello"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "info", "hello"])
    assert r.exit_code == 0
    assert "hello" in r.output and "structural" in r.output and "code" in r.output
    r2 = runner.invoke(cli, ["skill", "info", "ghost"])
    assert r2.exit_code == 3  # ERROR_NOT_FOUND


def test_verify_unsigned_fails(runner, tmp_path, monkeypatch, console_buf):
    _write_skill(tmp_path / "skills", "unsigned_skill", code=_ok_code("unsigned_skill"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "verify", "unsigned_skill"])
    assert r.exit_code == 1
    assert "publisher" in console_buf.getvalue()


def test_verify_signed_passes(runner, tmp_path, monkeypatch):
    priv, pub = generate_keypair()
    _sign_skill_dir(
        _write_skill(tmp_path / "skills", "signed_skill", code=_ok_code("signed_skill")), priv
    )
    _use_service(monkeypatch, _make_service(tmp_path))
    pub_file = tmp_path / "acme.pem"
    pub_file.write_bytes(pub)
    assert runner.invoke(cli, ["skill", "trust", "acme", "--key", str(pub_file)]).exit_code == 0
    r = runner.invoke(cli, ["skill", "verify", "signed_skill"])
    assert r.exit_code == 0


def test_test_runs_smoke_and_not_found(runner, tmp_path, monkeypatch):
    _write_skill(tmp_path / "skills", "hello", code=_ok_code("hello"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "test", "hello"])
    assert r.exit_code == 0, r.output
    r2 = runner.invoke(cli, ["skill", "test", "ghost"])
    assert r2.exit_code == 3


# ── Mutate: remove / update / create ──────────────────────────────────────


def test_remove_installed(runner, tmp_path, monkeypatch):
    _write_skill(tmp_path / "skills", "hello", code=_ok_code("hello"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "remove", "hello"])
    assert r.exit_code == 0
    assert not (tmp_path / "skills" / "hello").exists()
    assert runner.invoke(cli, ["skill", "info", "hello"]).exit_code == 3


def test_remove_refuses_bundled(runner, tmp_path, monkeypatch, console_buf):
    monkeypatch.setattr(loader_mod, "default_bundled_roots", lambda: [tmp_path / "bundled"])
    _write_skill(tmp_path / "bundled", "core", code=_ok_code("core"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "remove", "core"])
    assert r.exit_code == 1
    assert "bundled" in console_buf.getvalue()
    assert (tmp_path / "bundled" / "core").exists()


def test_update_refuses_non_git(runner, tmp_path, monkeypatch, console_buf):
    _write_skill(tmp_path / "skills", "hello", code=_ok_code("hello"))
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "update", "hello"])
    assert r.exit_code == 1
    assert "git" in console_buf.getvalue()


def test_create_scaffolds_and_tests(runner, tmp_path, monkeypatch):
    _use_service(monkeypatch, _make_service(tmp_path))
    r = runner.invoke(cli, ["skill", "create", "my_skill", "--agent", "scout"])
    assert r.exit_code == 0, r.output
    skill_dir = tmp_path / "skills" / "my_skill"
    assert (skill_dir / "SKILL.md").is_file() and (skill_dir / "skill.py").is_file()
    r2 = runner.invoke(cli, ["skill", "test", "my_skill"])
    assert r2.exit_code == 0, r2.output


# ── Trust management ──────────────────────────────────────────────────────


def test_trust_untrust_publisher(runner, tmp_path, monkeypatch):
    _, pub = generate_keypair()
    pub_file = tmp_path / "acme.pem"
    pub_file.write_bytes(pub)
    _use_service(monkeypatch, _make_service(tmp_path))

    assert runner.invoke(cli, ["skill", "trust", "acme", "--key", str(pub_file)]).exit_code == 0
    assert "acme" in load_publishers(tmp_path / "publishers.json")

    assert runner.invoke(cli, ["skill", "untrust", "acme"]).exit_code == 0
    assert "acme" not in load_publishers(tmp_path / "publishers.json")

    assert runner.invoke(cli, ["skill", "untrust", "acme"]).exit_code == 3


# ── Promotion (evidence-gated) + check-orphans ────────────────────────────


def test_promote_refuses_below_gate(runner, tmp_path, monkeypatch, console_buf):
    _promote_env(
        tmp_path,
        monkeypatch,
        stats={
            "total_runs": 3,
            "ok_runs": 3,
            "consecutive_ok": 3,
            "fallback_fired": 0,
        },
    )
    r = runner.invoke(cli, ["skill", "promote", "proven", "--agent", "scout"])
    assert r.exit_code == 1
    assert "evidence gate" in console_buf.getvalue()
    assert not (tmp_path / "promotions.json").exists()


def test_promote_succeeds_at_gate(runner, tmp_path, monkeypatch):
    _promote_env(
        tmp_path,
        monkeypatch,
        stats={
            "total_runs": 12,
            "ok_runs": 12,
            "consecutive_ok": 12,
            "fallback_fired": 0,
        },
    )
    r = runner.invoke(cli, ["skill", "promote", "proven", "--agent", "scout"])
    assert r.exit_code == 0, r.output
    store = load_promotions(tmp_path / "promotions.json")
    assert store["proven:scout"]["stable"] is True
    assert store["proven:scout"]["evidence"]["consecutive_ok"] == 12
    # promotion state never leaks into the signed manifest
    m = load_manifest_from_dir(tmp_path / "skills" / "proven", root="installed")
    assert not hasattr(m, "stable") or not getattr(m, "stable", False)


def test_promote_refuses_when_fallback_fired(runner, tmp_path, monkeypatch, console_buf):
    _promote_env(
        tmp_path,
        monkeypatch,
        stats={
            "total_runs": 12,
            "ok_runs": 12,
            "consecutive_ok": 12,
            "fallback_fired": 1,
        },
    )
    r = runner.invoke(cli, ["skill", "promote", "proven", "--agent", "scout"])
    assert r.exit_code == 1
    assert "fallback" in console_buf.getvalue()
    assert not (tmp_path / "promotions.json").exists()


def test_check_orphans_flags_stable_skill_with_fallback(runner, tmp_path, monkeypatch):
    agents_root = _agents_with_call(tmp_path, "proven", guarded=True)
    _promote_env(
        tmp_path,
        monkeypatch,
        agents_root=agents_root,
        stats={
            "total_runs": 12,
            "ok_runs": 12,
            "consecutive_ok": 12,
            "fallback_fired": 0,
        },
    )
    assert runner.invoke(cli, ["skill", "promote", "proven", "--agent", "scout"]).exit_code == 0
    r = runner.invoke(cli, ["skill", "check-orphans"])
    assert r.exit_code == 1
    assert "proven:scout" in r.output


def test_check_orphans_clean_when_fallback_removed(runner, tmp_path, monkeypatch):
    agents_root = _agents_with_call(tmp_path, "proven", guarded=False)
    _promote_env(
        tmp_path,
        monkeypatch,
        agents_root=agents_root,
        stats={
            "total_runs": 12,
            "ok_runs": 12,
            "consecutive_ok": 12,
            "fallback_fired": 0,
        },
    )
    assert runner.invoke(cli, ["skill", "promote", "proven", "--agent", "scout"]).exit_code == 0
    r = runner.invoke(cli, ["skill", "check-orphans"])
    assert r.exit_code == 0

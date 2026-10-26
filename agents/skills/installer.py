"""Installer — the 4-step validation gate + atomic install for user skills.

Every source (local dir, git URL, trusted .md, registry archive) is staged into
a temp dir, run through the gate, then atomically placed into
``~/.prometheus/skills/<name>/``. Atomic install (Cross-cutting contract #3):
the staged skill is moved onto the same filesystem as the target, then a single
``os.replace`` publishes it — a concurrently-scanned loader sees the old or the
new skill, never a torn one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from agents.skills.context import SkillContext
from agents.skills.loader import default_skills_root, repo_root, validate_structural
from agents.skills.manifest import (
    VALID_AGENTS,
    SkillManifest,
    check_min_version,
    load_manifest_from_dir,
    parse_frontmatter,
)
from agents.skills.signing import verify_manifest_signature
from agents.skills.subprocess_runner import run_skill_subprocess

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


@dataclass
class InstallResult:
    ok: bool
    reason: str = ""
    checks: list[dict] = field(default_factory=list)
    name: str = ""
    path: str = ""


def _detect_source_type(source: str, source_type: str | None) -> str:
    if source_type:
        return source_type
    if Path(source).is_dir():
        return "local"
    low = source.lower()
    if low.endswith(".md"):
        return "md"
    if low.startswith(("http://", "https://", "git@", "ssh://")):
        return "registry" if low.endswith((".zip", ".tar.gz", ".tgz")) else "git"
    return "local"


def _pick_skill_subdir(staging: Path) -> Path:
    """Locate the directory that holds a SKILL.md (root, else a unique subdir)."""
    if (staging / "SKILL.md").is_file():
        return staging
    candidates = [p for p in staging.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
    if len(candidates) == 1:
        return candidates[0]
    return staging


def _stage_md(source: str, staging: Path, name: str | None) -> Path:
    """A trusted .md skill becomes a single-file skill dir with a real manifest."""
    text = Path(source).read_text(encoding="utf-8")
    data, body = parse_frontmatter(text)
    if "type" not in data:
        data["type"] = "instruction"
    if "name" not in data:
        stem = _SLUG_RE.sub("_", Path(source).stem.lower()).strip("_") or "unnamed"
        data["name"] = name or stem
    if data["name"] not in ("", None):
        try:
            SkillManifest.model_validate(data)
        except ValidationError:
            pass  # the gate will report the precise invalid field
    header = "---\n" + yaml.safe_dump(data, sort_keys=False).rstrip() + "\n---\n\n"
    (staging / "SKILL.md").write_text(header + body, encoding="utf-8")
    return staging


def _stage_archive(source: str, staging: Path) -> Path:
    extract = staging / "extract"
    extract.mkdir(parents=True, exist_ok=True)
    archive_path = staging / "download"
    # Explicit user-supplied archive URL on a CLI command the operator runs
    # deliberately; not a server-side fetch of attacker input.
    urllib.request.urlretrieve(source, archive_path)  # nosec B310
    low = source.lower()
    if low.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as zf:
            _extract_zip_safe(zf, extract)
    else:
        with tarfile.open(archive_path, "r:*") as tf:
            tf.extractall(extract, filter="data")
    return _pick_skill_subdir(extract)


def _extract_zip_safe(zf: zipfile.ZipFile, extract: Path) -> None:
    """Extract a zip with zip-slip protection (bandit B202 / CWE-22).

    Mirrors tarfile's ``filter="data"`` contract: reject any member whose
    resolved path escapes the extraction root, so a malicious archive from a
    registry URL cannot write outside the staging dir.
    """
    root = extract.resolve()
    for member in zf.infolist():
        target = (extract / member.filename).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"unsafe archive member: {member.filename!r}")
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


def _stage(source: str, source_type: str, staging: Path, name: str | None) -> Path:
    if source_type == "local":
        src = Path(source)
        if not src.is_dir():
            raise ValueError(f"not a directory: {source}")
        target = staging / src.name
        shutil.copytree(src, target)
        return _pick_skill_subdir(target)
    if source_type == "git":
        repo = staging / "repo"
        subprocess.run(
            ["git", "clone", "--depth", "1", source, str(repo)],
            check=True,
            capture_output=True,
            timeout=120,
        )
        return _pick_skill_subdir(repo)
    if source_type == "md":
        return _stage_md(source, staging, name)
    if source_type == "registry":
        return _stage_archive(source, staging)
    raise ValueError(f"unknown source type: {source_type}")


def _persist_manifest(skill_root: Path, manifest: SkillManifest) -> None:
    """Rewrite SKILL.md with the final manifest, preserving the instruction body.

    The staged SKILL.md was authored before any ``--name`` / ``--agent`` /
    ``--trust`` overrides. Without this, those mutations live only on the
    in-memory manifest and the *installed* file still declares the original
    name/agents/trusted — so overrides silently fail and instruction skills
    install as ``trusted: false``. The scan-time fields (``path`` / ``root`` /
    ``instruction_body``) are excluded; the body is re-appended verbatim.
    """
    body = manifest.instruction_body or ""
    data = manifest.model_dump(exclude={"path", "root", "instruction_body"})
    text = "---\n" + yaml.safe_dump(data, sort_keys=False).rstrip() + "\n---\n\n" + body
    (skill_root / "SKILL.md").write_text(text, encoding="utf-8")


def build_dry_run_context(agent: str, manifest: SkillManifest | None = None) -> SkillContext:
    """Per-agent compat fixture, falling back to a minimal default context.

    Phase 1 ships real captured ``mission_brief``/``mission_spec`` snapshots in
    ``tests/fixtures/skill_contexts/<agent>.json``; until then the smoke uses a
    minimal context, which is conservative (skills needing real data fail the
    gate — better a safe false-reject than shipping a broken skill).
    """
    fixture = repo_root() / "tests" / "fixtures" / "skill_contexts" / f"{agent}.json"
    data: dict = {}
    if fixture.is_file():
        try:
            data = json.loads(fixture.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    return SkillContext(
        job_id="skill-install-smoke",
        agent=agent,
        brief=data.get("brief", {}),
        spec=data.get("spec", {}),
        paths=data.get("paths", {}),
    )


async def install_source(
    source: str,
    *,
    source_type: str | None = None,
    agents: str | None = None,
    trust: bool = False,
    force: bool = False,
    no_verify: bool = False,
    name: str | None = None,
    skills_root: Path | None = None,
    publishers: Path | None = None,
) -> InstallResult:
    """Stage → validate → atomically install a skill.

    Returns an ``InstallResult``; every gate failure reports exactly which
    check failed in ``result.checks``.
    """
    checks: list[dict] = []
    staging_root = Path(tempfile.mkdtemp(prefix="prometheus-skill-install-"))

    def _fail(reason: str, check: str) -> InstallResult:
        shutil.rmtree(staging_root, ignore_errors=True)
        return InstallResult(ok=False, reason=reason, checks=checks, name="")

    s_type = _detect_source_type(source, source_type)
    try:
        skill_root = _stage(source, s_type, staging_root, name)
    except Exception as e:
        return _fail(f"could not stage source: {e}", "source")

    manifest = load_manifest_from_dir(skill_root, root="installed")
    if manifest is None:
        checks.append({"step": "manifest", "ok": False, "detail": "no valid SKILL.md / manifest"})
        return _fail("no valid SKILL.md / manifest found in source", "manifest")

    # --name / --agent overrides re-validate through the full schema.
    if name:
        try:
            manifest = SkillManifest.model_validate({**manifest.model_dump(), "name": name})
        except ValidationError as e:
            return _fail(f"invalid --name: {e.errors()[0]['msg']}", "manifest")
    if agents:
        agent_list = [a.strip().lower() for a in agents.split(",")]
        try:
            manifest = SkillManifest.model_validate({**manifest.model_dump(), "agents": agent_list})
        except ValidationError as e:
            return _fail(f"invalid --agent: {e.errors()[0]['msg']}", "manifest")

    # ── Step 1: signature (required for remote sources unless --no-verify) ──
    if s_type in ("git", "registry") and not no_verify:
        sig_ok, sig_reason = verify_manifest_signature(manifest, path=publishers)
        checks.append({"step": "signature", "ok": sig_ok, "detail": sig_reason})
        if not sig_ok:
            return _fail(sig_reason, "signature")
    else:
        checks.append(
            {"step": "signature", "ok": True, "detail": "not required for this source type"}
        )

    # ── Step 2: manifest schema (already validated on load) + trust for md ─
    if manifest.is_instruction() and not (trust or manifest.trusted):
        return _fail(
            "instruction skills require --trust (their body is injected into an LLM agent's prompt)",
            "trust",
        )
    if trust:
        # --trust records trust on the installed manifest; only trusted
        # instruction skills are injected into an agent's LLM prompt.
        manifest.trusted = True
    if not check_min_version(manifest.min_prometheus_version):
        return _fail(f"requires prometheus >= {manifest.min_prometheus_version}", "manifest")
    # Persist overrides + trust into the staged SKILL.md now, so structural /
    # smoke validate the exact manifest that will be installed.
    _persist_manifest(skill_root, manifest)
    checks.append({"step": "manifest", "ok": True, "detail": "schema valid"})

    # ── Step 3: structural (Skill subclass + async run; imports = warning) ─
    struct_ok, struct_reason, warnings = validate_structural(manifest)
    checks.append(
        {
            "step": "structural",
            "ok": struct_ok,
            "detail": struct_reason or "ok",
            "warnings": warnings,
        }
    )
    if not struct_ok:
        return _fail(struct_reason, "structural")

    # ── Step 4: dry-run smoke + agent-compat ───────────────────────────────
    if manifest.type == "code":
        test_agents = sorted(VALID_AGENTS) if "all" in manifest.agents else manifest.agents
        for agent in test_agents:
            res = await run_skill_subprocess(manifest, build_dry_run_context(agent, manifest))
            checks.append({"step": f"smoke:{agent}", "ok": res.ok, "detail": res.reason or "ok"})
            if not res.ok:
                return _fail(
                    f"agent-compat smoke failed for {agent}: {res.reason}", f"smoke:{agent}"
                )
    else:
        checks.append(
            {"step": "smoke", "ok": True, "detail": "instruction skill — no code to smoke-test"}
        )

    # ── Atomic install ────────────────────────────────────────────────────
    target_root = Path(skills_root) if skills_root else default_skills_root()
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / manifest.name
    if target.exists() and not force:
        return _fail(f"{manifest.name} is already installed (use --force)", "exists")

    final_staging = target_root / f".{manifest.name}.staging-{uuid.uuid4().hex[:8]}"
    try:
        shutil.move(str(skill_root), str(final_staging))  # same-filesystem for the os.replace
        if target.exists():
            backup = target_root / f".{manifest.name}.old-{uuid.uuid4().hex[:8]}"
            os.replace(target, backup)
            shutil.rmtree(backup, ignore_errors=True)
        os.replace(final_staging, target)
    except Exception as e:
        shutil.rmtree(final_staging, ignore_errors=True)
        return _fail(f"atomic install failed: {e}", "install")
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    checks.append({"step": "install", "ok": True, "detail": str(target)})
    return InstallResult(
        ok=True, reason="installed", checks=checks, name=manifest.name, path=str(target)
    )

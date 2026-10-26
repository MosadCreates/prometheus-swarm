"""Discovery: scan the two skill roots and lazily import skill code.

Bundled skills live at ``agents/<agent>/skills/``; installed skills live at
``~/.prometheus/skills/<name>/`` (default install root — mirrors the daemon
data dir in ``prometheus/cli/daemon.py``). A same-named installed skill
shadows a bundled one. The scan reads **manifests only** — no imports at scan
time; skill code is imported lazily on first ``run()`` so one broken installed
skill can never take down the daemon.
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path
from typing import Any

from agents.skills.base import Skill
from agents.skills.manifest import VALID_AGENTS, SkillManifest, load_manifest_from_dir


def repo_root() -> Path:
    """Repository root (parents[2] from agents/skills/loader.py)."""
    return Path(__file__).resolve().parents[2]


def default_skills_root() -> Path:
    """Default install root for user skills: ``~/.prometheus/skills``."""
    return Path.home() / ".prometheus" / "skills"


def default_bundled_roots() -> list[Path]:
    """``agents/<agent>/skills`` for each known agent."""
    base = repo_root() / "agents"
    return [base / agent / "skills" for agent in sorted(VALID_AGENTS)]


def scan_roots(
    bundled_roots: list[Path] | None = None,
    skills_root: Path | None = None,
) -> list[SkillManifest]:
    """Scan bundled + installed roots for valid SKILL.md manifests.

    Directories without a valid SKILL.md are skipped — the tolerance for a
    mid-install state (Cross-cutting contract #3). Bundled manifests are
    collected first, then installed, so an installed skill of the same name
    shadows the bundled one downstream.
    """
    manifests: list[SkillManifest] = []
    roots = list(bundled_roots) if bundled_roots else default_bundled_roots()
    for base in roots:
        if not Path(base).is_dir():
            continue
        for child in sorted(p for p in Path(base).iterdir() if p.is_dir()):
            m = load_manifest_from_dir(child, root="bundled")
            if m is not None:
                manifests.append(m)
    sk_root = skills_root or default_skills_root()
    if Path(sk_root).is_dir():
        for child in sorted(p for p in Path(sk_root).iterdir() if p.is_dir()):
            m = load_manifest_from_dir(child, root="installed")
            if m is not None:
                manifests.append(m)
    return manifests


def load_skill_class(manifest: SkillManifest) -> type[Skill] | None:
    """Import a code skill's entry module and return its Skill subclass.

    Uses ``importlib.util.spec_from_file_location`` — the module is loaded in
    isolation under a unique name so it never pollutes ``sys.path`` and a
    broken skill only fails at its own ``run()`` site, not at scan time.
    Returns ``None`` when the entry module is missing or defines no
    ``Skill`` subclass.
    """
    if manifest.is_instruction():
        return None
    module_path = Path(manifest.path) / manifest.entry_module
    if not module_path.is_file():
        return None
    unique_name = f"agents.skills._loaded_{manifest.name}_{uuid.uuid4().hex[:8]}"
    try:
        spec = importlib.util.spec_from_file_location(unique_name, module_path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[unique_name] = module
        spec.loader.exec_module(module)
    except Exception:
        return None
    for attr in vars(module).values():
        if isinstance(attr, type) and issubclass(attr, Skill) and attr is not Skill:
            return attr
    return None


def validate_structural(manifest: SkillManifest) -> tuple[bool, str, list[str]]:
    """Structural gate: entry class subclasses Skill and has ``async run``.

    Returns ``(ok, reason, warnings)``. "Dangerous imports" is a **non-gating
    warning** — subprocess isolation is the real boundary, not import heuristics
    (see the Security Model in the plan).
    """
    if manifest.is_instruction():
        if not manifest.instruction_body.strip():
            return False, "instruction skill has an empty body", []
        return True, "", []
    cls = load_skill_class(manifest)
    if cls is None:
        return False, f"no Skill subclass found in {manifest.entry_module}", []
    if not hasattr(cls, "run") or not callable(getattr(cls, "run", None)):
        return False, f"{cls.__name__} does not define run()", []
    warnings: list[str] = []
    warnings.extend(_dangerous_import_warnings(manifest))
    return True, "", warnings


def _dangerous_import_warnings(manifest: SkillManifest) -> list[str]:
    """Non-gating static scan for imports a skill probably shouldn't need."""
    import re

    module_path = Path(manifest.path) / manifest.entry_module
    if not module_path.is_file():
        return []
    try:
        text = module_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    banned = {
        "subprocess",
        "os.system",
        "socket",
        "requests",
        "http.client",
        "shutil.rmtree",
        "pathlib.Path.unlink",
    }
    return [
        token
        for token in sorted(banned)
        if re.search(
            rf"(^|\b)import\s+{token}\b|from\s+{re.escape(token)}\s+import|\bos\.system\b", text
        )
    ]

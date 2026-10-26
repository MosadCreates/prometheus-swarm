"""User-installable skill platform (Phase 0).

Re-exports the public API for ``agents/skills``:
``Skill``, ``SkillRegistry``, ``SkillContext``, ``SkillResult``,
``SkillManifest``, plus the installer / signing surface used by the CLI.
"""

from agents.skills.base import Skill
from agents.skills.context import SkillContext, SkillResult
from agents.skills.installer import InstallResult, build_dry_run_context, install_source
from agents.skills.loader import (
    default_skills_root,
    load_skill_class,
    scan_roots,
    validate_structural,
)
from agents.skills.manifest import (
    SkillManifest,
    check_min_version,
    load_manifest_from_dir,
    parse_frontmatter,
)
from agents.skills.registry import SkillRegistry
from agents.skills.signing import (
    add_publisher,
    generate_keypair,
    is_trusted_publisher,
    load_publishers,
    publishers_path,
    save_publishers,
    sign_manifest,
    verify_manifest,
    verify_manifest_signature,
)

__all__ = [
    "Skill",
    "SkillContext",
    "SkillResult",
    "SkillManifest",
    "SkillRegistry",
    "InstallResult",
    "install_source",
    "build_dry_run_context",
    "scan_roots",
    "load_skill_class",
    "validate_structural",
    "default_skills_root",
    "load_manifest_from_dir",
    "parse_frontmatter",
    "check_min_version",
    "generate_keypair",
    "sign_manifest",
    "verify_manifest",
    "verify_manifest_signature",
    "add_publisher",
    "is_trusted_publisher",
    "load_publishers",
    "save_publishers",
    "publishers_path",
]

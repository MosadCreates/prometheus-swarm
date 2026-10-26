"""Phase 3 bundled-skill tests for Dissect.

Covers the six bundled skills shipped at ``agents/dissect/skills/``: each
manifest scans + validates structurally through the *real* bundled root (the
same root ``SkillRegistry.for_agent("dissect")`` scans in production), the
``DissectAgent`` mount sees all six, and each skill's ``run()`` returns the
documented ``ok=True`` detail for both the positive path and the *successful
negative* (e.g. ``locatable=False`` — a non-locatable crash is a result, not
a failure, so the promotion gate's ``consecutive_ok`` can still accumulate).
Empty-input grace and the run-never-raises contract are exercised through the
agent-facing ``self.skills.run(...)`` interface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agents.dissect.agent import DissectAgent
from agents.skills.context import SkillContext
from agents.skills.loader import validate_structural
from agents.skills.registry import SkillRegistry

REPO = Path(__file__).resolve().parents[2]
BUNDLED = REPO / "agents" / "dissect" / "skills"
DISSECT_SKILLS = {
    "crash_localizer",
    "error_signature_extractor",
    "patch_assertion_generator",
    "cascade_stats",
    "taxonomy_expander",
    "rule_generalizer",
}


# ── Helpers ───────────────────────────────────────────────────────────────


def _registry(tmp_path: Path) -> SkillRegistry:
    """Dissect-scoped registry over the real bundled root, isolated install root."""
    return SkillRegistry(
        agent="dissect",
        bundled_roots=[BUNDLED],
        skills_root=tmp_path / "no-installed-skills",
    )


def _ctx(**kwargs) -> SkillContext:
    return SkillContext(job_id="j1", agent="dissect", **kwargs)


# ── 1. All six bundled skills scan + validate + route to dissect ──────────


def test_all_six_bundled_skills_present_and_structurally_valid(tmp_path):
    reg = _registry(tmp_path)
    names = {m.name for m in reg.list()}
    assert names == DISSECT_SKILLS  # nothing missing, nothing unexpected

    for m in reg.list():
        assert m.root == "bundled"
        assert m.type == "code"
        assert m.deterministic is True
        assert m.requires_llm is False
        assert m.routes_to("dissect")
        ok, reason, _warnings = validate_structural(m)
        assert ok, f"{m.name}: structural validation failed: {reason}"


def test_bundled_skills_are_stamped_bundled_with_no_source_key(tmp_path):
    """Bundled manifests omit ``source`` (the scanner stamps root='bundled').

    ``SkillManifest.source`` defaults to ``"local"`` for every skill, so the
    bundled discriminator is ``root == "bundled"`` (which selects in-process
    execution) — and the authored file must not declare a ``source:`` line,
    which is reserved for installed skills.
    """
    reg = _registry(tmp_path)
    for m in reg.list():
        assert m.root == "bundled", f"{m.name} must be stamped bundled"
        dir_path = Path(m.path)
        frontmatter = (dir_path / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[1]
        assert "source:" not in frontmatter, f"{m.name} must not declare a source key"
        assert (dir_path / "skill.py").is_file(), f"{m.name} missing skill.py"
        assert (dir_path / "SKILL.md").is_file(), f"{m.name} missing SKILL.md"


# ── 2. The DissectAgent mount sees the bundled root ───────────────────────


def test_dissect_agent_skills_mount_sees_all_six(monkeypatch, tmp_path):
    """Production wiring: ``BaseAgent``-mounted registry picks up all 6."""
    # Isolate from any installed skills in ~/.prometheus/skills — a same-named
    # installed skill shadows the bundled one, so assert bundled only when the
    # install root is empty. This keeps the test deterministic on a machine
    # where the user has installed a shadow (e.g. the guide's demo).
    monkeypatch.setattr(
        "agents.skills.loader.default_skills_root",
        lambda: tmp_path / "no-installed-skills",
    )
    agent = DissectAgent("j1")
    assert agent.skills.agent == "dissect"
    for name in DISSECT_SKILLS:
        assert agent.skills.get(name) is not None, f"{name} missing from agent mount"
        assert agent.skills.get(name).routes_to("dissect")
    assert agent.skills.get("crash_localizer").root == "bundled"


# ── 3. crash_localizer ────────────────────────────────────────────────────

TRACEBACK = """\
Traceback (most recent call last):
  File "C:/venv/Lib/site-packages/lightgbm/sklearn.py", line 812, in fit
    super().fit(X, y)
  File "C:/Users/moham/OneDrive/Desktop/prometheus-swarm/scripts/training_script_j1.py", line 3, in <module>
    model.fit(X, y)
"""


@pytest.mark.asyncio
async def test_crash_localizer_prefers_script_frame(tmp_path):
    """Traceback with a script-local frame → that frame, line, snippet, 0.9."""
    reg = _registry(tmp_path)
    ctx = _ctx(paths={"script_path": "training_script_j1.py"}, kwargs={"traceback": TRACEBACK})
    res = await reg.run(
        "crash_localizer",
        ctx,
        script_snippet="import lightgbm\nmodel = lgb.LGBMClassifier()\nmodel.fit(X, y)\n",
    )
    assert res.ok
    d = res.detail
    assert d["locatable"] is True
    assert d["file"].endswith("training_script_j1.py")
    assert d["line"] == 3
    assert d["function"] == "<module>"
    assert d["snippet"] == "model.fit(X, y)"
    assert d["confidence"] == 0.9


@pytest.mark.asyncio
async def test_crash_localizer_message_fallback(tmp_path):
    """No traceback, but a 'line 42, in train' message → low-confidence locate."""
    reg = _registry(tmp_path)
    res = await reg.run(
        "crash_localizer", _ctx(kwargs={"exception_message": "error: line 42, in train"})
    )
    assert res.ok
    d = res.detail
    assert d["locatable"] is True
    assert d["line"] == 42
    assert d["function"] == "train"
    assert d["file"] == ""
    assert d["confidence"] == 0.4


@pytest.mark.asyncio
async def test_crash_localizer_successful_negative(tmp_path):
    """Empty context → ok=True with locatable=False (a result, not a failure)."""
    reg = _registry(tmp_path)
    res = await reg.run("crash_localizer", _ctx())
    assert res.ok
    d = res.detail
    assert d["locatable"] is False
    assert d["line"] is None and d["function"] is None
    assert d["confidence"] == 0.0


# ── 4. error_signature_extractor ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_error_signature_extractor_normalizes(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "error_signature_extractor",
        _ctx(),
        category="shape_mismatch",
        exception_type="ValueError",
        exception_message="  shapes (32, 3)   and (5,)  not aligned  ",
    )
    assert res.ok
    d = res.detail
    assert d["category"] == "shape_mismatch"
    assert d["exception_type"] == "ValueError"
    assert d["message_normalized"] == "shapes (32, 3) and (5,) not aligned"  # whitespace collapsed
    assert len(d["message_hash"]) == 16
    assert d["pipeline_stage"] == "training"  # default stage
    assert d["signature"] == f"shape_mismatch::{d['message_normalized'][:60]}::{d['message_hash']}"


@pytest.mark.asyncio
async def test_error_signature_extractor_stable_across_spacing(tmp_path):
    """Whitespace-normalization means the same error yields the same signature."""
    reg = _registry(tmp_path)
    a = await reg.run(
        "error_signature_extractor",
        _ctx(),
        category="c",
        exception_message="name 'np' is not defined",
    )
    b = await reg.run(
        "error_signature_extractor",
        _ctx(),
        category="c",
        exception_message="name  'np'  is   not defined",
    )
    assert a.ok and b.ok
    assert a.detail["message_hash"] == b.detail["message_hash"]


# ── 5. patch_assertion_generator ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_patch_assertions_pass_on_good_patch(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "patch_assertion_generator",
        _ctx(),
        original_script="import numpy as np\n\ndef train():\n    model.fit(X, y)\n",
        patched_script="import numpy as np\n\ndef train():\n    model.fit(X, np.asarray(y))\n",
        exception_type="NameError",
        exception_message="name 'np' is not defined",
        diff="-    model.fit(X, y)\n+    model.fit(X, np.asarray(y))\n",
    )
    assert res.ok
    d = res.detail
    by_name = {a["name"]: a["passed"] for a in d["assertions"]}
    assert set(by_name) == {
        "patch_is_ast_valid",
        "no_duplicate_top_level_defs",
        "crash_name_resolved",
        "entry_preserved",
    }
    assert all(by_name.values()), by_name
    assert d["passed"] is True
    assert "np.asarray" in d["diff"]


@pytest.mark.asyncio
async def test_patch_assertions_flag_duplicate_defs(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "patch_assertion_generator",
        _ctx(),
        original_script="def train():\n    model.fit(X, y)\n",
        patched_script="def train():\n    pass\ndef train():\n    pass\n",
        exception_type="ValueError",  # not NameError/ImportError → name check trivially passes
        exception_message="shapes mismatch",
    )
    assert res.ok
    by_name = {a["name"]: a["passed"] for a in res.detail["assertions"]}
    assert by_name["patch_is_ast_valid"] is True
    assert by_name["no_duplicate_top_level_defs"] is False
    assert by_name["entry_preserved"] is True  # 'train' still present
    assert res.detail["passed"] is False


@pytest.mark.asyncio
async def test_patch_assertions_empty_patch_is_graceful(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run("patch_assertion_generator", _ctx())
    assert res.ok
    assert res.detail == {"assertions": [], "reason": "no patched script"}


# ── 6. cascade_stats ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cascade_stats_aggregates(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "cascade_stats",
        _ctx(),
        level="L1",
        resolved=True,
        is_terminal=False,
        category="shape_mismatch",
        cascade_path=[
            {"level": "L0", "outcome": "miss"},
            {"level": "L1", "outcome": "hit"},
        ],
    )
    assert res.ok
    d = res.detail
    assert d["levels_tried"] == ["L0", "L1"]
    assert d["outcomes"] == ["miss", "hit"]
    assert d["final_level"] == "L1" and d["resolved"] is True and d["is_terminal"] is False
    assert "levels=[L0,L1]" in d["summary"]
    assert "resolved=True" in d["summary"]
    assert "category=shape_mismatch" in d["summary"]


@pytest.mark.asyncio
async def test_cascade_stats_empty_path(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run("cascade_stats", _ctx())
    assert res.ok
    assert res.detail["levels_tried"] == []
    assert "levels=[-]" in res.detail["summary"]  # no crash on empty path


# ── 7. taxonomy_expander ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_taxonomy_expander_suggests_at_low_confidence(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "taxonomy_expander",
        _ctx(),
        exception_type="RuntimeError",
        exception_message="CUDA out of memory. Tried to allocate 2.00 GiB",
        category="unknown",
        confidence=0.3,
    )
    assert res.ok
    d = res.detail
    assert d["suggested"] == "out_of_memory"
    assert d["current"] == "unknown"
    assert d["low_confidence"] is True
    assert d["candidate_pattern"]  # the regex that fired


@pytest.mark.asyncio
async def test_taxonomy_expander_silent_at_high_confidence(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "taxonomy_expander",
        _ctx(),
        exception_message="out of memory",
        category="shape_mismatch",
        confidence=0.8,
    )
    assert res.ok
    assert res.detail["suggested"] is None
    assert res.detail["reason"] == "high confidence"


@pytest.mark.asyncio
async def test_taxonomy_expander_no_hint_is_graceful(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "taxonomy_expander",
        _ctx(),
        exception_message="something completely unknown happened",
        confidence=0.2,
    )
    assert res.ok
    assert res.detail["suggested"] is None
    assert res.detail["reason"] == "no known hint"


# ── 8. rule_generalizer ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_generalizer_blanks_volatile_tokens(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run(
        "rule_generalizer",
        _ctx(),
        category="out_of_memory",
        exception_message="unable to allocate 5.0 GiB for tensor with shape (128, 3)",
        diff="-    X = X.astype(float64)\n+    X = X.astype(float32)\n",
        patch_id="j1::L2",
    )
    assert res.ok
    rule = res.detail["rule"]
    assert rule is not None
    assert rule["category"] == "out_of_memory"
    # readable pattern: every volatile token (5.0, 128, 3) blanked to <*>
    assert rule["message_pattern"] == "unable to allocate <*> GiB for tensor with shape (<*>, <*>)"
    assert rule["message_pattern_regex"].startswith("^")
    assert rule["message_pattern_regex"].endswith("$")
    assert ".*?" in rule["message_pattern_regex"]
    assert rule["patch_diff"].startswith("-    X = X.astype")
    assert rule["patch_id"] == "j1::L2"


@pytest.mark.asyncio
async def test_rule_generalizer_empty_message_is_graceful(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run("rule_generalizer", _ctx(), category="foo")
    assert res.ok
    assert res.detail == {"rule": None, "reason": "empty message"}


# ── 9. Skills run against a real captured mission context (fixture) ───────


@pytest.mark.asyncio
async def test_crash_localizer_on_real_fixture_context(tmp_path):
    """The Phase-1 per-agent compat fixture (real brief/spec/paths) feeds the skill."""
    fixture = json.loads(
        (REPO / "tests" / "fixtures" / "skill_contexts" / "dissect.json").read_text(
            encoding="utf-8"
        )
    )
    script_path = fixture["paths"]["script_path"]
    tb = f"""\
Traceback (most recent call last):
  File "C:/venv/Lib/site-packages/pandas/core/frame.py", line 999, in __getattr__
    raise AttributeError
  File "{script_path}", line 3, in <module>
    model.fit(X_train, y_train)
"""
    reg = _registry(tmp_path)
    res = await reg.run(
        "crash_localizer",
        SkillContext(
            job_id="j1",
            agent="dissect",
            brief=fixture["brief"],
            spec=fixture["spec"],
            paths=fixture["paths"],
        ),
        traceback=tb,
    )
    assert res.ok
    assert res.detail["locatable"] is True
    assert res.detail["file"] == script_path  # the fixture's own script wins
    assert res.detail["line"] == 3


# ── 10. run() contract: never raises, missing skill is a clean ok=False ───


@pytest.mark.asyncio
async def test_run_never_raises_for_missing_skill(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run("does_not_exist", _ctx())
    assert res.ok is False
    assert "not found" in res.reason


@pytest.mark.asyncio
async def test_run_populates_duration_and_skill_name(tmp_path):
    reg = _registry(tmp_path)
    res = await reg.run("cascade_stats", _ctx(), cascade_path=[{"level": "L0", "outcome": "hit"}])
    assert res.ok
    assert res.skill == "cascade_stats"
    assert res.duration_ms >= 0

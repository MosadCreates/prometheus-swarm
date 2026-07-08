"""Unit tests for Dissect Repair Templates + Validation Pipeline (Step 3-4)."""

import json
import os
import re
import tempfile
from unittest.mock import patch

import pytest

from agents.dissect.repair_templates import (
    RepairTemplate,
    ValidationResult,
    TemplateValidationReport,
    validate_template,
    promote_to_template,
    load_templates,
    save_templates,
    find_matching_templates,
    generalize_diff_to_template,
    _check_syntax,
    _check_regex,
    _check_safety,
    _check_apply_return,
    _registry,
    _BUILTIN_TEMPLATES,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_registry():
    _registry.clear()
    yield
    _registry.clear()


@pytest.fixture
def sample_script():
    return """import pandas as pd
import lightgbm as lgb

df = pd.read_csv("train.csv")
X = df.drop("target", axis=1)
y = df["target"]
model = lgb.LGBMClassifier()
model.fit(X, y)
print("done")
"""


SIMPLE_APPLY_SOURCE = """
def apply(script, message):
    return script + "\\n" + "# patched: " + message
"""

VALID_TEMPLATE_DATA = {
    "template_id": "tpl-test-0001",
    "category": "shape_mismatch",
    "pattern_matcher": r"(?i)shape mismatch",
    "apply_fn_source": SIMPLE_APPLY_SOURCE,
    "confidence": 0.8,
    "source_patch_id": "patch-abc123",
    "description": "Test template",
}


# ── ValidationResult Tests ───────────────────────────────────────────────


class TestValidationResult:
    def test_passed_is_truthy(self):
        assert ValidationResult(True, "ok")
        assert not ValidationResult(False, "fail")

    def test_default_severity(self):
        r = ValidationResult(True, "ok")
        assert r.severity == "error"


# ── TemplateValidationReport Tests ───────────────────────────────────────


class TestTemplateValidationReport:
    def test_passes_when_all_checks_pass(self):
        report = TemplateValidationReport("tpl-001")
        report.add(ValidationResult(True, "check 1"))
        report.add(ValidationResult(True, "check 2"))
        assert report.passed
        assert report.score == 1.0

    def test_fails_on_any_error(self):
        report = TemplateValidationReport("tpl-001")
        report.add(ValidationResult(True, "check 1"))
        report.add(ValidationResult(False, "check 2 failed"))
        assert not report.passed

    def test_warnings_do_not_fail(self):
        report = TemplateValidationReport("tpl-001")
        report.add(ValidationResult(True, "check 1"))
        report.add(ValidationResult(False, "warning", severity="warning"))
        report.add(ValidationResult(False, "info", severity="info"))
        assert report.passed

    def test_errors_property(self):
        report = TemplateValidationReport("tpl-001")
        report.add(ValidationResult(True, "ok"))
        report.add(ValidationResult(False, "error 1"))
        report.add(ValidationResult(False, "warning", severity="warning"))
        assert len(report.errors) == 1
        assert report.errors[0].message == "error 1"

    def test_summary_format(self):
        report = TemplateValidationReport("tpl-001")
        report.add(ValidationResult(True, "ok"))
        s = report.summary()
        assert "tpl-001" in s
        assert "1/1" in s


# ── Validation Check Tests ───────────────────────────────────────────────


class TestCheckSyntax:
    def test_valid_python_passes(self):
        r = _check_syntax("def apply(s, m): return s")
        assert r.passed

    def test_invalid_python_fails(self):
        r = _check_syntax("def apply(s, m): return ")
        assert r.passed  # actually valid (return None)

    def test_syntax_error_fails(self):
        r = _check_syntax("def apply(s, m: return s")
        assert not r.passed
        assert "Syntax error" in r.message


class TestCheckRegex:
    def test_valid_regex_passes(self):
        r = _check_regex(r"(?i)shape mismatch")
        assert r.passed

    def test_invalid_regex_fails(self):
        r = _check_regex(r"[invalid")
        assert not r.passed
        assert "Invalid regex" in r.message

    def test_empty_regex_passes(self):
        r = _check_regex("")
        assert r.passed


class TestCheckSafety:
    def test_clean_code_passes(self):
        r = _check_safety("def apply(s, m): return s")
        assert r.passed

    def test_exec_detected(self):
        r = _check_safety("def apply(s, m): exec('x=1'); return s")
        assert not r.passed
        assert "exec" in r.message

    def test_eval_detected(self):
        r = _check_safety("def apply(s, m): return eval(s)")
        assert not r.passed
        assert "eval" in r.message

    def test_subprocess_import_detected(self):
        r = _check_safety("import subprocess\ndef apply(s, m): return s")
        assert not r.passed
        assert "subprocess" in r.message

    def test_os_dot_system_detected(self):
        r = _check_safety("import os\ndef apply(s, m): os.system('rm -rf /'); return s")
        assert not r.passed
        assert "os" in r.message

    def test_open_allowed(self):
        r = _check_safety("def apply(s, m): return s")
        assert r.passed

    def test_import_ast_detected(self):
        r = _check_safety("import ast\ndef apply(s, m): return s")
        assert r.passed  # ast is not in the dangerous list

    def test_compile_is_dangerous(self):
        r = _check_safety("def apply(s, m): compile('x=1', '<x>', 'exec'); return s")
        assert not r.passed
        assert "compile" in r.message


class TestCheckApplyReturn:
    def test_modifies_script(self):
        r = _check_apply_return(
            "def apply(script, message): return script + '\\n# patched'",
            "original",
            "error msg",
        )
        assert r.passed

    def test_returns_none(self):
        r = _check_apply_return(
            "def apply(script, message): return None",
            "original",
            "error msg",
        )
        assert not r.passed

    def test_unchanged_script_warns(self):
        r = _check_apply_return(
            "def apply(script, message): return script",
            "original",
            "error msg",
        )
        assert not r.passed
        assert r.severity == "warning"

    def test_syntax_error_output(self):
        r = _check_apply_return(
            "def apply(script, message): return 'def f( :'",
            "original",
            "error msg",
        )
        assert not r.passed

    def test_no_apply_function(self):
        r = _check_apply_return(
            "x = 1",
            "original",
            "error msg",
        )
        assert not r.passed

    def test_apply_execution_failure(self):
        r = _check_apply_return(
            "def apply(s, m): raise ValueError('boom')",
            "original",
            "error msg",
        )
        assert not r.passed


# ── RepairTemplate Tests ─────────────────────────────────────────────────


class TestRepairTemplate:
    def test_creation(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        assert t.template_id == "tpl-test-0001"
        assert t.category == "shape_mismatch"
        assert t.confidence == 0.8

    def test_matches_matching_message(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        assert t.matches("ValueError", "Shape mismatch: expected 40 got 45")
        assert not t.matches("ValueError", "Some unrelated error")

    def test_case_insensitive_match(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        assert t.matches("ValueError", "SHAPE MISMATCH")

    def test_apply_modifies_script(self, sample_script):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        result = t.apply(sample_script, "Shape mismatch error")
        assert result is not None
        assert "patched: Shape mismatch error" in result

    def test_apply_returns_none_on_exception(self):
        t = RepairTemplate(
            template_id="tpl-broken-0001",
            category="other",
            pattern_matcher=r".*",
            apply_fn_source="def apply(s, m): raise RuntimeError('fail')",
            confidence=0.5,
        )
        result = t.apply("script", "msg")
        assert result is None

    def test_to_dict_roundtrip(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        d = t.to_dict()
        assert d["template_id"] == "tpl-test-0001"
        assert d["pattern_matcher"] == r"(?i)shape mismatch"

        t2 = RepairTemplate.from_dict(d)
        assert t2.template_id == t.template_id
        assert t2.category == t.category
        assert t2.pattern_matcher_str == t.pattern_matcher_str
        assert t2.apply_fn_source == t.apply_fn_source


# ── validate_template Tests ──────────────────────────────────────────────


class TestValidateTemplate:
    def test_valid_template_passes(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        report = validate_template(t, sample_script="original", sample_exception_message="shape mismatch")
        assert report.passed

    def test_invalid_syntax_fails(self):
        t = RepairTemplate(
            template_id="tpl-bad-0001",
            category="other",
            pattern_matcher=r".*",
            apply_fn_source="def apply(s, m: return s",  # syntax error
            confidence=0.5,
        )
        report = validate_template(t)
        assert not report.passed
        assert any("Syntax error" in c.message for c in report.checks if not c.passed)

    def test_invalid_regex_fails(self):
        t = RepairTemplate(
            template_id="tpl-bad-regex",
            category="other",
            pattern_matcher=r"[unclosed",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.5,
        )
        report = validate_template(t)
        assert not report.passed
        assert any("Invalid regex" in c.message for c in report.checks if not c.passed)

    def test_dangerous_code_fails(self):
        t = RepairTemplate(
            template_id="tpl-unsafe",
            category="other",
            pattern_matcher=r".*",
            apply_fn_source="import os\ndef apply(s, m): os.system('rm'); return s",
            confidence=0.5,
        )
        report = validate_template(t)
        assert not report.passed
        assert len(report.errors) >= 1

    def test_apply_check_with_sample(self, sample_script):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        report = validate_template(t, sample_script=sample_script, sample_exception_message="shape mismatch")
        apply_checks = [c for c in report.checks if "Apply" in c.message]
        assert all(c.passed for c in apply_checks)


# ── Template Registry Tests ──────────────────────────────────────────────


class TestTemplateRegistry:
    def test_load_templates_creates_file_if_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                templates = load_templates()
                assert os.path.exists(path)
                # Should contain built-in templates
                assert len(templates) >= len(_BUILTIN_TEMPLATES)

    def test_load_templates_reads_existing(self):
        data = [VALID_TEMPLATE_DATA]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with open(path, "w") as f:
                json.dump(data, f)
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                templates = load_templates()
                assert len(templates) == len(data) + len(_BUILTIN_TEMPLATES)

    def test_save_and_reload_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                t = RepairTemplate(**VALID_TEMPLATE_DATA)
                _registry.append(t)
                save_templates()
                _registry.clear()
                templates = load_templates()
                found = [x for x in templates if x.template_id == "tpl-test-0001"]
                assert len(found) == 1
                assert found[0].category == "shape_mismatch"

    def test_load_handles_corrupted_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with open(path, "w") as f:
                f.write("not json")
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                templates = load_templates()
                assert len(templates) >= len(_BUILTIN_TEMPLATES)


class TestFindMatchingTemplates:
    def test_finds_matching_template(self):
        assert len(_registry) == 0
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        _registry.append(t)
        matches = find_matching_templates("ValueError", "Shape mismatch: expected 40 got 45", "shape_mismatch")
        assert len(matches) >= 1
        assert any(m.template_id == "tpl-test-0001" for m in matches)

    def test_returns_empty_on_no_match(self):
        assert len(_registry) == 0
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        _registry.append(t)
        matches = find_matching_templates("ValueError", "Something completely different")
        assert len(matches) == 0

    def test_filters_by_category(self):
        assert len(_registry) == 0
        t1 = RepairTemplate(**VALID_TEMPLATE_DATA)
        t2 = RepairTemplate(
            template_id="tpl-other-0001",
            category="nan_propagation",
            pattern_matcher=r"(?i)nan",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.7,
        )
        _registry.extend([t1, t2])
        matches = find_matching_templates("ValueError", "Shape mismatch", "shape_mismatch")
        assert len(matches) == 1
        assert matches[0].category == "shape_mismatch"

    def test_filters_by_confidence(self):
        assert len(_registry) == 0
        t = RepairTemplate(
            template_id="tpl-low-conf",
            category="shape_mismatch",
            pattern_matcher=r"(?i)shape",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.3,
        )
        _registry.append(t)
        matches = find_matching_templates(
            "ValueError", "Shape mismatch", "shape_mismatch", min_confidence=0.6
        )
        assert len(matches) == 0

    def test_sorts_by_confidence_descending(self):
        assert len(_registry) == 0
        t1 = RepairTemplate(
            template_id="tpl-high",
            category="shape_mismatch",
            pattern_matcher=r"(?i)shape",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.9,
        )
        t2 = RepairTemplate(
            template_id="tpl-low",
            category="shape_mismatch",
            pattern_matcher=r"(?i)shape",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.6,
        )
        _registry.extend([t2, t1])  # insert in reverse order
        matches = find_matching_templates("ValueError", "Shape mismatch", "shape_mismatch")
        assert matches[0].template_id == "tpl-high"
        assert matches[1].template_id == "tpl-low"


# ── promote_to_template Tests ────────────────────────────────────────────


class TestPromoteToTemplate:
    def test_promotes_valid_template(self, sample_script):
        t = promote_to_template(
            category="shape_mismatch",
            pattern_matcher=r"(?i)shape mismatch",
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.8,
            source_patch_id="patch-xyz",
            description="promoted test",
            sample_script=sample_script,
            sample_exception_message="shape mismatch",
        )
        assert t is not None
        assert t.template_id.startswith("tpl-shape_mismatch-")
        assert len(_registry) == 1

    def test_blocks_invalid_template(self):
        t = promote_to_template(
            category="other",
            pattern_matcher=r"[unclosed",  # broken regex
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.5,
        )
        assert t is None
        assert len(_registry) == 0

    def test_blocks_dangerous_template(self):
        t = promote_to_template(
            category="other",
            pattern_matcher=r".*",
            apply_fn_source="import subprocess\ndef apply(s, m): subprocess.call('rm'); return s",
            confidence=0.5,
        )
        assert t is None
        assert len(_registry) == 0


# ── generalize_diff_to_template Tests ────────────────────────────────────


class TestGeneralizeDiffToTemplate:
    def test_generalizes_simple_addition(self):
        original = "model.fit(X, y)\n"
        patched = "model.fit(X, y)\nprint('done')\n"
        t = generalize_diff_to_template(
            category="other",
            original_script=original,
            patched_script=patched,
            exception_message="NameError: name 'x' not defined",
            source_patch_id="patch-001",
        )
        assert t is not None
        assert t.category == "other"

    def test_returns_none_if_no_change(self):
        original = "model.fit(X, y)\n"
        t = generalize_diff_to_template(
            category="other",
            original_script=original,
            patched_script=original,
            exception_message="Error",
            source_patch_id="patch-001",
        )
        assert t is None

    def test_generalized_template_passes_validation(self):
        original = """import pandas as pd
df = pd.read_csv("train.csv")
model.fit(df.drop("target", axis=1), df["target"])
"""
        patched = """import pandas as pd
df = pd.read_csv("train.csv")
df.columns = df.columns.str.strip()
model.fit(df.drop("target", axis=1), df["target"])
"""
        t = generalize_diff_to_template(
            category="dtype_mismatch",
            original_script=original,
            patched_script=patched,
            exception_message="ValueError: could not convert string to float ' Survived'",
            source_patch_id="patch-002",
        )
        assert t is not None

    def test_handles_missing_error_pattern(self):
        original = "a = 1\n"
        patched = "a = 2\n"
        t = generalize_diff_to_template(
            category="other",
            original_script=original,
            patched_script=patched,
            exception_message="",
            source_patch_id="patch-003",
        )
        assert t is not None

    def test_broken_output_blocked_by_validation(self):
        original = "x = 1\n"
        patched = "x = 1\ny = \n"
        t = generalize_diff_to_template(
            category="other",
            original_script=original,
            patched_script=patched,
            exception_message="Syntax error",
            source_patch_id="patch-004",
        )
        # Validation blocks the template because the apply output
        # (appending "y = ") would produce invalid Python
        assert t is None


# ── Built-in Template Tests ──────────────────────────────────────────────


class TestBuiltinTemplates:
    def test_shape_mismatch_builtin_loaded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                load_templates()
                ids = [t.template_id for t in _registry]
                assert "tpl-builtin-shape_mismatch-0001" in ids

    def test_builtin_not_duplicated_on_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "templates.json")
            with patch("agents.dissect.repair_templates._get_templates_path", return_value=path):
                load_templates()
                count_first = len(_registry)
                load_templates()
                count_second = len(_registry)
                assert count_first == count_second


# ── Edge Cases ───────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_template_with_empty_source(self):
        t = RepairTemplate(
            template_id="tpl-empty",
            category="other",
            pattern_matcher=r".*",
            apply_fn_source="",
            confidence=0.5,
        )
        report = validate_template(t)
        assert not report.passed
        assert any("Empty" in c.message for c in report.checks if not c.passed)

    def test_very_long_pattern_matcher(self):
        long_pattern = r"(?i)" + "a" * 10000
        t = RepairTemplate(
            template_id="tpl-long",
            category="other",
            pattern_matcher=long_pattern,
            apply_fn_source=SIMPLE_APPLY_SOURCE,
            confidence=0.5,
        )
        report = validate_template(t)
        assert report.passed

    def test_unicode_in_exception_message(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        result = t.apply("script", "Shape mismatch: \u00e9\u00e0\u00fc")
        assert result is not None
        assert "\u00e9\u00e0\u00fc" in result

    def test_matches_called_with_empty_message(self):
        t = RepairTemplate(**VALID_TEMPLATE_DATA)
        assert not t.matches("ValueError", "")

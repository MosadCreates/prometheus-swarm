"""Unit tests for Dissect rule-based quick patches (no LLM)."""

from agents.dissect.rules import (
    fix_name_error,
    fix_import_error,
    fix_dtype_mismatch,
    fix_nan_propagation,
    fix_zero_division,
    fix_permission_error,
    fix_syntax_error,
    apply_rule,
)


def test_fix_name_error_false():
    script = "if false == true:\n    x = null\n"
    result = fix_name_error(script, "name 'false' is not defined")
    assert result is not None
    assert "False" in result
    assert "True" in result
    assert "None" in result
    assert "false" not in result
    assert "true" not in result
    assert "null" not in result


def test_fix_name_error_no_match():
    result = fix_name_error("x = 42", "some other error")
    assert result is None


def test_fix_name_error_boundary():
    script = "if false_flag == True:\n    x = null_value\n"
    result = fix_name_error(script, "name 'false' is not defined")
    assert result is not None
    assert "false_flag" in result
    assert "null_value" in result
    assert "False" in result or "True" in result


def test_fix_import_error():
    script = "import pandas\nprint('hello')\n"
    result = fix_import_error(script, "ModuleNotFoundError: No module named 'lightgbm'")
    assert result is not None
    assert "subprocess" in result
    assert "lightgbm" in result
    assert "check_call" in result


def test_fix_import_error_no_match():
    result = fix_import_error("x = 1", "ValueError: something else")
    assert result is None


def test_fix_import_error_duplicate_safe():
    script = "import pandas\n"
    result = fix_import_error(script, "No module named 'lightgbm'")
    assert result is not None
    result2 = fix_import_error(result, "No module named 'lightgbm'")
    assert result2 is not None
    assert result2.count("import subprocess") == 1
    assert result2 == result


def test_fix_dtype_mismatch():
    script = "X = pd.DataFrame({'a': [1, 2]})\ny = [0, 1]\nmodel.fit(X, y)\n"
    result = fix_dtype_mismatch(script, "ValueError: could not convert string to float: 'abc'")
    assert result is not None
    assert "pd.to_numeric" in result
    assert "[Dissect hotfix]" in result


def test_fix_dtype_mismatch_no_match():
    result = fix_dtype_mismatch("x = 1", "ValueError: shape mismatch")
    assert result is None


def test_fix_dtype_mismatch_idempotent():
    script = "X = pd.DataFrame({'a': [1, 2]})\ny = [0, 1]\n"
    result = fix_dtype_mismatch(script, "could not convert string to float: 'abc'")
    assert result is not None
    result2 = fix_dtype_mismatch(result, "could not convert string to float: 'abc'")
    assert result == result2


def test_fix_nan_propagation():
    script = "X = pd.DataFrame()\nmodel.fit(X, y)\n"
    result = fix_nan_propagation(script, "ValueError: Input contains NaN")
    assert result is not None
    assert "SimpleImputer" in result
    assert "strategy='median'" in result
    assert "strategy='most_frequent'" in result


def test_fix_nan_propagation_no_match():
    result = fix_nan_propagation("x = 1", "ValueError: shape mismatch")
    assert result is None


def test_fix_zero_division():
    script = "accuracy = correct / total\n"
    result = fix_zero_division(script, "ZeroDivisionError: division by zero")
    assert result is not None
    assert "1e-8" in result
    assert "correct / (total + 1e-8)" in result or "correct/(total + 1e-8)" in result


def test_fix_zero_division_no_match():
    result = fix_zero_division("x = 1", "ValueError: shape")
    assert result is None


def test_fix_permission_error():
    script = "import pandas\nmodel.save('outputs/model.pkl')\n"
    result = fix_permission_error(
        script, "PermissionError: [Errno 13] Permission denied: 'outputs'"
    )
    assert result is not None
    assert "makedirs" in result


def test_fix_permission_error_no_match():
    result = fix_permission_error("x = 1", "ValueError: shape")
    assert result is None


def test_fix_syntax_error():
    script = "model.fit(X, y, max_iter=100, early_stopping=True, 42)"
    result = fix_syntax_error(script, "SyntaxError: positional argument follows keyword argument")
    assert result is not None
    args = result.split("(")[1].split(")")[0]
    parts = [a.strip() for a in args.split(",")]
    kw_start = min((i for i, p in enumerate(parts) if "=" in p), default=len(parts))
    for i, p in enumerate(parts):
        if i < kw_start:
            assert "=" not in p, f"Positional args should come first, got {p}"
        else:
            assert "=" in p, f"Keyword args should come last, got {p}"


def test_fix_syntax_error_no_match():
    result = fix_syntax_error("x = 1", "ValueError: shape mismatch")
    assert result is None


def test_apply_rule_dispatches():
    script = "if false:\n    pass\n"
    result = apply_rule("name_error", script, "name 'false' is not defined")
    assert result is not None
    assert "False" in result


def test_apply_rule_unknown_category():
    result = apply_rule("shape_mismatch", "x = 1", "shape error")
    assert result is None

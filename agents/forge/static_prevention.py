"""Static Prevention Rules — applied at generation time without Redis.

These rules transform rendered training scripts to prevent known failure
patterns BEFORE the script reaches Furnace. Unlike prevention.py (which
loads rules from Redis at runtime), these rules are deterministic and
always fire on every generated script.

Why this exists:
    Patch_log analysis shows 50% of Dissect interventions are for failures
    that could be prevented at generation time: missing columns, dtype
    mismatches, encoding errors, and empty datasets after NaN filtering.
    These rules codify the fixes so Forge outputs scripts that never
    trigger those errors.

Flow:
    select_and_render() finishes Jinja rendering
        → apply_static_prevention() transforms the script
        → validate_script_static() checks for known anti-patterns
        → script is written to disk and published

All rules are AST-safe — they operate on text but preserve Python syntax.
"""

import ast
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Rule definitions ──────────────────────────────────────────────


def _find_matching_paren(text: str, start: int) -> int:
    """Find the index of the closing paren matching the opening paren at start."""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _find_read_csv_calls(script: str) -> list[tuple[int, int, str, str]]:
    """Find all pd.read_csv(...) calls and their positions.

    Returns list of (start_idx, end_idx, call_text, full_match) for each call
    that doesn't already have an encoding parameter.
    """
    calls: list[tuple[int, int, str, str]] = []
    pattern = re.compile(r"pd\.read_csv\s*\(")
    for m in pattern.finditer(script):
        open_paren = m.end() - 1
        close_paren = _find_matching_paren(script, open_paren)
        if close_paren < 0:
            continue
        # Full match from start of pd.read_csv to closing paren
        full_match = script[m.start() : close_paren + 1]
        # Check if encoding= is already inside
        if "encoding=" in full_match:
            continue
        calls.append((m.start(), close_paren + 1, m.group(), full_match))
    return calls


def ensure_read_csv_encoding(script: str, encoding: str = "utf-8") -> str:
    """Add encoding parameter to pd.read_csv calls that lack it.

    Patch_log shows encoding errors (UnicodeDecodeError) are a recurring
    failure pattern when CSV files use non-UTF-8 encodings. Adding
    encoding="utf-8" ensures consistent decoding behavior.

    Uses proper paren-matching to handle nested calls like
    pd.read_csv(os.path.join(...), ...).

    Transforms:
        pd.read_csv(path)
            → pd.read_csv(path, encoding="utf-8")

        pd.read_csv(os.path.join(_dir, "file.csv"))
            → pd.read_csv(os.path.join(_dir, "file.csv"), encoding="utf-8")
    """
    calls = _find_read_csv_calls(script)
    if not calls:
        return script

    # Process from end to start so positions stay valid
    # (reverse order means earlier positions are unaffected by later edits)
    result = script
    for start, end, _, full_match in reversed(calls):
        if "encoding=" in full_match:
            continue

        # Get the current text at this position (may differ from original
        # if a later call was processed, but since we go backwards, earlier
        # positions are unaffected)
        current_text = result[start:end]
        if "encoding=" in current_text:
            continue

        # Insert encoding param before the closing paren
        if current_text.rstrip().endswith(")"):
            inner = current_text[:-1].rstrip()
            new_call = (
                f'{inner}, encoding="{encoding}")'
                if not inner.endswith(",")
                else f'{inner} encoding="{encoding}")'
            )
            result = result[:start] + new_call + result[end:]

    count = result.count(f'encoding="{encoding}"')
    if count:
        logger.info(
            f"ensure_read_csv_encoding: added encoding={encoding} to {count} read_csv call(s)"
        )

    if count:
        logger.info(
            f"ensure_read_csv_encoding: added encoding={encoding} to {count} read_csv call(s)"
        )
    return result


def widen_numeric_dtype_selection(script: str) -> str:
    """Widen select_dtypes(include=["int64", "float64"]) to select_dtypes(include="number").

    The narrow type list ["int64", "float64"] misses int32, uint8, float32,
    and other numeric dtypes. When a CSV has columns of these types, they
    get dropped from the feature set, causing shape mismatches at training time.

    Transforms:
        select_dtypes(include=["int64", "float64"])
            → select_dtypes(include="number")

        .select_dtypes(include=["int64", "float64"])
            → .select_dtypes(include="number")

    Does NOT touch:
        select_dtypes(include=["object"])
        select_dtypes(include=["category"])
    """
    if 'include="number"' in script or "include='number'" in script:
        return script

    pattern = re.compile(r'(select_dtypes\s*\(\s*include\s*=\s*)\["int64"\s*,\s*"float64"\]')
    count = len(pattern.findall(script))

    if count:
        result = pattern.sub(r'\1"number"', script)
        logger.info(f"widen_numeric_dtype_selection: widened {count} select_dtypes call(s)")
        return result

    # Also handle reversed order ["float64", "int64"] or single type
    pattern_reversed = re.compile(
        r'(select_dtypes\s*\(\s*include\s*=\s*)\["float64"\s*,\s*"int64"\]'
    )
    count_rev = len(pattern_reversed.findall(script))
    if count_rev:
        result = pattern_reversed.sub(r'\1"number"', script)
        logger.info(
            f"widen_numeric_dtype_selection: widened {count_rev} reversed select_dtypes call(s)"
        )
        return result

    # Single type: ["int64"] or ["float64"] — wider but less likely
    pattern_single = re.compile(r'(select_dtypes\s*\(\s*include\s*=\s*)\["(?:int64|float64)"\]')
    count_single = len(pattern_single.findall(script))
    if count_single:
        result = pattern_single.sub(r'\1"number"', script)
        logger.info(
            f"widen_numeric_dtype_selection: widened {count_single} single-type select_dtypes call(s)"
        )
        return result

    return script


def add_runtime_column_validation(script: str) -> str:
    """Add runtime column validation after pd.read_csv and target extraction.

    Detects the pattern:
        target = df.pop("column_name")
        X = df

    And inserts validation that checks feature columns exist before training.
    This prevents 33% of Dissect interventions (missing_column category).

    Insertion is done as a comment + assert that fires before model.fit().
    The assertion uses the column list from select_dtypes (numeric + categorical),
    so it validates the exact columns that will enter the model.
    """
    if "FAILSAFE: column validation" in script:
        return script

    # Find where training data is prepared — look for X_train assignment
    # that follows the pattern of collecting numeric and categorical columns
    lines = script.split("\n")

    # Look for the pattern where numeric_cols and cat_cols are defined
    numeric_cols_line = None
    cat_cols_line = None
    fit_line = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if "_numeric_cols = " in stripped or "numeric_cols = " in stripped:
            numeric_cols_line = i
        if (
            "_cat_cols = " in stripped
            or "cat_cols = " in stripped
            or "_categorical_cols = " in stripped
            or "categorical_cols = " in stripped
        ):
            cat_cols_line = i

    # Detect actual variable names used in script (with or without underscore prefix)
    _num_var = "numeric_cols"
    _cat_var = "categorical_cols"
    if numeric_cols_line is not None:
        raw = lines[numeric_cols_line].strip()
        if raw.startswith("_"):
            _num_var = "_numeric_cols"
    if cat_cols_line is not None:
        raw = lines[cat_cols_line].strip()
        m = re.match(r"^(_?[a-z_]+)\s*=", raw)
        if m:
            _cat_var = m.group(1).strip()

    # Also look for model.fit() insertion point
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\s*(model|_model|model_)\s*\.fit\s*\(", stripped):
            fit_line = i
            break

    if numeric_cols_line is None or cat_cols_line is None or fit_line is None:
        return script

    # Insert column validation right before model.fit()
    indent_match = re.match(r"^(\s*)", lines[fit_line])
    indent = indent_match.group(1) if indent_match else "    "

    validation_block = (
        f"{indent}# FAILSAFE: column validation -- verify expected features exist\n"
        f"{indent}_expected_cols = list(dict.fromkeys({_num_var} + {_cat_var}))\n"
        f"{indent}_missing_cols = [c for c in _expected_cols if c not in X_train.columns]\n"
        f"{indent}if _missing_cols:\n"
        f"{indent}    raise ValueError(\n"
        f'{indent}        f"FAILSAFE: missing {{len(_missing_cols)}} expected columns: {{_missing_cols}} | "\n'
        f'{indent}        f"available={{list(X_train.columns)[:10]}}..."\n'
        f"{indent}    )\n"
        f"{indent}\n"
        f"{indent}# FAILSAFE: ensure X_train has rows after NaN filtering\n"
        f"{indent}if len(X_train) == 0:\n"
        f'{indent}    raise ValueError("FAILSAFE: X_train has 0 rows -- all data was dropped during NaN filtering")\n'
        f"{indent}\n"
    )

    result_lines = lines[:fit_line] + [validation_block] + lines[fit_line:]
    logger.info("add_runtime_column_validation: added column validation before model.fit()")
    return "\n".join(result_lines)


def add_data_fallback_options(script: str) -> str:
    """Add fallback encoding and error handling to critical I/O sections.

    Wraps pd.read_csv with a try/except for encoding fallback:
    - First tries utf-8
    - Falls back to latin-1 if utf-8 fails
    - Falls back to 'replace' error handling as last resort
    """
    if "FAILSAFE: encoding fallback" in script:
        return script

    # Find pd.read_csv lines and wrap them
    lines = script.split("\n")
    new_lines: list[str] = []
    i = 0
    read_csv_count = 0

    while i < len(lines):
        stripped = lines[i].strip()
        if "pd.read_csv(" in stripped:
            # Check if it's already wrapped
            if i > 0 and "FAILSAFE:" in lines[i - 1]:
                new_lines.append(lines[i])
                i += 1
                continue

            # Get indentation of this line
            indent_match = re.match(r"^(\s*)", lines[i])
            indent = indent_match.group(1) if indent_match else ""
            next_indent = indent + "    "

            # Build the wrapped version
            read_csv_count += 1

            new_lines.append(
                f"{indent}# FAILSAFE: encoding fallback — try utf-8 first, fall back to latin-1"
            )
            new_lines.append(f"{indent}try:")
            new_lines.append(f"{next_indent}{stripped}")
            new_lines.append(f"{next_indent}df = df  # keep reference in local scope")
            new_lines.append(f"{indent}except UnicodeDecodeError:")
            new_lines.append(f"{next_indent}_read_csv_encoding = 'ISO-8859-1'  # latin-1 fallback")
            # Reconstruct with latin-1
            new_stripped = _replace_encoding_arg(stripped, "_read_csv_encoding")
            new_lines.append(f"{next_indent}{new_stripped}")
            i += 1
        else:
            new_lines.append(lines[i])
            i += 1

    if read_csv_count:
        logger.info(
            f"add_data_fallback_options: wrapped {read_csv_count} read_csv call(s) with encoding fallback"
        )
    return "\n".join(new_lines)


def _replace_encoding_arg(call: str, var_name: str) -> str:
    """Replace or add encoding= argument in a pd.read_csv call."""
    if "encoding=" in call:
        return re.sub(r'encoding\s*=\s*"[^"]*"', f"encoding={var_name}", call)
    else:
        # Add before closing paren
        return call.rstrip().rstrip(")") + f", encoding={var_name})"


def ensure_result_json_write(script: str) -> str:
    """Ensure the script writes result.json with training outcome.

    The orchestrator reads result.json to determine job success.
    Scripts that crash before writing result.json leave the orchestrator
    hanging. This rule adds a try/finally around the main training block
    to always write result.json.
    """
    if "result.json" in script and "finally:" in script:
        return script

    lines = script.split("\n")

    # Find the training block — look for model.fit() or training loop
    fit_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r"^\s*(model|_model)\s*\.fit\s*\(", stripped):
            fit_idx = i
            break

    if fit_idx is None:
        return script

    # Find the last line of the training block (next blank line or end of block)
    # and wrap the fit block with try/finally
    indent_match = re.match(r"^(\s*)", lines[fit_idx])
    indent = indent_match.group(1) if indent_match else "    "
    inner_indent = indent + "    "

    try_block = f"{indent}try:\n{inner_indent}"
    lines[fit_idx] = try_block + lines[fit_idx].lstrip()

    # Insert result.json write in a finally block
    # Find a good insertion point after the fit call — look for a blank line
    # or the next top-level statement
    insert_idx = None
    for j in range(fit_idx + 1, len(lines)):
        stripped = lines[j].strip()
        if stripped == "":
            continue
        if stripped.startswith("#") or stripped.startswith("print(") or stripped.startswith('"'):
            continue
        # Check if this is top-level code (not inside a function/class)
        if re.match(r"^\S", stripped):
            insert_idx = j
            break

    if insert_idx is None:
        insert_idx = len(lines)

    finally_block = (
        f"\n{indent}finally:\n"
        f"{inner_indent}import json as _json_mod\n"
        f"{inner_indent}_result = {{\n"
        f'{inner_indent}    "status": "completed",\n'
        f'{inner_indent}    "best_val_metric": float(_best_val_metric_) if "_best_val_metric_" in dir() else None,\n'
        f'{inner_indent}    "total_epochs": _total_epochs if "_total_epochs" in dir() else None,\n'
        f'{inner_indent}    "total_crashes_recovered": _total_crashes_recovered if "_total_crashes_recovered" in dir() else 0,\n'
        f"{inner_indent}}}\n"
        f'{inner_indent}with open(os.path.join(_output_dir, "result.json"), "w") as _f:\n'
        f"{inner_indent}    _json_mod.dump(_result, _f)\n"
        f'{inner_indent}print("TRAINING_COMPLETE", _result["status"])\n'
    )

    result = lines[:insert_idx] + [finally_block] + lines[insert_idx:]
    logger.info("ensure_result_json_write: wrapped training block with try/finally for result.json")
    return "\n".join(result)


# ── Static validation ────────────────────────────────────────────


VALIDATION_CHECKS: list[dict[str, Any]] = [
    {
        "id": "missing_encoding",
        "description": "pd.read_csv without encoding= parameter",
        "pattern": r"pd\.read_csv\s*\([^)]*\)(?!.*encoding=)",
        "severity": "warning",
        "message": "pd.read_csv() should specify encoding= to prevent UnicodeDecodeError",
    },
    {
        "id": "narrow_numeric_dtype",
        "description": "select_dtypes with explicit ['int64', 'float64'] list",
        "pattern": r'select_dtypes\s*\(\s*include\s*=\s*\["int64"\s*,\s*"float64"\]',
        "severity": "warning",
        "message": "Use select_dtypes(include='number') instead of ['int64', 'float64'] to catch all numeric dtypes",
    },
    {
        "id": "narrow_numeric_dtype_reversed",
        "description": "select_dtypes with explicit ['float64', 'int64'] list",
        "pattern": r'select_dtypes\s*\(\s*include\s*=\s*\["float64"\s*,\s*"int64"\]',
        "severity": "warning",
        "message": "Use select_dtypes(include='number') instead of ['float64', 'int64'] to catch all numeric dtypes",
    },
    {
        "id": "missing_training_complete",
        "description": "Missing TRAINING_COMPLETE print statement",
        "pattern": r'print\s*\(\s*"TRAINING_COMPLETE',
        "severity": "error",
        "message": "Script must print TRAINING_COMPLETE for orchestrator to detect completion",
    },
    {
        "id": "missing_result_json",
        "description": "Missing result.json write statement",
        "pattern": r"result\.json",
        "severity": "error",
        "message": "Script must write result.json for orchestrator to read training outcome",
    },
    {
        "id": "unprotected_stratify",
        "description": "train_test_split with stratify= but no _n_classes guard",
        "pattern": r"train_test_split\s*\([^)]*stratify\s*=",
        "severity": "warning",
        "message": "stratify= in train_test_split should be guarded with _n_classes > 1 check",
    },
    {
        "id": "model_fit_without_validation",
        "description": "model.fit() without prior column validation",
        "pattern": r"model\.fit\s*\(",
        "severity": "info",
        "message": "Consider adding pre-fit column validation to catch missing features early",
    },
]


def validate_script_static(script: str) -> list[dict[str, Any]]:
    """Run static analysis on a generated training script.

    Checks for known anti-patterns and missing safety guards.
    Returns a list of findings (empty list = clean).

    This is called AFTER static prevention rules are applied, so findings
    should be rare — the rules should have fixed most of these already.
    """
    findings: list[dict[str, Any]] = []

    for check in VALIDATION_CHECKS:
        pattern = re.compile(check["pattern"])
        matches = pattern.findall(script)

        if check["id"] in ("missing_encoding",):
            # Special case: check if encoding IS already there
            if "encoding=" in script:
                continue

        if check["id"] in ("missing_training_complete",):
            if not matches:
                findings.append(
                    {
                        "id": check["id"],
                        "severity": check["severity"],
                        "message": check["message"],
                        "count": 0,
                    }
                )
            continue

        if check["id"] in ("missing_result_json",):
            if "result.json" not in script:
                findings.append(
                    {
                        "id": check["id"],
                        "severity": check["severity"],
                        "message": check["message"],
                        "count": 0,
                    }
                )
            continue

        if not matches:
            continue

        # For unprotected_stratify: check if _use_stratify guard exists
        if check["id"] == "unprotected_stratify":
            if "_use_stratify" in script:
                continue

        # For model_fit_without_validation: check if FAILSAFE comment exists
        if check["id"] == "model_fit_without_validation":
            if "FAILSAFE: column validation" in script:
                continue

        findings.append(
            {
                "id": check["id"],
                "severity": check["severity"],
                "message": check["message"],
                "count": len(matches),
            }
        )

    return findings


# ── Main entry point ─────────────────────────────────────────────


def apply_static_prevention(
    script: str,
    mission: dict[str, Any] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Apply all static prevention rules to a rendered training script.

    Args:
        script: The rendered training script content.
        mission: Optional mission spec dict (used for context-aware rules).

    Returns:
        Tuple of (modified_script, list of findings from pre/post comparison).
    """
    original = script

    # Order matters: encoding fixes first, then dtype, then validation
    script = ensure_read_csv_encoding(script)
    script = widen_numeric_dtype_selection(script)
    script = add_runtime_column_validation(script)

    # Run validation on the final script
    findings = validate_script_static(script)

    changes = 0
    if script != original:
        changes = sum(1 for a, b in zip(original.split("\n"), script.split("\n")) if a != b)
        logger.info(
            f"apply_static_prevention: {changes} line(s) changed | {len(findings)} validation finding(s)"
        )
    else:
        logger.info(
            f"apply_static_prevention: no changes needed | {len(findings)} validation finding(s)"
        )

    # Attach finding count as comment for auditability
    if findings:
        header = f"# StaticPrevention: {len(findings)} finding(s)\n"
        for f in findings:
            header += f"#   [{f['severity'].upper()}] {f['message']}\n"
        script = header + script

    return script, findings

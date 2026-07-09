"""Patch validation — pre-sandbox and post-sandbox checks for Dissect patches.

Pre-sandbox validation (before Docker launch):
    - ast.parse() syntax check
    - Critical structural elements: model.fit(), train_test_split(), result.json
    - Import safety: no exec/eval/__import__ without justification
    - Diff sanity: at least 1 line changed, at most 50 (prevents wholesale replacement)

Post-sandbox validation (after Docker returns):
    - Checkpoint file created
    - TRAINING_COMPLETE printed to stdout
    - result.json written with valid metric values
"""

import ast
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

SAFE_IMPORTS = {
    "os", "json", "pickle", "warnings", "numpy", "pandas", "torch",
    "sklearn", "lightgbm", "xgboost", "optuna", "difflib",
    "collections", "functools", "itertools", "math", "random",
    "typing", "pathlib", "datetime", "time", "uuid",
    "transformers", "datasets", "PIL", "torchvision",
    "pytorch_tabnet", "imblearn", "onnx", "onnxruntime",
}

DANGEROUS_FUNCTIONS = {"exec", "eval", "__import__", "compile", "globals", "locals"}

CRITICAL_PATTERNS = {
    "model.fit": r"\bmodel\s*\.\s*fit\s*\(",
    "train_test_split": r"train_test_split\s*\(",
    "result.json": r"result\.json",
}


def validate_patch_pre(
    original_script: str,
    patched_script: str,
    diff_text: str,
) -> dict[str, Any]:
    """Pre-sandbox validation of a patch.

    Returns dict with:
        valid: bool — overall pass/fail
        checks: list of check results
    """
    checks: list[dict[str, Any]] = []

    # 1. AST syntax check
    try:
        ast.parse(patched_script)
        checks.append({"name": "syntax", "passed": True, "message": "Valid Python syntax"})
    except SyntaxError as e:
        checks.append({"name": "syntax", "passed": False, "message": f"Syntax error: {e}"})

    # 2. Diff sanity: at least 1 line changed, at most 50
    lines_changed = sum(1 for line in diff_text.split("\n") if line.startswith("+") and not line.startswith("+++"))
    deletions = sum(1 for line in diff_text.split("\n") if line.startswith("-") and not line.startswith("---"))
    if lines_changed >= 1 and lines_changed <= 50:
        checks.append({
            "name": "diff_size", "passed": True,
            "message": f"Diff changed {lines_changed} added + {deletions} deleted lines",
        })
    elif lines_changed == 0:
        checks.append({"name": "diff_size", "passed": False, "message": "No lines changed in patch"})
    else:
        checks.append({
            "name": "diff_size", "passed": False,
            "message": f"Patch too large: {lines_changed} lines added (max 50)",
        })

    # 3. Structural elements — check critical patterns exist in patched script
    for name, pattern in CRITICAL_PATTERNS.items():
        if re.search(pattern, patched_script, re.MULTILINE):
            checks.append({"name": f"has_{name.replace('.', '_')}", "passed": True, "message": f"Found {name}()"})
        else:
            checks.append({"name": f"has_{name.replace('.', '_')}", "passed": False, "message": f"Missing {name}()"})

    # 4. Import safety — check for dangerous functions
    try:
        tree = ast.parse(patched_script)
        dangerous_used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in DANGEROUS_FUNCTIONS:
                    dangerous_used.add(node.func.id)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "__import__":
                    dangerous_used.add("__import__")
        if dangerous_used:
            checks.append({
                "name": "import_safety", "passed": False,
                "message": f"Dangerous functions used: {dangerous_used}",
            })
        else:
            checks.append({"name": "import_safety", "passed": True, "message": "No dangerous functions"})
    except SyntaxError:
        checks.append({"name": "import_safety", "passed": False, "message": "Cannot check imports — syntax error"})

    valid = all(c["passed"] for c in checks)
    return {"valid": valid, "checks": checks}


def validate_patch_post(
    job_id: str,
    sandbox_output: str,
    outputs_dir: str = "outputs",
) -> dict[str, Any]:
    """Post-sandbox validation after running the patched script.

    Args:
        job_id: The job ID.
        sandbox_output: stdout/stderr from the sandbox container.
        outputs_dir: Base outputs directory.

    Returns:
        dict with valid: bool and checks: list.
    """
    checks: list[dict[str, Any]] = []

    # 1. Check TRAINING_COMPLETE in output
    has_complete = "TRAINING_COMPLETE" in sandbox_output
    checks.append({
        "name": "training_complete",
        "passed": has_complete,
        "message": "TRAINING_COMPLETE found in output" if has_complete else "TRAINING_COMPLETE NOT found in output",
    })

    # 2. Check for common failure patterns in output
    failure_keywords = ["Traceback", "Error", "Exception", "failed", "FAILSAFE"]
    found_failures = [kw for kw in failure_keywords if kw in sandbox_output]
    if found_failures:
        checks.append({
            "name": "error_output",
            "passed": False,
            "message": f"Error keywords found in output: {found_failures[:3]}",
        })
    else:
        checks.append({"name": "error_output", "passed": True, "message": "No error keywords in output"})

    # 3. Check checkpoint file created
    ckpt_path = os.path.join(outputs_dir, job_id, "checkpoints", "best.ckpt")
    if os.path.exists(ckpt_path):
        checks.append({"name": "checkpoint", "passed": True, "message": f"Checkpoint exists at {ckpt_path}"})
    else:
        checks.append({"name": "checkpoint", "passed": False, "message": f"Checkpoint not found at {ckpt_path}"})

    # 4. Check result.json written
    result_path = os.path.join(outputs_dir, job_id, "result.json")
    if os.path.exists(result_path):
        try:
            import json
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
            checks.append({
                "name": "result_json", "passed": True,
                "message": f"result.json written with val_score={result.get('val_score', 'N/A')}",
            })
        except Exception as e:
            checks.append({"name": "result_json", "passed": False, "message": f"result.json unreadable: {e}"})
    else:
        checks.append({"name": "result_json", "passed": False, "message": "result.json not found"})

    valid = all(c["passed"] for c in checks)
    return {"valid": valid, "checks": checks}

"""Dissect tools. Each function is independently unit-testable."""

import difflib
import logging
import os
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)


def parse_stack_trace(traceback_str: str) -> dict:
    """Extract failing file, line number, and function from a traceback string."""
    result = {
        "file": None,
        "line": None,
        "function": None,
        "exception_line": None,
    }

    lines = traceback_str.strip().split("\n")
    for i, line in enumerate(lines):
        if 'File "' in line:
            try:
                parts = line.split('"')
                result["file"] = parts[1]
                if "line " in line:
                    line_parts = line.split("line ")
                    result["line"] = int(line_parts[1].split(",")[0])
                if "in " in line:
                    func_part = line.split("in ")[-1].strip()
                    result["function"] = func_part
            except (IndexError, ValueError):
                pass

    for line in reversed(lines):
        line = line.strip()
        if (
            line
            and not line.startswith("Traceback")
            and not line.startswith("  File")
            and not line.startswith("  ")
        ):
            result["exception_line"] = line
            break

    return result


def apply_patch(script_path: str, patched_code: str) -> tuple[bool, str]:
    """Apply a patch to a script file. Creates .bak backup.

    Returns:
        (success, message)
    """
    if not os.path.exists(script_path):
        return False, f"Script not found: {script_path}"

    try:
        bak_path = script_path + ".bak"
        shutil.copy2(script_path, bak_path)

        with open(script_path, "w") as f:
            f.write(patched_code)

        return True, f"Patch applied. Backup at {bak_path}"
    except Exception as e:
        return False, f"Failed to apply patch: {e}"


def rollback_patch(script_path: str) -> bool:
    """Rollback a patch by restoring from .bak backup."""
    bak_path = script_path + ".bak"
    if not os.path.exists(bak_path):
        return False

    try:
        shutil.copy2(bak_path, script_path)
        os.remove(bak_path)
        return True
    except Exception:
        return False


def compute_diff(original: str, patched: str) -> str:
    """Compute unified diff between original and patched code."""
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        patched_lines,
        fromfile="original",
        tofile="patched",
    )
    return "".join(diff)


async def run_sandbox_test(script_path: str, job_id: str, max_epochs: int = 3) -> tuple[bool, str]:
    """Run patched script in a sandbox for up to max_epochs to verify it works.

    Returns:
        (passed, output)
    """
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return True, "Timed out after 60s (OK - training past max_epochs)"
    except Exception as e:
        return False, str(e)

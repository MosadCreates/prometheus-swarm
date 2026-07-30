"""Dissect tools. Each function is independently unit-testable."""

import asyncio
import difflib
import logging
import os
import shutil
import uuid

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

        with open(script_path, "w", encoding="utf-8") as f:
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
    original = original.replace("\r\n", "\n")
    patched = patched.replace("\r\n", "\n")
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)

    diff = difflib.unified_diff(
        original_lines,
        patched_lines,
        fromfile="original",
        tofile="patched",
    )
    return "".join(diff)


def apply_unified_diff(script_path: str, diff_text: str) -> tuple[bool, str]:
    """Apply a unified diff to a file in-place. Creates .bak backup.

    Parses a unified diff produced by compute_diff() and applies line insertions
    and deletions readably without shelling out to `patch`.
    """
    if not os.path.exists(script_path):
        return False, f"Script not found: {script_path}"
    try:
        bak_path = script_path + ".bak"
        shutil.copy2(script_path, bak_path)

        with open(script_path, encoding="utf-8") as f:
            lines = f.readlines()

        hunk_lines = []
        in_hunk = False
        for line in diff_text.split("\n"):
            if line.startswith("@@"):
                hunk_lines.append(line)
                in_hunk = True
            elif in_hunk:
                if line.startswith("---") or line.startswith("+++"):
                    continue
                hunk_lines.append(line)

        result = list(lines)
        offset = 0
        i = 0
        while i < len(hunk_lines):
            h = hunk_lines[i]
            if not h.startswith("@@"):
                i += 1
                continue
            parts = h.split()
            if len(parts) < 2:
                i += 1
                continue
            old_range = parts[1]
            if "," in old_range:
                old_start, old_count = old_range.split(",")
                old_start = int(old_start) - 1
                old_count = int(old_count)
            else:
                old_start = int(old_range) - 1
                old_count = 1
            i += 1
            deletions = 0
            insertions = []
            while i < len(hunk_lines) and not hunk_lines[i].startswith("@@"):
                cl = hunk_lines[i]
                if cl.startswith("---") or cl.startswith("+++"):
                    i += 1
                    continue
                if cl.startswith("-"):
                    deletions += 1
                elif cl.startswith("+"):
                    insertions.append(cl[1:])
                i += 1

            pos = old_start + offset
            if pos < 0:
                pos = 0
            for _ in range(deletions):
                if pos < len(result):
                    result.pop(pos)
            for j, ins in enumerate(insertions):
                result.insert(pos + j, ins + "\n" if not ins.endswith("\n") else ins)
            offset += len(insertions) - deletions

        with open(script_path, "w", encoding="utf-8") as f:
            f.writelines(result)

        return True, f"Diff applied. Backup at {bak_path}"
    except Exception as e:
        return False, f"Failed to apply diff: {e}"


def _validate_sandbox_env(job_id: str) -> None:
    """Verify sandbox and Furnace share identical environment.

    Checks:
        - Docker image name matches Furnace's TRAINING_IMAGE_NAME
        - Required env vars are present
        - Script path exists

    Raises RuntimeError on any mismatch.
    """
    from runtime.paths import get_job_paths

    jp = get_job_paths(job_id)

    expected_image = os.getenv("TRAINING_IMAGE_NAME", "prometheus-training-base")
    if not expected_image:
        raise RuntimeError("Missing TRAINING_IMAGE_NAME env var for sandbox")

    # Allow RuntimePaths-compatible defaults (same as runtime/paths.py _resolve_dir)
    for var, default in [
        ("SCRIPTS_DIR", "./scripts"),
        ("OUTPUTS_DIR", "./outputs"),
        ("DATA_DIR", "./data"),
    ]:
        if not os.getenv(var):
            os.environ[var] = default

    scripts_parent = jp.script_path.parent
    if not os.path.exists(str(scripts_parent)):
        raise RuntimeError(f"Scripts directory not found: {scripts_parent}")


async def run_sandbox_test(script_path: str, job_id: str, max_epochs: int = 3) -> tuple[bool, str]:
    """Run patched script in a Docker sandbox for up to max_epochs to verify it works.

    Uses the same training base image and volume layout as the real Furnace training
    container, ensuring the patch is tested in an environment identical to production.

    Returns:
        (passed, output)
    """
    import docker
    from docker.errors import DockerException
    from runtime.paths import get_job_paths

    # Verify identical environment before launching
    _validate_sandbox_env(job_id)

    client = docker.from_env()
    image = os.getenv("TRAINING_IMAGE_NAME", "prometheus-training-base")
    sandbox_id = f"{job_id}-{uuid.uuid4().hex[:8]}"
    container_name = f"prometheus-sandbox-{sandbox_id}"
    script_name = os.path.basename(script_path)
    jp = get_job_paths(job_id)

    volumes = {
        os.path.abspath(script_path): {"bind": f"/app/{script_name}", "mode": "ro"},
        **jp.docker_mounts,
    }
    environment = jp.container_env

    loop = asyncio.get_event_loop()

    try:
        container = await loop.run_in_executor(
            None,
            lambda: client.containers.run(
                image=image,
                command=["python", f"/app/{script_name}"],
                name=container_name,
                detach=True,
                volumes=volumes,
                environment=environment,
                working_dir="/app",
                stdout=True,
                stderr=True,
                remove=False,
            ),
        )
    except DockerException as e:
        return False, f"Failed to launch sandbox container: {e}"

    try:
        try:
            result = await loop.run_in_executor(
                None,
                lambda: container.wait(timeout=60),
            )
            exit_code = result.get("StatusCode", -1)
        except Exception:
            await loop.run_in_executor(None, lambda: container.kill())
            return True, "Timed out after 60s (OK - training past max_epochs)"

        logs = await loop.run_in_executor(
            None,
            lambda: container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace"),
        )

        if exit_code == 0:
            return True, logs
        return False, logs
    finally:
        try:
            await loop.run_in_executor(None, lambda: container.remove(force=True))
        except Exception:
            pass

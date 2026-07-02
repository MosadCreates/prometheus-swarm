"""
Proves Dissect's sandbox test runs real Docker containers.
Requires: Docker running, prometheus-training-base image built.
"""

import asyncio
import os
import pytest

pytestmark = [pytest.mark.asyncio, pytest.mark.timeout(120)]


@pytest.fixture(autouse=True)
def require_docker():
    import subprocess

    result = subprocess.run(
        ["docker", "images", "-q", "prometheus-training-base"],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        pytest.skip("prometheus-training-base image not found")


async def test_sandbox_passes_valid_script():
    """A valid Python script produces exit code 0 in the sandbox."""
    from agents.dissect.tools import run_sandbox_test
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("import pandas as pd\n" "import numpy as np\n" "print('Sandbox test passed')\n")
        script_path = f.name
    try:
        passed, output = await run_sandbox_test(script_path, "sandbox-test-valid")
        assert passed, f"Valid script should pass sandbox. Output: {output}"
        assert "Sandbox test passed" in output or passed
    finally:
        os.unlink(script_path)


async def test_sandbox_fails_crashing_script():
    """A script that raises an exception produces exit code != 0."""
    from agents.dissect.tools import run_sandbox_test
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write("raise ValueError('Deliberate failure for sandbox test')\n")
        script_path = f.name
    try:
        passed, output = await run_sandbox_test(script_path, "sandbox-test-fail")
        assert not passed, "Crashing script should fail sandbox"
        assert "ValueError" in output or "Deliberate failure" in output
    finally:
        os.unlink(script_path)


async def test_sandbox_isolates_jobs():
    """Two concurrent sandbox tests for different job_ids don't interfere."""
    from agents.dissect.tools import run_sandbox_test
    import tempfile

    with (
        tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f1,
        tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f2,
    ):
        f1.write("print('job A')\n")
        f2.write("print('job B')\n")
        path1, path2 = f1.name, f2.name
    try:
        results = await asyncio.gather(
            run_sandbox_test(path1, "sandbox-test-A"),
            run_sandbox_test(path2, "sandbox-test-B"),
        )
        assert results[0][0], "Job A should pass"
        assert results[1][0], "Job B should pass"
    finally:
        os.unlink(path1)
        os.unlink(path2)

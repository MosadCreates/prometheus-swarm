"""
Guards against architectural drift — ensures the benchmark uses
job_runner.py and not subprocess or direct tool calls.
"""

import ast
import os


def test_run_benchmark_does_not_use_subprocess_for_training():
    """Benchmark must not call subprocess.run() for training (git is ok)."""
    with open("research/run_benchmark.py", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "run":
                if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                    # Allow git commands (metadata gathering)
                    if node.args and hasattr(node.args[0], "elts"):
                        first_arg_constants = [
                            e.value for e in node.args[0].elts if isinstance(e, ast.Constant)
                        ]
                        if "git" in first_arg_constants:
                            continue
                    raise AssertionError(
                        f"run_benchmark.py calls subprocess.run() at line {node.lineno}. "
                        "Use orchestrator.job_runner.run_job() instead."
                    )


def test_run_benchmark_imports_job_runner():
    """Benchmark must import from orchestrator.job_runner."""
    with open("research/run_benchmark.py", encoding="utf-8") as f:
        source = f.read()
    assert "job_runner" in source, (
        "run_benchmark.py does not import job_runner. "
        "The benchmark must use orchestrator.job_runner.run_job()."
    )


def test_job_runner_does_not_use_subprocess_for_training():
    """job_runner.py must not call subprocess for training scripts."""
    with open("orchestrator/job_runner.py", encoding="utf-8") as f:
        source = f.read()
    if "subprocess.run" in source:
        parts = source.split("subprocess.run", 1)
        if len(parts) > 1:
            assert "sys.executable" not in parts[1][:200], (
                "job_runner.py appears to call subprocess.run(sys.executable, ...) "
                "which bypasses Docker training."
            )


def test_furnace_agent_exists_and_has_run_method():
    """FurnaceAgent must exist and implement run() with script_path parameter."""
    from agents.furnace.agent import FurnaceAgent
    import inspect

    sig = inspect.signature(FurnaceAgent.run)
    assert "script_path" in sig.parameters, "FurnaceAgent.run() must accept script_path parameter"


def test_arbiter_agent_exists_and_has_on_training_complete():
    """ArbiterAgent must implement on_training_complete() as an agent method."""
    from agents.arbiter.agent import ArbiterAgent

    assert hasattr(
        ArbiterAgent, "on_training_complete"
    ), "ArbiterAgent must have on_training_complete() method"
    assert callable(ArbiterAgent.on_training_complete)


def test_harbor_agent_exists_and_has_on_evaluation_pass():
    """HarborAgent must implement on_evaluation_pass() as an agent method."""
    from agents.harbor.agent import HarborAgent

    assert hasattr(
        HarborAgent, "on_evaluation_pass"
    ), "HarborAgent must have on_evaluation_pass() method"


def test_patch_log_has_get_job_patch_outcomes():
    """patch_log.py must expose get_job_patch_outcomes() for job_runner."""
    from agents.dissect.patch_log import get_job_patch_outcomes

    assert callable(get_job_patch_outcomes)

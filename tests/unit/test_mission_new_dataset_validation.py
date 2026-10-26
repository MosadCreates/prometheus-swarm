"""Fail-fast dataset validation for ``mission new``.

Regression test: a mission submitted with a nonexistent dataset path used to
start the orchestrator/daemon, submit the job, and then die in ~0s inside
Scout (``Dataset not found``) with the reason buried in the daemon log and the
diagnostic report. ``mission new`` now rejects the submission up front.

Only the missing-dataset path is tested here — it returns before any daemon /
Redis work, so it is hermetic under CliRunner.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

from click.testing import CliRunner

from prometheus.cli.mission import mission
from prometheus.utils.exit_codes import ExitCode


def _invoke_new(runner: CliRunner, dataset: str):
    return runner.invoke(
        mission,
        [
            "new",
            "predict passenger survival",
            "--dataset",
            dataset,
            "--auto",
        ],
        # renderer_from_ctx reads these off the root ctx.obj (the real
        # prometheus/main.py:cli group populates them).
        obj={"format": "rich", "no_color": False},
        # Click 8.4 CliRunner computes exit_code only from SystemExit / caught
        # exceptions — a command's returned int is discarded under the default
        # standalone_mode=True. standalone_mode=False makes main() return the
        # callback value, so the ExitCode the guard returns survives into
        # Result.return_value (production converts it via the root cli group's
        # result_callback: ctx.exit(result.value) -> SystemExit(1)).
        standalone_mode=False,
    )


def test_mission_new_rejects_missing_dataset():
    runner = CliRunner()
    result = _invoke_new(runner, "definitely-not-a-real-dataset-xyz.csv")

    assert result.return_value == ExitCode.ERROR
    assert "Dataset not found" in result.output
    # It must fail before any orchestrator/daemon work — no submission happens.
    assert "Mission created" not in result.output
    assert "started daemon" not in result.output


def test_mission_new_accepts_existing_dataset(tmp_path, monkeypatch):
    """An existing file passes the pre-check and the mission is submitted.

    The post-guard machinery (orchestrator daemon readiness + Redis submit) is
    mocked so this stays hermetic; the point is that the guard does not
    false-positive on a real file.
    """

    runner = CliRunner()
    dataset = tmp_path / "data.csv"
    dataset.write_text("age,sex,survived\n1,m,1\n", encoding="utf-8")

    # mission new imports these inside the function body, so patching the
    # module attributes is enough. The guard runs before either is reached.
    monkeypatch.setattr(
        "prometheus.cli.daemon.wait_for_orchestrator_ready",
        _async_returning_true,
    )
    monkeypatch.setattr(
        "orchestrator.job_queue.submit_job",
        _async_returning_job_id,
    )

    result = _invoke_new(runner, str(dataset))

    assert result.return_value == ExitCode.SUCCESS
    # Guard bypassed for a real file — and submission actually happened.
    assert "Dataset not found" not in result.output
    assert "Mission created" in result.output


def _async_returning_true(*_args, **_kwargs):
    import asyncio

    return asyncio.sleep(0, result=True)


def _async_returning_job_id(*_args, **_kwargs):
    import asyncio
    import uuid

    return asyncio.sleep(0, result=str(uuid.uuid4()))

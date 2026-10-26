"""Subprocess isolation for installed skills — Cross-cutting contract #2.

Wall-clock timeout **and** a parent-side RSS monitor (psutil) both hard-kill
the worker. Windows has no ``resource.setrlimit``, so the psutil monitor is
the cross-platform memory cap. A CPU-bound ``while True`` hang is killed by
the timeout (the thing ``asyncio.wait_for`` alone cannot stop); a runaway
allocator is killed by the RSS monitor before it OOMs the host. Either way the
parent returns ``SkillResult(ok=False, reason=...)`` — never raises.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

from agents.skills.context import SkillContext, SkillResult
from agents.skills.loader import repo_root
from agents.skills.manifest import DEFAULT_MAX_MEMORY_MB, DEFAULT_MAX_RUNTIME_S, SkillManifest

_REPO_ROOT = str(repo_root())
_POLL_INTERVAL_S = 0.1


def _kill_tree(pid: int) -> None:
    """Kill the worker's whole process tree (descendants first, then root).

    On Windows the venv ``python.exe`` is a redirector stub: ``asyncio`` reports
    the stub's PID while the real interpreter — the process actually running the
    skill — is its child. Killing only the reported PID would orphan the runaway
    interpreter: its stdout pipe stays open, so ``communicate()`` never sees EOF
    and the kill silently fails to contain it. Tree-kill fixes both the orphan
    and the never-closing pipe.
    """
    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return
    for child in root.children(recursive=True):
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        root.kill()
    except psutil.Error:
        pass


def _tree_rss_bytes(pid: int) -> int:
    """Total RSS across the process and all descendants (see ``_kill_tree``).

    Summing the tree matters on Windows for the same redirector-stub reason:
    the reported PID stays ~4MB forever, so monitoring only it would never see
    a runaway worker cross the cap.
    """
    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return 0
    total = 0
    try:
        total += root.memory_info().rss
    except psutil.Error:
        pass
    for child in root.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            pass
    return total


async def _monitor_rss(
    proc: asyncio.subprocess.Process, memory_limit: int, state: dict[str, bool]
) -> None:
    """Kill the worker's tree if its total RSS exceeds ``memory_limit`` bytes."""
    while True:
        await asyncio.sleep(_POLL_INTERVAL_S)
        if proc.poll() is not None:
            return
        try:
            if _tree_rss_bytes(proc.pid) > memory_limit:
                state["memory_killed"] = True
                _kill_tree(proc.pid)
                return
        except psutil.Error:
            return


def _spawn(args: list[str], cwd: str, env: dict[str, str]) -> subprocess.Popen:
    """Spawn the worker subprocess (runs inside an executor thread).

    asyncio's ``create_subprocess_exec`` needs a Proactor event loop; the
    orchestrator and mission commands select ``WindowsSelectorEventLoopPolicy``
    on Windows, so under that policy the asyncio transport raises
    ``NotImplementedError``. Popen through a thread is loop-agnostic and keeps
    the spawn working under *any* policy — a subprocess capability must not
    depend on the caller's loop type.
    """
    return subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def run_skill_subprocess(manifest: SkillManifest, ctx: SkillContext) -> SkillResult:
    """Run ``manifest``'s skill in a subprocess worker and return its result.

    Never raises: every failure mode (spawn error, timeout, memory kill, bad
    stdout) collapses to ``SkillResult(ok=False, reason=...)``.
    """
    work_dir = tempfile.mkdtemp(prefix=f"skill-{manifest.name}-")
    ctx = ctx.model_copy(update={"work_dir": work_dir})
    ctx_file = os.path.join(work_dir, "ctx.json")
    with open(ctx_file, "w", encoding="utf-8") as fh:
        fh.write(ctx.model_dump_json())

    timeout = manifest.max_runtime_s or DEFAULT_MAX_RUNTIME_S
    memory_limit = (manifest.max_memory_mb or DEFAULT_MAX_MEMORY_MB) * 1024 * 1024

    started = time.perf_counter()
    loop = asyncio.get_running_loop()
    try:
        proc = await loop.run_in_executor(
            None,
            _spawn,
            [sys.executable, "-m", "agents.skills.worker", manifest.path, ctx_file],
            _REPO_ROOT,
            os.environ.copy(),
        )
    except Exception as e:
        return SkillResult(
            skill=manifest.name,
            ok=False,
            reason=f"failed to spawn worker: {e}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    state: dict[str, bool] = {"memory_killed": False}
    monitor = asyncio.create_task(_monitor_rss(proc, memory_limit, state))
    try:
        stdout, _stderr = await asyncio.wait_for(
            asyncio.to_thread(proc.communicate), timeout=timeout
        )
    except asyncio.TimeoutError:
        _kill_tree(proc.pid)
        await asyncio.to_thread(proc.wait)
        monitor.cancel()
        return SkillResult(
            skill=manifest.name,
            ok=False,
            reason=f"timed out after {timeout}s",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    finally:
        monitor.cancel()

    if state["memory_killed"]:
        return SkillResult(
            skill=manifest.name,
            ok=False,
            reason=f"memory limit exceeded ({manifest.max_memory_mb or DEFAULT_MAX_MEMORY_MB}MB)",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    if proc.returncode != 0:
        return SkillResult(
            skill=manifest.name,
            ok=False,
            reason=f"worker exited with code {proc.returncode}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    try:
        payload = stdout.decode("utf-8", errors="replace").strip()
        result = SkillResult.model_validate_json(payload.splitlines()[-1])
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result
    except Exception:
        return SkillResult(
            skill=manifest.name,
            ok=False,
            reason="worker produced no valid SkillResult on stdout",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def build_work_dir(manifest_name: str) -> str:
    """Create a per-skill work_dir for in-process runs (heavy outputs land here)."""
    return tempfile.mkdtemp(prefix=f"skill-{manifest_name}-")

from __future__ import annotations

import asyncio
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode

DAEMON_DIR = Path.home() / ".prometheus"
PID_FILE = DAEMON_DIR / "daemon.pid"
LOG_FILE = DAEMON_DIR / "daemon.log"
HEARTBEAT_KEY = "orch:heartbeat"


def _ensure_dir() -> None:
    DAEMON_DIR.mkdir(parents=True, exist_ok=True)


def _read_pid() -> int | None:
    if PID_FILE.exists():
        try:
            return int(PID_FILE.read_text().strip())
        except (ValueError, OSError):
            return None
    return None


def _write_pid(pid: int) -> None:
    _ensure_dir()
    PID_FILE.write_text(str(pid))


def _remove_pid() -> None:
    if PID_FILE.exists():
        PID_FILE.unlink()


def _is_orchestrator_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x0400, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError, SystemError):
        return False


async def _check_redis_heartbeat() -> bool:
    try:
        from memory.redis_client import RedisClient

        client = RedisClient()
        await client.connect()
        result = await client.get_str(HEARTBEAT_KEY)
        await client.close()
        return result is not None
    except Exception:
        return False


def _check_redis_heartbeat_sync() -> bool:
    try:
        return asyncio.run(_check_redis_heartbeat())
    except Exception:
        return False


def _resolve_python() -> Path:
    """Return the Python executable to use for the daemon subprocess.

    On Windows, prefers pythonw.exe (window-less) to avoid any console window.
    Falls back to python.exe, then PATH.
    """
    if sys.platform == "win32":
        candidates = [
            Path.cwd() / ".venv" / "Scripts" / "pythonw.exe",
            Path(sys.executable).with_name("pythonw.exe"),
            Path.cwd() / ".venv" / "Scripts" / "python.exe",
            Path(sys.executable),
        ]
    else:
        candidates = [
            Path.cwd() / ".venv" / "bin" / "python",
            Path(sys.executable),
        ]
    for p in candidates:
        if p.is_file():
            return p
    return Path(sys.executable)


@click.group(
    name="daemon",
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def daemon_cmd() -> None:
    """Manage the orchestrator background daemon."""


@daemon_cmd.command(name="start")
@click.option("--log-file", default=str(LOG_FILE), help="Path to log file")
@click.pass_context
def daemon_start(ctx: click.Context, log_file: str) -> ExitCode:
    """Start the orchestrator as a background daemon process."""
    renderer = renderer_from_ctx(ctx)

    pid = _read_pid()
    if pid and _is_orchestrator_alive(pid):
        already_slug = f" (PID {pid})"
        renderer.print(f"  Orchestrator is already running{already_slug}.")
        renderer.print("  Use:  prometheus daemon stop")
        return ExitCode.SUCCESS

    _ensure_dir()
    log_path = Path(log_file)

    orchestrator_module = "orchestrator.runtime"
    python = _resolve_python()

    try:
        with open(log_path, "a") as log_fh:
            proc = subprocess.Popen(
                [str(python), "-m", orchestrator_module],
                stdout=log_fh,
                stderr=log_fh,
                stdin=subprocess.DEVNULL,
                creationflags=(
                    (subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)
                    if sys.platform == "win32"
                    else 0
                ),
                start_new_session=True,
            )
    except FileNotFoundError:
        renderer.error(f"Python executable not found: {python}")
        return ExitCode.ERROR
    except Exception as e:
        renderer.error(f"Failed to start daemon: {e}")
        return ExitCode.ERROR

    _write_pid(proc.pid)
    renderer.print(f"  Orchestrator daemon started (PID {proc.pid}).")
    renderer.print(f"  Logs: {log_path}")
    renderer.print("  Use:  prometheus daemon status")
    renderer.print("        prometheus daemon stop")
    return ExitCode.SUCCESS


@daemon_cmd.command(name="stop")
@click.pass_context
def daemon_stop(ctx: click.Context) -> ExitCode:
    """Stop the background orchestrator daemon."""
    renderer = renderer_from_ctx(ctx)

    pid = _read_pid()
    if not pid:
        renderer.print("  No orchestrator daemon PID file found.")
        renderer.print(
            "  If the orchestrator is running, stop it manually (Ctrl+C in its terminal)."
        )
        return ExitCode.SUCCESS

    if not _is_orchestrator_alive(pid):
        renderer.print(f"  Orchestrator daemon (PID {pid}) is not running (stale PID file).")
        _remove_pid()
        return ExitCode.SUCCESS

    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)

        for _ in range(10):
            time.sleep(0.5)
            if not _is_orchestrator_alive(pid):
                break

        if _is_orchestrator_alive(pid):
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)

    except Exception as e:
        renderer.error(f"Failed to stop daemon: {e}")
        return ExitCode.ERROR

    _remove_pid()
    renderer.print(f"  Orchestrator daemon (PID {pid}) stopped.")
    return ExitCode.SUCCESS


@daemon_cmd.command(name="status")
@click.option("--redis/--no-redis", "check_redis", default=True, help="Check Redis heartbeat")
@click.pass_context
def daemon_status(ctx: click.Context, check_redis: bool) -> ExitCode:
    """Check if the orchestrator daemon is running and responding."""
    renderer = renderer_from_ctx(ctx)

    pid = _read_pid()
    alive = False
    if pid:
        alive = _is_orchestrator_alive(pid)

    redis_alive = False
    if check_redis:
        redis_alive = _check_redis_heartbeat_sync()

    if alive:
        renderer.print(f"  PID:     {pid} (running)")
    else:
        renderer.print("  PID:     none (not running)")

    if check_redis:
        if redis_alive:
            renderer.print("  Redis:   heartbeat detected")
        else:
            renderer.print("  Redis:   no heartbeat")

    if alive and redis_alive:
        renderer.print("  Status:  healthy")
        return ExitCode.SUCCESS
    elif alive:
        renderer.print("  Status:  starting (no Redis heartbeat yet)")
        return ExitCode.ERROR
    else:
        renderer.print("  Status:  stopped")
        return ExitCode.ERROR

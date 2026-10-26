from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
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


# The orchestrator writes orch:heartbeat every 5s once initialize() completes.
HEARTBEAT_MAX_AGE = 15  # seconds — older means the orchestrator is down/zombie


# The orchestrator binds its Prometheus metrics server on 9090 only after
# initialize() succeeds — so "port 9090 bound" distinguishes a live orchestrator
# from a ghost heartbeat left behind by one that just crashed.
METRICS_PORT = 9090


def _metrics_port_bound() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", METRICS_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _heartbeat_is_fresh(value: str | None, max_age: int = HEARTBEAT_MAX_AGE) -> bool:
    """True if the heartbeat value is present and newer than ``max_age`` seconds.

    A stale heartbeat (e.g. left behind by a dead orchestrator) must NOT count
    as "orchestrator running" — that is what previously caused missions to be
    submitted to a dead orchestrator and hang at "waiting for Scout to begin".
    """
    if not value:
        return False
    try:
        ts = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() < max_age


async def _check_redis_heartbeat() -> bool:
    try:
        from memory.redis_client import RedisClient

        client = RedisClient()
        await client.connect()
        result = await client.get_str(HEARTBEAT_KEY)
        await client.close()
        return _heartbeat_is_fresh(result)
    except Exception:
        return False


def _check_redis_heartbeat_sync() -> bool:
    try:
        return asyncio.run(_check_redis_heartbeat())
    except Exception:
        return False


async def wait_for_orchestrator_ready(timeout: float = 60.0, pid: int | None = None) -> bool:
    """Poll the Redis heartbeat until the orchestrator is fresh or ``timeout``.

    The orchestrator only writes its first heartbeat after ``initialize()``
    finishes (which includes ChromaDB tool registration — ~30-40s on a cold
    host), so a freshly spawned daemon takes a while before it becomes ready.
    If ``pid`` is given and that process dies before readiness, return False
    immediately so the caller can fall back without waiting out the timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await _check_redis_heartbeat():
            return True
        if pid is not None and not _is_orchestrator_alive(pid):
            return False
        await asyncio.sleep(1.0)
    return False


def tail_daemon_log(n: int = 10) -> str:
    """Return the last ``n`` lines of the daemon log, indented for printing."""
    if not LOG_FILE.exists():
        return f"  (no daemon log found at {LOG_FILE})"
    try:
        lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(f"  {line}" for line in lines[-n:])
    except OSError as e:
        return f"  (could not read daemon log: {e})"


def daemon_pid() -> int | None:
    """PID of the tracked orchestrator daemon, if any."""
    return _read_pid()


def is_daemon_alive(pid: int | None) -> bool:
    """True if ``pid`` is present and refers to a live process."""
    return bool(pid) and _is_orchestrator_alive(pid)


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


def start_orchestrator_daemon(log_file: str | None = None) -> tuple[bool, str]:
    """Start the orchestrator as a background daemon process.

    Reusable by both the ``daemon start`` command and ``mission new`` (which
    auto-starts the daemon). Returns ``(ok, message)``:

    - ``(True, "already running (PID n)")`` if a live daemon exists — never
      spawns a second one (two orchestrators would fight over the metrics port).
    - ``(True, "started (PID n)")`` on a fresh spawn.
    - ``(False, reason)`` if the spawn failed.
    """
    _ensure_dir()
    log_path = Path(log_file) if log_file else LOG_FILE

    pid = _read_pid()
    if pid and _is_orchestrator_alive(pid):
        return True, f"already running (PID {pid})"

    # Trust a live heartbeat over the PID file: an orchestrator started outside
    # this mechanism (e.g. a different venv) won't be in the PID file, and two
    # orchestrators would fight over the metrics port and the consumer groups.
    # Require the metrics port to be bound too — a crashed daemon leaves a fresh
    # heartbeat for up to ~15s, and refusing to spawn over that ghost would
    # leave missions submitted to a dead orchestrator.
    if _check_redis_heartbeat_sync() and _metrics_port_bound():
        return True, "already running (heartbeat detected)"

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
        return False, f"Python executable not found: {python}"
    except Exception as e:
        return False, f"Failed to start daemon: {e}"

    _write_pid(proc.pid)
    return True, f"started (PID {proc.pid})"


@daemon_cmd.command(name="start")
@click.option("--log-file", default=str(LOG_FILE), help="Path to log file")
@click.pass_context
def daemon_start(ctx: click.Context, log_file: str) -> ExitCode:
    """Start the orchestrator as a background daemon process."""
    renderer = renderer_from_ctx(ctx)

    ok, msg = start_orchestrator_daemon(log_file=log_file)
    if not ok:
        renderer.error(msg)
        return ExitCode.ERROR

    renderer.print(f"  Orchestrator daemon {msg}.")
    if msg.startswith("already running"):
        renderer.print("  Use:  prometheus daemon stop")
        return ExitCode.SUCCESS
    renderer.print(f"  Logs: {log_file}")
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
            # /T kills the whole process tree. The tracked PID is the venv
            # pythonw shim, whose *child* is the real interpreter running the
            # orchestrator (uv venvs relay to the base interpreter). Killing
            # only the shim would orphan the real orchestrator, which then
            # holds the metrics port and reappears as a "duplicate" next start.
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                timeout=15,
            )
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
        renderer.print("  Status:  starting (no recent Redis heartbeat)")
        return ExitCode.ERROR
    elif redis_alive:
        renderer.print("  Status:  running (heartbeat) — PID untracked")
        renderer.print("           find it with: Get-Process pythonw | sort StartTime")
        renderer.print("           stop it manually, or run: prometheus daemon stop")
        return ExitCode.SUCCESS
    else:
        renderer.print("  Status:  stopped")
        return ExitCode.ERROR

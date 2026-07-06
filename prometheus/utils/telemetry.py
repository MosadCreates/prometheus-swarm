from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

_TELEMETRY_DIR = Path.home() / ".prometheus" / "telemetry"
_COMMANDS_LOG = _TELEMETRY_DIR / "commands.ndjson"


def _ensure_dir():
    _TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


def _record(entry: dict[str, Any]):
    _ensure_dir()
    with open(_COMMANDS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


@contextmanager
def track_command(command_name: str) -> Generator[dict[str, Any], None, None]:
    start = time.perf_counter()
    result = {"exit_code": 0, "success": True}
    try:
        yield result
    except Exception:
        result["exit_code"] = 1
        result["success"] = False
        raise
    finally:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        entry = {
            "command": command_name,
            "duration_ms": duration_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "exit_code": result["exit_code"],
            "success": result["success"],
        }
        _record(entry)


def get_diagnostics() -> dict[str, Any]:
    if not _COMMANDS_LOG.exists():
        return {"total_commands": 0}

    commands: list[dict[str, Any]] = []
    with open(_COMMANDS_LOG, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                commands.append(json.loads(line))

    if not commands:
        return {"total_commands": 0}

    total = len(commands)
    successes = sum(1 for c in commands if c.get("success"))
    failures = total - successes
    durations = [c["duration_ms"] for c in commands]
    recent = commands[-20:]

    return {
        "total_commands": total,
        "successful": successes,
        "failed": failures,
        "avg_duration_ms": round(sum(durations) / total, 1) if total else 0,
        "min_duration_ms": round(min(durations), 1) if durations else 0,
        "max_duration_ms": round(max(durations), 1) if durations else 0,
        "p50_duration_ms": round(sorted(durations)[total // 2], 1) if durations else 0,
        "p95_duration_ms": round(sorted(durations)[int(total * 0.95)], 1) if durations else 0,
        "recent_commands": recent,
    }

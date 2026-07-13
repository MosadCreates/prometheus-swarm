"""Pydantic models for Dissect agent — CrashReport, PatchResult, SandboxResult."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CrashReport:
    job_id: str
    exception_type: str
    exception_message: str
    traceback: str
    script_path: str
    last_checkpoint_path: str | None = None
    epoch_at_crash: int = 0
    crash_attempt_number: int = 1
    container_name: str = ""
    exit_code: int = -1
    timestamp: str = ""

    @classmethod
    def from_event(cls, event: dict[str, Any]) -> CrashReport:
        return cls(
            job_id=event.get("job_id", ""),
            exception_type=event.get("exception_type", ""),
            exception_message=event.get("exception_message", ""),
            traceback=event.get("traceback", ""),
            script_path=event.get("script_path", ""),
            last_checkpoint_path=event.get("last_checkpoint_path"),
            epoch_at_crash=int(event.get("epoch_at_crash", 0)),
            crash_attempt_number=int(event.get("crash_attempt_number", 1)),
            container_name=event.get("container_name", ""),
            exit_code=int(event.get("exit_code", -1)),
            timestamp=event.get("timestamp", ""),
        )

    def to_event(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "exception_type": self.exception_type,
            "exception_message": self.exception_message,
            "traceback": self.traceback,
            "script_path": self.script_path,
            "last_checkpoint_path": self.last_checkpoint_path,
            "epoch_at_crash": self.epoch_at_crash,
            "crash_attempt_number": self.crash_attempt_number,
            "container_name": self.container_name,
            "exit_code": self.exit_code,
            "timestamp": self.timestamp,
        }


@dataclass
class PatchResult:
    patch_id: str
    job_id: str
    category: str
    strategy: str
    cascade_level: int
    diff_applied: str
    lines_changed: int
    sandbox_passed: bool
    patched_script_path: str
    confidence: float = 0.0
    error_message: str = ""


@dataclass
class SandboxResult:
    passed: bool
    output: str = ""


@dataclass
class DissectOutcome:
    outcome: str  # "resume", "escalate"
    patch_result: PatchResult | None = None
    reason: str = ""
    patched_script_path: str = ""
    resume_from_checkpoint: str = ""
    patch_id: str = ""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobStatusRow:
    id: str
    status: str
    agent: str
    crashes: int
    created: str = ""


@dataclass(frozen=True)
class JobResult:
    id: str
    status: str
    decision: str = ""
    reason: str = ""
    metrics: dict = field(default_factory=dict)
    endpoint_url: str | None = None
    checkpoint_path: str | None = None

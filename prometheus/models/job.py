from __future__ import annotations

import enum
from dataclasses import dataclass, field


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass(frozen=True)
class Job:
    id: str
    status: JobStatus = JobStatus.PENDING
    description: str = ""
    dataset: str = ""
    current_agent: str = ""
    crash_count: int = 0
    metrics: dict = field(default_factory=dict)
    endpoint_url: str | None = None
    created_at: str | None = None

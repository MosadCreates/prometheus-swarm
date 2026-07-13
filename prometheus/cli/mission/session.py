from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class SessionStatus(Enum):
    IDLE = "IDLE"
    COLLECTING_DESCRIPTION = "COLLECTING_DESCRIPTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass
class MissionSession:
    mission_text: str = ""
    job_id: str = ""
    created_at: datetime | None = None
    status: SessionStatus = SessionStatus.IDLE


_session: MissionSession | None = None


def get_session() -> MissionSession:
    global _session
    if _session is None:
        _session = MissionSession()
    return _session


def reset_session() -> None:
    global _session
    _session = None

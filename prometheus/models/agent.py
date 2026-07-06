from __future__ import annotations

import enum
from dataclasses import dataclass, field


class AgentStatus(enum.Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    SLEEPING = "sleeping"
    ERROR = "error"


class AgentRole(enum.Enum):
    SCOUT = "scout"
    FORGE = "forge"
    FURNACE = "furnace"
    DISSECT = "dissect"
    ARBITER = "arbiter"
    HARBOR = "harbor"


@dataclass(frozen=True)
class AgentCapability:
    name: str
    description: str
    tool_count: int = 0


@dataclass(frozen=True)
class Agent:
    role: AgentRole
    name: str
    display_name: str
    status: AgentStatus = AgentStatus.IDLE
    capabilities: list[AgentCapability] = field(default_factory=list)
    version: str = "0.1.0"

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentSummary:
    name: str
    display_name: str
    status: str
    tools: int = 0
    version: str = "0.1.0"


@dataclass(frozen=True)
class AgentDetail:
    name: str
    display_name: str
    status: str
    role: str
    version: str
    tools: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    prompt_count: int = 0

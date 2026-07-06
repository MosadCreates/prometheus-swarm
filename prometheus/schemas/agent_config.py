from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentConfig:
    name: str
    enabled: bool = True
    model: str = "claude-sonnet-4-6"
    max_retries: int = 3
    timeout_seconds: int = 300
    environment: dict[str, str] = field(default_factory=dict)

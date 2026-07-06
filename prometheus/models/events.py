from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DomainEvent:
    type: str
    source: str
    payload: dict = field(default_factory=dict)

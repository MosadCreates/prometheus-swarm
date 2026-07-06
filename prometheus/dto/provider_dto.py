from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    model: str
    configured: bool
    available: bool

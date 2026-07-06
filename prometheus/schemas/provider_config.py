from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    extra: dict[str, str] = field(default_factory=dict)

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Command:
    name: str
    category: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    tier: int = 3
    implemented: bool = True
    experimental: bool = False
    hidden: bool = False
    requires_workspace: bool = False
    requires_provider: bool = False
    permissions: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    since: str = ""
    deprecated_since: str | None = None
    replacement: str | None = None

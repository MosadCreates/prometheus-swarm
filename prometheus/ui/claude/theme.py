from __future__ import annotations

import os


def detect_color_system() -> str:
    if os.environ.get("NO_COLOR") or os.environ.get("CLICOLOR") == "0":
        return "standard"
    colorterm = os.environ.get("COLORTERM", "").lower()
    if colorterm in ("truecolor", "24bit"):
        return "truecolor"
    term = os.environ.get("TERM", "").lower()
    if "truecolor" in term or "24bit" in term:
        return "truecolor"
    if "256" in term:
        return "256"
    return "256"


CLAUDE = "#E68A4C"
CLAUDE_SHIMMER = "#F0B88A"
TEXT = "#ECECEC"
INACTIVE = "#8E8E93"
INACTIVE_SHIMMER = "#B9B9B9"
SUBTLE = "#48484A"
SUCCESS = "#5FD75F"
ERROR = "#D75F5F"
WARNING = "#D7AF00"
PERMISSION = "#7C5CFC"
BORDER_SUBTLE = "#2A2A2A"
PROMPT_BORDER = "#E68A4C"

CLAWD_BODY = "#E68A4C"
CLAWD_BG = "#0A0A0A"

AGENT_SCOUT = "#3B82F6"
AGENT_FORGE = "#6366F1"
AGENT_FURNACE = "#8B5CF6"
AGENT_DISSECT = "#A855F7"
AGENT_ARBITER = "#D946EF"
AGENT_HARBOR = "#EC4899"

RICH_THEME_OVERRIDES: dict[str, str] = {
    "claude": CLAUDE,
    "text": TEXT,
    "inactive": INACTIVE,
    "subtle": SUBTLE,
    "success": SUCCESS,
    "error": ERROR,
    "warning": WARNING,
    "permission": PERMISSION,
}

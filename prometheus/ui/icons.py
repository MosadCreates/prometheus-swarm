CHECK = "\u2713"
CROSS = "\u2717"
BULLET = "\u25cf"
DIAMOND = "\u25c6"
ARROW = "\u25b6"
TRIANGLE = "\u25b8"
FILLED = "\u25a0"
HALF = "\u25a3"
EMPTY = "\u25a1"
PIPE = "\u2502"
CORNER = "\u2514"
ELLIPSIS = "\u2026"
SEPARATOR = "\u00b7"

SPINNER = ["\u25d0", "\u25d3", "\u25d1", "\u25d2"]

ONLINE = "\u25cf"
OFFLINE = "\u25cb"
WARNING_SIGN = "\u26a0"
FLAG = "\u2691"
CANCELLED = "\u25a2"  # ▢
ESCALATED_FLAG = "\u2691"  # ⚑  (same as FLAG, semantic alias)

DIVIDER = "\u2500"

QUICK_RETRY = "\u21bb"  # ↻
RIGHTWARDS_HARPOON = "\u21c4"  # ⇄


def progress_bar(
    current: int | float,
    total: int | float,
    width: int = 20,
    *,
    filled_char: str = "\u2588",
    empty_char: str = "\u2591",
) -> str:
    """Return a text progress bar string.

    Uses a consistent style everywhere: filled blocks followed by
    empty blocks (Chapter 10.3).

    Returns something like ``██████████████░░░░░░░░░░░░`` (20 chars).
    """
    pct = max(0, min(current / max(total, 1), 1.0))
    fill_count = round(pct * width)
    empty_count = width - fill_count
    return filled_char * fill_count + empty_char * empty_count


def status_icon(ok: bool) -> str:
    return CHECK if ok else CROSS


def health_icon(status: str) -> str:
    match status:
        case "online" | "healthy" | "ready" | "connected":
            return ONLINE
        case "warning" | "busy":
            return WARNING_SIGN
        case _:
            return OFFLINE


def state_glyph(state: str) -> str:
    return {
        "idle": OFFLINE,
        "queued": OFFLINE,
        "thinking": SPINNER[0],
        "planning": DIAMOND,
        "acting": ARROW,
        "verifying": "\u2713?",
        "done": BULLET,
        "complete": BULLET,
        "error": CROSS,
        "failed": CROSS,
        "escalated": ESCALATED_FLAG,
        "cancelled": CANCELLED,
        "retrying": QUICK_RETRY,
        "retry_pending": QUICK_RETRY,
    }.get(state.lower().replace(" ", "_"), "?")

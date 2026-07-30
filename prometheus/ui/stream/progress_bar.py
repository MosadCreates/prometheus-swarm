"""Inline progress bar for the scroll-forward renderer.

Used by Furnace to show training progress::

    │   ├── Training  ████████████░░░░░░░░░░░░  48%  Fold 3/5  Epoch 7/10

Renders as a Rich Text line that can be converted to ANSI for
direct ``sys.stdout.write()`` output.
"""

from __future__ import annotations

from rich.text import Text

from prometheus.ui.theme import Theme

# ── Bar characters ───────────────────────────────────────────────────────
_FILL = "█"
_EMPTY = "░"
_BAR_WIDTH = 24


def render_progress(
    label: str = "Training",
    progress: float = 0.0,
    detail: str = "",
    width: int = _BAR_WIDTH,
) -> Text:
    """Render an inline progress bar.

    Parameters
    ----------
    label
        Label to the left of the bar (e.g. "Training").
    progress
        Float between 0.0 and 1.0.
    detail
        Optional detail text to the right (e.g. "Fold 3/5  Epoch 7/10").
    width
        Character width of the bar itself.
    """
    progress = max(0.0, min(1.0, progress))
    filled = int(progress * width)
    empty = width - filled
    pct = int(progress * 100)

    t = Text()
    t.append("   │   ├── ", style=str(Theme.tree_connector))
    t.append(f"{label}  ", style=str(Theme.body))
    t.append(_FILL * filled, style=str(Theme.info))
    t.append(_EMPTY * empty, style=str(Theme.muted))
    t.append(f"  {pct}%", style=str(Theme.body))
    if detail:
        t.append(f"  {detail}", style=str(Theme.muted))

    return t

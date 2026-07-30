from __future__ import annotations

import os
from dataclasses import dataclass


def detect_color_system() -> str:
    """Detect terminal color depth and return a Rich-compatible color system name.

    Returns ``"truecolor"`` (16.7M), ``"256"`` (8-bit), or ``"standard"`` (16 colors).

    Honors ``NO_COLOR`` and ``COLORTERM`` conventions (Chapter 12.3).
    Rich uses this when constructing ``Console(color_system=...)`` to prevent
    garbled ANSI codes on SSH, tmux, or older terminal emulators.
    """
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


@dataclass(frozen=True)
class Color:
    hex: str

    def __str__(self) -> str:
        return self.hex

    def rich(self) -> str:
        return self.hex

    def fg(self) -> str:
        return self.hex


class Theme:
    background = Color("#0A0A0A")

    primary = Color("#ECECEC")
    secondary = Color("#8E8E93")
    muted = Color("#767676")
    border = Color("#2A2A2A")
    surface = Color("#2A2A2A")

    title = Color("#ECECEC")
    body = Color("#ECECEC")
    label = Color("#8E8E93")
    metadata = Color("#8E8E93")
    disabled = Color("#48484A")

    # Design-book exact state colors (Chapter 10.1)
    state_idle = Color("#767676")
    state_thinking = Color("#5FD7D7")
    state_planning = Color("#5F87FF")
    state_acting = Color("#D7AF00")
    state_verifying = Color("#AF5FD7")
    state_done = Color("#5FD75F")
    state_error = Color("#D75F5F")
    state_escalated_bg = Color("#AF0000")
    state_escalated_fg = Color("#FFFFFF")

    accent = Color("#7C5CFC")
    highlight = Color("#7C5CFC")
    secondary_accent = Color("#7C5CFC")
    heading = Color("#ECECEC")

    info = Color("#5FD7D7")
    success = Color("#5FD75F")
    warning = Color("#D7AF00")
    error = Color("#D75F5F")

    agent_scout = Color("#3B82F6")
    agent_forge = Color("#6366F1")
    agent_furnace = Color("#8B5CF6")
    agent_dissect = Color("#A855F7")
    agent_arbiter = Color("#D946EF")
    agent_harbor = Color("#EC4899")

    command = Color("#7C5CFC")
    status_text = Color("#8E8E93")

    # ── New semantic colors for streaming UI components ──────────────────
    # Pipeline tracker
    pipeline_completed = Color("#5FD75F")
    pipeline_active = Color("#5FD7D7")
    pipeline_pending = Color("#767676")
    pipeline_error = Color("#D75F5F")
    pipeline_connector = Color("#2A2A2A")

    # Progress bars
    progress_bg = Color("#1A1A2E")
    progress_fill = Color("#5FD75F")
    progress_fill_warning = Color("#D7AF00")
    progress_fill_error = Color("#D75F5F")
    progress_text = Color("#ECECEC")

    # Header banner
    header_bg = Color("#0A0A0A")
    header_border = Color("#2A2A2A")
    header_label = Color("#8E8E93")
    header_value = Color("#ECECEC")
    header_gpu = Color("#5FD7D7")
    header_memory = Color("#D7AF00")

    # Harbor card
    harbor_card_border = Color("#EC4899")
    harbor_live = Color("#5FD75F")
    harbor_endpoint = Color("#5FD7D7")
    harbor_swagger = Color("#A855F7")
    harbor_cmd = Color("#5FD7FF")
    harbor_health_ok = Color("#5FD75F")
    harbor_health_warn = Color("#D7AF00")
    harbor_health_error = Color("#D75F5F")

    # Mission summary
    summary_card_border = Color("#2C3E50")
    summary_card_bg = Color("#1A1A2E")
    summary_label = Color("#8E8E93")
    summary_value = Color("#ECECEC")
    summary_artifact = Color("#5FD75F")
    summary_next = Color("#5FD7FF")

    # Cascade levels
    cascade_done = Color("#5FD75F")
    cascade_active = Color("#5FD7D7")
    cascade_pending = Color("#48484A")
    cascade_error = Color("#D75F5F")

    # Thinking pane
    thinking_text = Color("#8E8E93")
    thinking_glow = Color("#B0B0B4")

    # Transition banners
    transition_line = Color("#2A2A2A")
    transition_arrow = Color("#5FD7D7")
    transition_reason = Color("#8E8E93")

    # Completion card
    completion_border = Color("#5FD75F")
    completion_border_error = Color("#D75F5F")

    # Badge
    badge_text = Color("#FFFFFF")

    # Box drawing / tree connectors
    tree_connector = Color("#2A2A2A")
    tree_badge_bg = Color("#2C3E50")

    # ── Scroll-forward stream renderer tokens ────────────────────────────
    stream_thinking = Color("#8E8E93")       # Thinking text (dim, italic)
    stream_thinking_active = Color("#B0B0B4")  # Active thinking tail (brighter)
    stream_finalized = Color("#5FD7D7")      # Finalized/done text (cyan/teal instead of bright green)
    stream_subaction = Color("#8E8E93")      # Subaction detail lines
    stream_running = Color("#5F87AF")        # Running indicator (slate blue)
    stream_cost = Color("#D7AF00")           # Token cost display


    @classmethod
    def rich_theme(cls):
        from rich.theme import Theme as RichTheme

        return RichTheme(
            {
                "primary": str(cls.primary),
                "secondary": str(cls.secondary),
                "success": str(cls.success),
                "warning": str(cls.warning),
                "error": str(cls.error),
                "info": str(cls.info),
                "accent": str(cls.accent),
                "highlight": str(cls.highlight),
                "muted": str(cls.muted),
                "border": str(cls.border),
                "title": str(cls.title),
                "body": str(cls.body),
                "label": str(cls.label),
                "metadata": str(cls.metadata),
                # New semantic colors
                "pipeline_completed": str(cls.pipeline_completed),
                "pipeline_active": str(cls.pipeline_active),
                "pipeline_pending": str(cls.pipeline_pending),
                "pipeline_error": str(cls.pipeline_error),
                "pipeline_connector": str(cls.pipeline_connector),
                "progress_bg": str(cls.progress_bg),
                "progress_fill": str(cls.progress_fill),
                "progress_fill_warning": str(cls.progress_fill_warning),
                "progress_fill_error": str(cls.progress_fill_error),
                "progress_text": str(cls.progress_text),
                "header_bg": str(cls.header_bg),
                "header_border": str(cls.header_border),
                "header_label": str(cls.header_label),
                "header_value": str(cls.header_value),
                "header_gpu": str(cls.header_gpu),
                "header_memory": str(cls.header_memory),
                "harbor_card_border": str(cls.harbor_card_border),
                "harbor_live": str(cls.harbor_live),
                "harbor_endpoint": str(cls.harbor_endpoint),
                "harbor_swagger": str(cls.harbor_swagger),
                "harbor_cmd": str(cls.harbor_cmd),
                "harbor_health_ok": str(cls.harbor_health_ok),
                "harbor_health_warn": str(cls.harbor_health_warn),
                "harbor_health_error": str(cls.harbor_health_error),
                "summary_card_border": str(cls.summary_card_border),
                "summary_card_bg": str(cls.summary_card_bg),
                "summary_label": str(cls.summary_label),
                "summary_value": str(cls.summary_value),
                "summary_artifact": str(cls.summary_artifact),
                "summary_next": str(cls.summary_next),
                "tree_connector": str(cls.tree_connector),
                "tree_badge_bg": str(cls.tree_badge_bg),
                # Cascade
                "cascade_done": str(cls.cascade_done),
                "cascade_active": str(cls.cascade_active),
                "cascade_pending": str(cls.cascade_pending),
                "cascade_error": str(cls.cascade_error),
                # Thinking
                "thinking_text": str(cls.thinking_text),
                "thinking_glow": str(cls.thinking_glow),
                # Transition
                "transition_line": str(cls.transition_line),
                "transition_arrow": str(cls.transition_arrow),
                "transition_reason": str(cls.transition_reason),
                # Completion
                "completion_border": str(cls.completion_border),
                "completion_border_error": str(cls.completion_border_error),
                "badge_text": str(cls.badge_text),
                # Stream renderer
                "stream_thinking": str(cls.stream_thinking),
                "stream_thinking_active": str(cls.stream_thinking_active),
                "stream_finalized": str(cls.stream_finalized),
                "stream_subaction": str(cls.stream_subaction),
                "stream_running": str(cls.stream_running),
                "stream_cost": str(cls.stream_cost),
            }
        )

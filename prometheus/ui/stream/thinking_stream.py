# ruff: noqa: E501 — display strings with long styled fragments
"""Token-by-token thinking stream — Dissect only.

Manages the live LLM token stream for the Dissect agent. Tokens arrive
one at a time from the ``agent_thinking`` Redis stream. This class:

1. Buffers them into word-wrapped lines.
2. Finalizes complete lines (printed permanently via the renderer's
   ``_emit_permanent()`` — they scroll up and never change).
3. Keeps the last partial line in the "active tail" (rewritten via ``\\r``).
4. Applies a subtle glow animation to the newest tokens.

Only Dissect calls the LLM with ``stream=True``. The other five agents
are deterministic and never produce thinking tokens.
"""

from __future__ import annotations

import math
import time
from collections import deque
from io import StringIO

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.theme import Theme


# Maximum visible width for the thinking text (excluding indent)
_MAX_THINKING_WIDTH = 72


class ThinkingStream:
    """Buffers LLM tokens and produces renderable lines.

    Lifecycle::

        stream = ThinkingStream()
        stream.append_token("The ")
        stream.append_token("dataset ")
        ...

        # Get completed lines to finalize (print permanently):
        for line in stream.drain_complete_lines():
            emit_permanent(line)

        # Get the active tail (rewrite via \\r):
        tail = stream.render_active_tail(width=80, indent="│   ")
    """

    def __init__(self) -> None:
        self._tokens: deque[str] = deque(maxlen=8000)
        self._full_text: list[str] = []  # All tokens concatenated
        self._finalized_up_to: int = 0  # Character index already finalized
        self._last_append: float = 0.0
        self._token_count: int = 0

    def append_token(self, token: str) -> None:
        """Append a new token from the LLM stream."""
        self._tokens.append(token)
        self._full_text.append(token)
        self._token_count += 1
        self._last_append = time.monotonic()

    @property
    def token_count(self) -> int:
        return self._token_count

    @property
    def has_content(self) -> bool:
        return self._token_count > 0

    def drain_complete_lines(self, width: int = _MAX_THINKING_WIDTH) -> list[str]:
        """Return completed lines that should be finalized (printed permanently).

        A line is "complete" when a newline or word-wrap boundary has been
        crossed. We keep only the last partial line as the active tail.
        """
        full = "".join(self._full_text)
        if len(full) <= self._finalized_up_to:
            return []

        # Word-wrap the unfinalized portion
        unfinalized = full[self._finalized_up_to :]
        wrapped = self._word_wrap(unfinalized, width)

        if len(wrapped) <= 1:
            # Only a partial line — nothing to finalize yet
            return []

        # All lines except the last are complete
        complete = wrapped[:-1]
        # Calculate how many characters we finalized
        finalized_text = "\n".join(complete)
        # Account for the characters consumed (including implicit newlines from wrapping)
        consumed = 0
        for line in complete:
            consumed += len(line.rstrip())
            # Skip any whitespace that was at the wrap boundary
            remaining = unfinalized[consumed:]
            if remaining and remaining[0] == " ":
                consumed += 1

        self._finalized_up_to += consumed

        return complete

    def render_active_tail(self, width: int = _MAX_THINKING_WIDTH) -> str:
        """Return the current partial line (the active tail).

        This is the text that gets rewritten via ``\\r`` on every tick.
        """
        full = "".join(self._full_text)
        if len(full) <= self._finalized_up_to:
            return ""
        unfinalized = full[self._finalized_up_to :]
        wrapped = self._word_wrap(unfinalized, width)
        return wrapped[-1] if wrapped else ""

    def render_token_summary(self) -> str:
        """Return a summary like '847 tokens' for finalization."""
        return f"{self._token_count:,} tokens"

    @staticmethod
    def _word_wrap(text: str, width: int) -> list[str]:
        """Wrap text at word boundaries to fit within width."""
        if not text:
            return []
        lines: list[str] = []
        for raw_line in text.split("\n"):
            if not raw_line:
                lines.append("")
                continue
            current = ""
            for word in raw_line.split(" "):
                test = f"{current} {word}".strip() if current else word
                if len(test) > width and current:
                    lines.append(current)
                    current = word
                else:
                    current = test
            if current:
                lines.append(current)
        return lines

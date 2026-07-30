"""Scroll-forward streaming renderer — Claude Code-style agent streaming.

This package implements a scroll-forward rendering architecture where each
line is printed once and scrolls up. Only the active agent's badge line
and (for Dissect) the thinking tail are rewritten via \\r. The header is
updated in-place via ANSI cursor-up escape sequences.

Public API::

    from prometheus.ui.stream import StreamRenderer, run_stream

    renderer = StreamRenderer(redis, mission_id, problem_description)
    await renderer.run()

    # Or the convenience wrapper:
    await run_stream(redis, mission_id, problem_description)
"""

from prometheus.ui.stream.renderer import StreamRenderer, run_stream

__all__ = ["StreamRenderer", "run_stream"]

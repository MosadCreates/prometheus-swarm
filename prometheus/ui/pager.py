"""Interactive pager for CLI list views.

Provides j/k navigation, / for search/filter, Enter for selection,
and q/Esc to dismiss.  Used by ``mission list --interactive``,
``agent list --interactive``, etc.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from rich.table import Table
from rich.text import Text

from prometheus.ui.console import console
from prometheus.ui.styles import Token


def interactive_table(
    title: str,
    headers: list[str],
    rows: list[list[Any]],
    *,
    selectable: bool = True,
) -> dict[str, Any] | None:
    """Display *rows* in an interactive scrollable table.

    Keyboard controls:
      j / Down    Move selection down
      k / Up      Move selection up
      /           Focus inline search input
      Enter       Select the highlighted row (returns its dict)
      q / Esc     Dismiss (returns ``None``)

    Parameters
    ----------
    title
        Table title shown in the header bar.
    headers
        Column names.
    rows
        List of row values (one list per row).
    selectable
        If ``True``, Enter selects a row.  If ``False``, Enter dismisses.

    Returns
    -------
    A dict mapping header names to values for the selected row, or
    ``None`` if dismissed without selection.
    """
    try:
        import msvcrt as _m
    except ImportError:
        _fallback_print(title, headers, rows)
        return None

    if not sys.stdin.isatty():
        _fallback_print(title, headers, rows)
        return None

    selected = 0
    scroll_offset = 0
    search_text = ""
    search_mode = False
    search_buf: list[str] = []
    filtered_rows = list(rows)
    page_rows = max(_terminal_height() - 5, 5)
    last_key_time = 0.0

    # Scroll acceleration
    _scroll_velocity = 1
    _scroll_decay = 0.0

    import time as _t

    def _scroll_accel() -> int:
        nonlocal _scroll_velocity, _scroll_decay
        now = _t.monotonic()
        if now - _scroll_decay < 0.25:
            _scroll_velocity = min(_scroll_velocity + 1, 12)
        else:
            _scroll_velocity = 1
        _scroll_decay = now
        return _scroll_velocity

    def _filter() -> None:
        nonlocal filtered_rows, selected, scroll_offset
        if not search_text:
            filtered_rows = list(rows)
        else:
            lower = search_text.lower()
            filtered_rows = [r for r in rows if any(lower in str(c).lower() for c in r)]
        selected = min(selected, max(0, len(filtered_rows) - 1))
        scroll_offset = max(0, min(scroll_offset, max(0, len(filtered_rows) - page_rows)))

    def _render() -> None:
        nonlocal scroll_offset
        sys.stdout.write("\x1b[?25l")  # hide cursor
        sys.stdout.write("\r\x1b[J")
        lines: list[str] = []

        # Header bar
        search_indicator = f"  /{''.join(search_buf)}\u258c" if search_mode else ""
        lines.append(f"  [{Token.accent}]{title}[/]{search_indicator}")
        lines.append(
            f"  [{Token.secondary}]{len(filtered_rows)} item(s)[/]  "
            f"[{Token.muted}]j/k nav  / search  Enter select  q quit[/]"
        )
        lines.append("")

        if not filtered_rows:
            lines.append(f"  [{Token.muted}]No matching items.[/]")
        else:
            col_widths = _compute_col_widths(headers, filtered_rows)
            fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
            header_fmt = fmt.format(*headers)
            lines.append(f"  [{Token.border}]{header_fmt}[/]")
            lines.append(
                f"  [{Token.border}]" + "-" * (sum(col_widths) + 2 * (len(headers) - 1)) + "[/]"
            )

            end = min(scroll_offset + page_rows, len(filtered_rows))
            for i in range(scroll_offset, end):
                row = filtered_rows[i]
                prefix = f"[{Token.success}]\u25b6[/]" if i == selected else " "
                style = f"reverse {Token.accent}" if i == selected else ""
                vals = [str(c) for c in row]
                line = fmt.format(*vals)
                lines.append(f"  [{style}]{prefix} {line}[/]")

        console.print("\n".join(lines), end="")
        console.file.flush()

    _render()

    while True:
        ch = _m.getwch()
        now = _t.monotonic()

        if ch in ("\x00", "\xe0"):
            ext = _m.getwch()
            if ext == "H":  # Up
                if not search_mode and filtered_rows:
                    vel = _scroll_accel()
                    selected = max(selected - vel, 0)
                    if selected < scroll_offset:
                        scroll_offset = selected
                    _render()
            elif ext == "P":  # Down
                if not search_mode and filtered_rows:
                    vel = _scroll_accel()
                    selected = min(selected + vel, len(filtered_rows) - 1)
                    if selected >= scroll_offset + page_rows:
                        scroll_offset = selected - page_rows + 1
                    _render()
            continue

        # Enter
        if ch == "\r":
            sys.stdout.write("\r\x1b[J")
            sys.stdout.write("\x1b[?25h")
            console.print()
            if search_mode:
                search_text = "".join(search_buf)
                search_mode = False
                _filter()
                _render()
                continue
            if filtered_rows and selected >= 0:
                return dict(zip(headers, filtered_rows[selected]))
            return None

        # / — enter search mode
        if ch == "/":
            if not search_mode:
                search_mode = True
                search_buf.clear()
                _render()
            continue

        # Esc — cancel search or dismiss
        if ch == "\x1b":
            if search_mode:
                search_mode = False
                search_buf.clear()
                _render()
                continue
            sys.stdout.write("\r\x1b[J")
            sys.stdout.write("\x1b[?25h")
            console.print()
            return None

        # q — dismiss
        if ch in ("q", "Q"):
            if search_mode:
                search_mode = False
                search_buf.clear()
                _render()
                continue
            sys.stdout.write("\r\x1b[J")
            sys.stdout.write("\x1b[?25h")
            console.print()
            return None

        # Backspace (in search mode)
        if ch in ("\b", "\x7f"):
            if search_mode and search_buf:
                search_buf.pop()
                search_text = "".join(search_buf)
                _filter()
                _render()
            continue

        # Printable (in search mode)
        if search_mode and ch.isprintable():
            search_buf.append(ch)
            search_text = "".join(search_buf)
            _filter()
            _render()
            continue


def _compute_col_widths(headers: list[str], rows: list[list[Any]]) -> list[int]:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))
    term_w = _terminal_width()
    total = sum(widths) + 2 * (len(headers) - 1)
    if total > term_w:
        excess = total - term_w
        for i in range(len(widths) - 1, -1, -1):
            if widths[i] > 10:
                shrink = min(widths[i] - 10, excess)
                widths[i] -= shrink
                excess -= shrink
                if excess <= 0:
                    break
    return widths


def _terminal_width() -> int:
    import shutil

    return shutil.get_terminal_size().columns


def _terminal_height() -> int:
    import shutil

    return shutil.get_terminal_size().lines


def _fallback_print(title: str, headers: list[str], rows: list[list[Any]]) -> None:
    """Non-interactive fallback: just print the table."""
    table = Table(title=title, title_style=Token.accent)
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*[str(c) for c in row])
    console.print(table)

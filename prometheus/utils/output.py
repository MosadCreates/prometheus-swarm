"""Three-mode output contract: interactive / plain / json.

Every command that implements the Book Chapter 9 contract uses this
module to emit its output.  The three modes render the exact same data
differently; ``--format`` or TTY detection chooses which one fires.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from enum import auto, Enum
from typing import Any

import click

from prometheus.ui.renderers import renderer_from_ctx


class Format(Enum):
    INTERACTIVE = auto()
    PLAIN = auto()
    JSON = auto()


def detect_format(ctx: click.Context) -> Format:
    """Return the active output format.

    Order of precedence:
      1. ``--format`` flag (if set to a valid value)
      2. TTY detection: interactive if stdout is a TTY, else plain
    """
    fmt_str: str = ctx.find_root().obj.get("format", "")
    if fmt_str == "interactive":
        return Format.INTERACTIVE
    if fmt_str == "plain":
        return Format.PLAIN
    if fmt_str == "json":
        return Format.JSON
    return Format.INTERACTIVE if sys.stdout.isatty() else Format.PLAIN


def emit_str_table(
    ctx: click.Context,
    fmt: Format,
    *,
    headers: list[str],
    rows: list[list[str]],
    json_schema: str = "",
) -> None:
    """Emit a string table in the requested format."""
    match fmt:
        case Format.INTERACTIVE:
            _interactive_table(ctx, headers, rows)
        case Format.PLAIN:
            _plain_table(headers, rows)
        case Format.JSON:
            _json_table(headers, rows, json_schema)


def emit_dict(
    ctx: click.Context,
    fmt: Format,
    data: dict[str, Any],
    schema: str = "",
) -> None:
    """Emit a single dict in the requested format."""
    match fmt:
        case Format.INTERACTIVE:
            _interactive_dict(ctx, data)
        case Format.PLAIN:
            _plain_dict(data)
        case Format.JSON:
            print(
                json.dumps(
                    {**({"schema": schema} if schema else {}), **data}, indent=2, default=str
                )
            )


def emit_log_lines(
    ctx: click.Context,
    fmt: Format,
    events: list[dict[str, Any]],
    schema: str = "",
) -> None:
    """Emit an event log in the requested format."""
    match fmt:
        case Format.INTERACTIVE:
            _interactive_log(ctx, events)
        case Format.PLAIN:
            _plain_log(events)
        case Format.JSON:
            print(json.dumps({"schema": schema, "events": events}, indent=2, default=str))


# ── Interactive renderers ────────────────────────────────────────────────────


def _interactive_table(ctx: click.Context, headers: list[str], rows: list[list[str]]) -> None:
    r = renderer_from_ctx(ctx)
    r.table(headers, rows)


def _interactive_dict(ctx: click.Context, data: dict[str, Any]) -> None:
    items: list[tuple[str, str]] = []
    for k, v in data.items():
        items.append((k.replace("_", " ").title(), str(v)))
    r = renderer_from_ctx(ctx)
    r.status(items, title=data.get("mission_id") or "")


def _interactive_log(ctx: click.Context, events: list[dict[str, Any]]) -> None:
    from prometheus.ui.console import console

    for ev in events:
        ts = _fmt_ts(ev.get("timestamp", ""))
        agent = (ev.get("agent", "?") or "?").lower()
        state = (ev.get("state", "") or ev.get("phase", "") or "").lower()
        summary = ev.get("summary", "") or ev.get("event", "")
        console.print(
            f"  [dim]{ts}[/dim] [bold]{agent:<8}[/bold] [cyan]{state:<12}[/cyan] {summary}"
        )


# ── Plain renderers ─────────────────────────────────────────────────────────


def _plain_table(headers: list[str], rows: list[list[str]]) -> None:
    print("\t".join(headers))
    for row in rows:
        print("\t".join(row))


def _json_table(headers: list[str], rows: list[list[str]], schema: str = "") -> None:
    records = [dict(zip(headers, row)) for row in rows]
    print(
        json.dumps(
            {"schema": schema, "count": len(records), "records": records}, indent=2, default=str
        )
    )


def _plain_dict(data: dict[str, Any]) -> None:
    for k, v in data.items():
        print(f"{k}={v}")


def _plain_log(events: list[dict[str, Any]]) -> None:
    for ev in events:
        ts = _fmt_ts(ev.get("timestamp", ""))
        agent = ev.get("agent", "?")
        state = ev.get("state", "") or ev.get("phase", "")
        summary = ev.get("summary", "") or ev.get("event", "")
        print(f"{ts} {agent} {state} {summary}")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _fmt_ts(ts: str) -> str:
    if not ts:
        return "--:--:--"
    try:
        if "T" in ts:
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%H:%M:%S")
        return ts[:8]
    except (ValueError, TypeError):
        return ts[:8]

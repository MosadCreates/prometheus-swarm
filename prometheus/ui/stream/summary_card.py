# ruff: noqa: E501 — display strings with long styled fragments
"""Mission summary card — the completion experience.

Renders a rich bordered card when a mission completes or fails::

    ╭───────────── Mission Summary · fraud-detect-a3f9 ─────────────────────╮
    │                                                                        │
    │  ✔ fraud-detect-a3f9                                                   │
    │                                                                        │
    │  Result    LightGBM · AUC-ROC: 0.9234 (≥ 0.9000 ✔)                   │
    │  Duration  03m 42s                                                     │
    │  Crashes   1 repaired (column_rename)                                  │
    │  …                                                                     │
    ╰────────────────────────────────────────────────────────────────────────╯

Builds on the same data model as the existing MissionSummaryCard but
renders for direct ``sys.stdout.write()`` output in the scroll-forward
renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import Any

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.theme import Theme


@dataclass
class SummaryData:
    """Data for the mission summary card."""

    mission_id: str = ""
    status: str = "complete"  # "complete" | "error"
    winner_architecture: str = ""
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float | None = None
    duration_seconds: float = 0.0
    dissect_patches: int = 0
    dissect_categories: list[str] = field(default_factory=list)
    endpoint_url: str = ""
    model_format: str = "onnx"
    health_status: str = ""
    health_latency_ms: float | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error_detail: str = ""
    failed_agent: str = ""
    agent_states: dict[str, str] = field(default_factory=dict)


def _format_duration(seconds: float) -> str:
    secs = int(seconds)
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    secs = secs % 60
    return f"{mins:02d}m {secs:02d}s"


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f}KB"
    return f"{size_bytes / 1024 / 1024:.1f}MB"


def render_summary(data: SummaryData, width: int = 78) -> str:
    """Render the complete summary card as an ANSI string."""
    w = min(width - 2, 96)
    inner = w - 2

    is_success = data.status == "complete"
    border_color = str(Theme.success) if is_success else str(Theme.error)
    slug = data.mission_id[:20] if data.mission_id else "—"

    t = Text()

    # ── Top border with title ──
    title = f" Mission {'Summary' if is_success else 'Failed'} · {slug} "
    title_len = len(title)
    dashes = max(0, inner - title_len)
    left_dashes = dashes // 2
    right_dashes = dashes - left_dashes

    t.append("╭", style=border_color)
    t.append("─" * left_dashes, style=border_color)
    t.append(title, style=Style(bold=True, color="#FFFFFF", bgcolor=border_color))
    t.append("─" * right_dashes, style=border_color)
    t.append("╮\n", style=border_color)

    # ── Empty line ──
    t.append("│", style=border_color)
    t.append(" " * inner)
    t.append("│\n", style=border_color)

    # ── Status line ──
    t.append("│ ", style=border_color)
    if is_success:
        t.append(" ✔ ", style=str(Theme.success))
    else:
        t.append(" ✘ ", style=str(Theme.error))
    t.append(slug, style=f"bold {Theme.accent}")
    t.append(" " * max(1, inner - len(slug) - 4))
    t.append("│\n", style=border_color)

    # ── Empty line ──
    t.append("│", style=border_color)
    t.append(" " * inner)
    t.append("│\n", style=border_color)

    if is_success:
        _build_success_body(t, data, inner, border_color)
    else:
        _build_error_body(t, data, inner, border_color)

    # ── Empty line ──
    t.append("│", style=border_color)
    t.append(" " * inner)
    t.append("│\n", style=border_color)

    # ── Next steps ──
    _build_next_steps(t, data, inner, border_color, is_success)

    # ── Bottom border ──
    t.append("╰", style=border_color)
    t.append("─" * inner, style=border_color)
    t.append("╯", style=border_color)

    # Convert to ANSI
    buf = StringIO()
    console = Console(
        file=buf,
        width=width,
        color_system="auto",
        force_terminal=True,
        emoji=False,
        highlight=False,
    )
    console.print(t, end="")
    return buf.getvalue()


def _kv_line(t: Text, key: str, value: str, inner: int, bc: str, value_style: str = "") -> None:
    """Append a key-value row inside the card."""
    t.append("│ ", style=bc)
    t.append(f" {key:<10}", style=str(Theme.muted))
    vs = value_style or str(Theme.body)
    t.append(value, style=vs)
    t.append(" " * max(1, inner - 12 - len(value)))
    t.append("│\n", style=bc)


def _build_success_body(t: Text, data: SummaryData, inner: int, bc: str) -> None:
    """Build the body for a successful mission."""
    # Result
    result = ""
    if data.winner_architecture:
        result = data.winner_architecture
        if data.metric_name:
            result += f" · {data.metric_name}: {data.metric_value:.4f}"
        if data.threshold is not None:
            passed = data.metric_value >= data.threshold
            result += f" (≥ {data.threshold:.4f} {'✔' if passed else '✘'})"
    if result:
        _kv_line(t, "Result", result, inner, bc)

    # Duration
    _kv_line(t, "Duration", _format_duration(data.duration_seconds), inner, bc)

    # Crashes
    if data.dissect_patches > 0:
        cats = ", ".join(data.dissect_categories) if data.dissect_categories else "auto-patch"
        _kv_line(t, "Crashes", f"{data.dissect_patches} repaired ({cats})", inner, bc)

    # Harbor deployment
    if data.endpoint_url:
        t.append("│", style=bc)
        t.append(" " * inner)
        t.append("│\n", style=bc)

        _kv_line(t, "Serving", f"● {data.endpoint_url}", inner, bc, str(Theme.success))
        if data.model_format:
            model_str = f"{data.winner_architecture or 'Model'} ({data.model_format.upper()})"
            _kv_line(t, "Model", model_str, inner, bc)
        _kv_line(t, "Predict", f"POST {data.endpoint_url}/predict", inner, bc, str(Theme.info))
        _kv_line(t, "Swagger", f"GET  {data.endpoint_url}/docs", inner, bc, str(Theme.info))
        if data.health_status:
            health_icon = "✔" if data.health_status == "healthy" else "✘"
            lat = f" ({data.health_latency_ms:.0f}ms)" if data.health_latency_ms else ""
            _kv_line(
                t,
                "Health",
                f"{health_icon} {data.health_status.title()}{lat}",
                inner,
                bc,
                str(Theme.success) if data.health_status == "healthy" else str(Theme.error),
            )

    # Artifacts
    if data.artifacts:
        t.append("│", style=bc)
        t.append(" " * inner)
        t.append("│\n", style=bc)

        _kv_line(t, "Artifacts", "", inner, bc)
        for artifact in data.artifacts:
            name = artifact.get("name", "artifact")
            size = _format_size(artifact.get("size_bytes", 0))
            t.append("│ ", style=bc)
            t.append(f"  ✔ {name}", style=str(Theme.success))
            t.append(f" ({size})", style=str(Theme.muted))
            t.append(" " * max(1, inner - len(name) - len(size) - 8))
            t.append("│\n", style=bc)


def _build_error_body(t: Text, data: SummaryData, inner: int, bc: str) -> None:
    """Build the body for a failed mission."""
    if data.failed_agent:
        dur = _format_duration(data.duration_seconds)
        _kv_line(t, "Failed at", f"{data.failed_agent} (after {dur})", inner, bc, str(Theme.error))
    if data.error_detail:
        detail = data.error_detail
        if len(detail) > inner - 12:
            detail = detail[: inner - 15] + "…"
        _kv_line(t, "Error", detail, inner, bc, str(Theme.error))

    # Agent states ribbon
    if data.agent_states:
        agents_str = "  ".join(
            f"{'✔' if s == 'complete' else '✘' if s == 'error' else '○'} {a}"
            for a, s in data.agent_states.items()
        )
        _kv_line(t, "Agents", agents_str, inner, bc)


def _build_next_steps(
    t: Text,
    data: SummaryData,
    inner: int,
    bc: str,
    is_success: bool,
) -> None:
    """Build the next steps section."""
    t.append("│ ", style=bc)
    t.append(" Next steps", style=str(Theme.muted))
    t.append(" " * max(1, inner - 12))
    t.append("│\n", style=bc)

    steps: list[str] = []
    if is_success:
        if data.endpoint_url:
            steps.append(f"curl -X POST {data.endpoint_url}/predict -d @input.json")
        slug = data.mission_id[:8] if data.mission_id else "<id>"
        steps.append(f"prometheus mission report {slug}")
        if data.endpoint_url:
            steps.append("prometheus model export --to ./deploy")
    else:
        slug = data.mission_id[:8] if data.mission_id else "<id>"
        if data.failed_agent:
            steps.append(f"prometheus mission logs {slug} --agent {data.failed_agent}")
        steps.append("prometheus doctor")

    for step in steps:
        t.append("│ ", style=bc)
        t.append("  • ", style=str(Theme.muted))
        t.append(step, style=str(Theme.info))
        t.append(" " * max(1, inner - len(step) - 5))
        t.append("│\n", style=bc)

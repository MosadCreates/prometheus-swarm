from __future__ import annotations


from rich.console import Console
from rich.panel import Panel

from prometheus.ui.theme import Theme

_ACCENT = str(Theme.accent)
_MUTED = str(Theme.muted)
_BODY = str(Theme.body)
_BORDER = str(Theme.border)
_SECONDARY = str(Theme.secondary)
_AGENT_FADED = "#48484A"


def _get_workspace() -> str:
    try:
        import tomllib
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["name"]
    except Exception:
        return "prometheus-swarm"


def _count_this_week() -> int:
    from pathlib import Path as _Path

    import datetime

    outputs = _Path("outputs")
    if not outputs.exists():
        return 0
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)
    count = 0
    for child in outputs.iterdir():
        if child.is_dir() and (child / "trace.jsonl").exists():
            try:
                mtime = datetime.datetime.fromtimestamp((child / "trace.jsonl").stat().st_mtime)
                if mtime >= week_ago:
                    count += 1
            except (OSError, ValueError):
                pass
    return count


def _build_logo_lines() -> list[str]:
    BOLD = "bold"
    return [
        "",
        f"  [{_ACCENT}]\u250c\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2510[/]",
        f"  [{_ACCENT}]\u2502[/]  [{_BODY}]Autonomous ML Engineering[/]  [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]                                   [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]             [{_ACCENT}]\u2550\u2550\u2550\u2588\u2588\u2588\u2550\u2550\u2550[/]              [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]            [{_ACCENT}]\u255d\u255f\u2588\u2588\u2588\u2588\u2588\u255f\u255c[/]             [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]              [{_MUTED}]\u2558\u2558 \u255d\u255d[/]               [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]                                   [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]      [{BOLD}]6 Specialized Agents[/]      [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]   [{_MUTED}]Scout \u2192 Forge \u2192 Furnace[/]   [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]  [{_MUTED}]Dissect \u2192 Arbiter \u2192 Harbor[/]  [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2502[/]                                   [{_ACCENT}]\u2502[/]",
        f"  [{_ACCENT}]\u2514\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2518[/]",
    ]


def _build_quickstart_lines() -> list[str]:
    lines = [
        f"  [{_BODY}]\u2501 Quick Start[/]",
        f"    [{_MUTED}]mission new --file data.csv[/]",
        f"    [{_MUTED}]mission list[/]",
        f"    [{_MUTED}]cockpit[/]",
        f"    [{_MUTED}]doctor[/]",
        f"  [{_BORDER}]\u2500[/]  " * 20 + "",
        f"    [{_MUTED}]/docs[/] for full reference",
        "",
        f"  [{_BODY}]\u2501 Features[/]",
        f"    [{_MUTED}]\u25cf[/]  Dissect self-patching crash recovery",
        f"    [{_MUTED}]\u25cf[/]  Harbor live ONNX + FastAPI serving",
        f"    [{_MUTED}]\u25cf[/]  Arbiter auto model evaluation",
        f"    [{_MUTED}]\u25cf[/]  Cockpit TUI real-time telemetry",
        f"  [{_BORDER}]\u2500[/]  " * 20 + "",
    ]
    return lines


def animate_startup(console: Console, fast: bool = False) -> None:
    HORIZ = "\u2500"

    if fast:
        workspace = _get_workspace()
        weekly = _count_this_week()
        suffix = f"{weekly} mission{'s' if weekly != 1 else ''} this week"
        console.print(
            f"  prometheus \u00b7 {workspace} \u00b7 {suffix}",
            style=_SECONDARY,
            overflow="ellipsis",
            no_wrap=True,
        )
        console.print(
            f"  [{_BORDER}]{HORIZ * 48}[/]",
            overflow="ellipsis",
            no_wrap=True,
        )
        return

    logo_lines = _build_logo_lines()
    qs_lines = _build_quickstart_lines()

    max_logo = max(_plain_len(line) for line in logo_lines)
    gap = 4

    combined_lines: list[str] = []
    num_rows = max(len(logo_lines), len(qs_lines))
    for i in range(num_rows):
        left = logo_lines[i] if i < len(logo_lines) else ""
        right = qs_lines[i] if i < len(qs_lines) else ""
        cur_left = _plain_len(left)
        spacer = " " * (max_logo - cur_left + gap)
        combined_lines.append(f"{left}{spacer}{right}")

    combined_text = "\n".join(combined_lines)

    panel = Panel(
        combined_text,
        title=f"[bold {_ACCENT}]\u2500\u2500\u2500 Prometheus Swarm v0.1.0 \u2500\u2500\u2500[/]",
        border_style=_BORDER,
        padding=(1, 2),
        subtitle=f"[{_MUTED}]{_get_workspace()} \u00b7 {_count_this_week()} missions this week[/]",
        subtitle_align="right",
    )
    console.print(panel)
    console.print()


def _plain_len(marked: str) -> int:
    """Return length of a Rich-markup string with tags stripped."""
    import re

    return len(re.sub(r"\[/?\w+(?:[=#][^\]]*)?\]", "", marked))

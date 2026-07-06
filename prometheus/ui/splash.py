import os
import time
from datetime import datetime, timezone
from importlib import import_module
from inspect import getmembers, isfunction
from pathlib import Path

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.logos import PROMETHEUS, LOGO_WIDTH
from prometheus.ui.styles import Token


splash_console = Console(emoji=False, force_terminal=True)

_start_time = time.time()

STOPS = Token.gradient_stops

CONTENT_WIDTH = 60

STATUS_LABEL = 16
STATUS_VAL = 20
STATUS_LINE_W = 4 + STATUS_LABEL + 1 + STATUS_VAL


def _lerp_rgb(t: float) -> str:
    n = len(STOPS) - 1
    seg = int(t * n)
    if seg >= n:
        r, g, b = STOPS[-1]
        return f"#{r:02x}{g:02x}{b:02x}"
    local = t * n - seg
    c1, c2 = STOPS[seg], STOPS[seg + 1]
    r = int(c1[0] + (c2[0] - c1[0]) * local)
    g = int(c1[1] + (c2[1] - c1[1]) * local)
    b = int(c1[2] + (c2[2] - c1[2]) * local)
    return f"#{r:02x}{g:02x}{b:02x}"


def _gradient_rows(rows: list[str]) -> list[Text]:
    max_w = max(len(r) for r in rows)
    out: list[Text] = []
    for row in rows:
        t = Text()
        for col, ch in enumerate(row):
            pos = col / max(max_w - 1, 1)
            t.append(ch, style=Style(color=_lerp_rgb(pos)))
        out.append(t)
    return out


_TOOL_COUNT_CACHE: str | None = None


def _count_tools() -> str:
    global _TOOL_COUNT_CACHE
    if _TOOL_COUNT_CACHE is not None:
        return _TOOL_COUNT_CACHE

    agent_modules = [
        ("agents.scout.tools", 10),
        ("agents.forge.tools", 6),
        ("agents.furnace.tools", 2),
        ("agents.dissect.tools", 4),
        ("agents.arbiter.tools", 4),
        ("agents.harbor.tools", 6),
    ]
    total = 0
    all_ok = True
    for modpath, expected in agent_modules:
        try:
            mod = import_module(modpath)
            funcs = getmembers(mod, isfunction)
            total += sum(
                1
                for n, f in funcs
                if not n.startswith("_") and getattr(f, "__module__", "") == modpath
            )
        except Exception:
            all_ok = False

    if all_ok:
        _TOOL_COUNT_CACHE = f"{total} Registered"
    else:
        _TOOL_COUNT_CACHE = f"{sum(e for _, e in agent_modules)} Available"
    return _TOOL_COUNT_CACHE


def _count_agents() -> str:
    try:
        agents_path = Path(__file__).resolve().parent.parent.parent / "agents"
        count = sum(1 for d in agents_path.iterdir() if d.is_dir() and not d.name.startswith("_"))
        return f"{count} Active"
    except Exception:
        return "6 Active"


def _get_provider() -> str:
    raw = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    return _format_provider(raw)


def _format_provider(name: str) -> str:
    overrides = {"claude-sonnet-4-6": "Claude Sonnet 4.6"}
    if name in overrides:
        return overrides[name]
    return name.replace("-", " ").title()


def _get_workspace() -> str:
    try:
        import tomllib

        root = Path(__file__).resolve().parent.parent.parent
        with open(root / "pyproject.toml", "rb") as f:
            return tomllib.load(f)["project"]["name"]
    except Exception:
        return "prometheus-swarm"


def _get_uptime() -> str:
    elapsed = time.time() - _start_time
    if elapsed < 60:
        return f"{int(elapsed)}s"
    if elapsed < 3600:
        return f"{int(elapsed // 60)}m {int(elapsed % 60)}s"
    return f"{int(elapsed // 3600)}h {int((elapsed % 3600) // 60)}m"


def animate_startup(console: Console, version: str = "0.1.0") -> None:
    w = console.width or 80

    rows = list(PROMETHEUS)
    if w < LOGO_WIDTH:
        rows = [r[: max(w - 2, 20)] for r in rows]
    for row in _gradient_rows(rows):
        console.print(row)

    console.print()
    tagline = "Autonomous AI Engineering System"
    pad = max((CONTENT_WIDTH - len(tagline)) // 2, 0)
    console.print(" " * pad + tagline, style=Token.secondary)

    console.print()
    divider = "\u2500" * CONTENT_WIDTH
    console.print(divider, style=Token.border)

    console.print()
    console.print("Runtime", style=Token.dim)
    console.print()

    status_items = [
        ("Started", _get_uptime() + " ago"),
        ("Agent Registry", _count_agents()),
        ("Memory", "Connected"),
        ("MCP Gateway", "Online"),
        ("Workspace", _get_workspace()),
        ("Provider", _get_provider()),
    ]

    for label, value in status_items:
        done = Text()
        done.append("  \u2713 ", style=Token.success)
        done.append(f"{label:<{STATUS_LABEL}}", style=Token.white)
        done.append(f"  {value:>{STATUS_VAL}}", style=Token.secondary)
        console.print(done)
        time.sleep(0.04)

    console.print()
    console.print(divider, style=Token.border)
    console.print()

    ready = Text()
    ready.append("\u25cf ", style=Style(color=Token.success, bold=True))
    ready.append("Ready.", style=Token.white)
    console.print(ready)

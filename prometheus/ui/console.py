import sys

from rich.console import Console

from prometheus.ui.theme import Theme, detect_color_system

# Force UTF-8 on Windows so Rich can render Unicode symbols
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

theme = Theme.rich_theme()
color_system = detect_color_system()

console = Console(
    theme=theme,
    emoji=False,
    safe_box=True,
    no_color=False,
    log_time=False,
    color_system=color_system,
)

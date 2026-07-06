from rich.console import Console
from rich.theme import Theme

theme = Theme(
    {
        "success": "green",
        "error": "bold red",
        "warning": "yellow",
        "info": "cyan",
    }
)

console = Console(theme=theme, emoji=False, safe_box=True, no_color=False, log_time=False)

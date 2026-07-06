from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.registry import Command
from prometheus.ui.styles import Token


def HelpPanel(cmd: Command) -> Panel:
    rows: list[Text | str] = []

    if cmd.description:
        rows.append(Text(cmd.description, style="white"))
        rows.append("")

    usage = Text()
    usage.append(f"\n  prometheus {cmd.name}", style=f"bold {Token.command}")
    rows.append(Text("Usage", style=f"bold {Token.heading}"))
    rows.append(usage)
    rows.append("")

    if cmd.aliases:
        alias_text = Text()
        alias_text.append("  " + ", ".join(cmd.aliases), style=Token.secondary)
        rows.append(Text("Aliases", style=f"bold {Token.heading}"))
        rows.append(alias_text)
        rows.append("")

    if cmd.examples:
        rows.append(Text("Examples", style=f"bold {Token.heading}"))
        for ex in cmd.examples:
            rows.append(Text(f"  {ex}", style=Token.dim))
        rows.append("")

    if cmd.related:
        rows.append(Text("Related", style=f"bold {Token.heading}"))
        rows.append(Text("  " + ", ".join(cmd.related), style=Token.secondary))

    if cmd.deprecated_since:
        rows.append("")
        repl = f" \u2192 {cmd.replacement}" if cmd.replacement else ""
        rows.append(Text(f"  Deprecated since {cmd.deprecated_since}{repl}", style=Token.warning))

    if cmd.experimental:
        rows.append("")
        rows.append(Text("  Experimental — may change in future releases.", style=Token.warning))

    if cmd.implemented is False:
        rows.append("")
        rows.append(Text(f"  Coming in {cmd.since}.", style=Token.muted))

    inner = Table.grid(padding=(0, 0))
    for row in rows:
        inner.add_row(row)

    return Panel(
        inner,
        title=f"[bold {Token.command}]prometheus {cmd.name}[/]",
        border_style=Token.border,
    )

from __future__ import annotations

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from prometheus.registry import Command
from prometheus.ui.theme import Theme


def HelpPanel(cmd: Command) -> Panel:
    rows: list[Text | str] = []

    if cmd.description:
        rows.append(Text(cmd.description, style=str(Theme.body)))
        rows.append("")

    usage = Text()
    usage.append(f"\n  prometheus {cmd.name}", style=f"bold {Theme.command}")
    rows.append(Text("Usage", style=f"bold {Theme.heading}"))
    rows.append(usage)
    rows.append("")

    if cmd.aliases:
        alias_text = Text()
        alias_text.append("  " + ", ".join(cmd.aliases), style=str(Theme.secondary))
        rows.append(Text("Aliases", style=f"bold {Theme.heading}"))
        rows.append(alias_text)
        rows.append("")

    if cmd.examples:
        rows.append(Text("Examples", style=f"bold {Theme.heading}"))
        for ex in cmd.examples:
            rows.append(Text(f"  {ex}", style=str(Theme.muted)))
        rows.append("")

    if cmd.related:
        rows.append(Text("Related", style=f"bold {Theme.heading}"))
        rows.append(Text("  " + ", ".join(cmd.related), style=str(Theme.secondary)))

    if cmd.deprecated_since:
        rows.append("")
        repl = f" \u2192 {cmd.replacement}" if cmd.replacement else ""
        rows.append(
            Text(f"  Deprecated since {cmd.deprecated_since}{repl}", style=str(Theme.warning))
        )

    if cmd.experimental:
        rows.append("")
        rows.append(
            Text("  Experimental \u2014 may change in future releases.", style=str(Theme.warning))
        )

    if cmd.implemented is False:
        rows.append("")
        rows.append(Text(f"  Coming in {cmd.since}.", style=str(Theme.muted)))

    inner = Table.grid(padding=(0, 0))
    for row in rows:
        inner.add_row(row)

    return Panel(
        inner,
        title=f"[bold {Theme.command}]prometheus {cmd.name}[/]",
        border_style=str(Theme.border),
    )

"""Rich console output for Dissect agent stages — used by CLI mission mode."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.text import Text

from prometheus.ui.styles import Token


def show_dissect_progress(console: Console, message: str) -> None:
    t = Text("  [Dissect] ")
    t.stylize("bold red")
    t.append(message)
    console.print(t)


def show_dissect_crash_received(
    console: Console,
    job_id: str,
    exception_type: str,
    exception_message: str,
) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    t = Text("  [Dissect] Crash Analysis")
    t.stylize("bold red")
    console.print(t)
    console.print()
    console.print(f"  [bold]Exception[/]  {exception_type}")
    console.print(f"  [bold]Message[/]    {exception_message[:120]}")
    console.print()


def show_dissect_classification(
    console: Console,
    category: str,
    confidence: float,
    match_method: str,
    strategy: str,
) -> None:
    def line(label: str, value: Any) -> None:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        console.print(f"  [bold]{label}[/]  {v}")

    console.print("  [bold]Classification[/]")
    line("Category", category)
    line("Confidence", f"{confidence:.2f}")
    line("Match", match_method)
    line("Strategy", strategy)
    console.print()


def show_dissect_cascade_level(
    console: Console,
    level: int,
    level_name: str,
) -> None:
    console.print(f"  [bold]Cascade Level[/]  {level} ({level_name})")


def show_dissect_patch_applied(
    console: Console,
    lines_changed: int,
    diff: str,
) -> None:
    console.print(f"  [green]\u2713 Patch applied[/]  ({lines_changed} lines changed)")
    if diff:
        diff_lines = diff.split("\n")[:8]
        for dl in diff_lines:
            if dl.startswith("+"):
                console.print(f"    [green]{dl}[/]")
            elif dl.startswith("-"):
                console.print(f"    [red]{dl}[/]")
            else:
                console.print(f"    [dim]{dl}[/]")
        if len(diff_lines) > 8:
            console.print(f"    [dim]... ({len(diff.split(chr(10))) - 8} more lines)[/]")
    console.print()


def show_dissect_sandbox_start(console: Console) -> None:
    console.print("  [bold]Sandbox Test[/]  Running patched script in isolated container...")


def show_dissect_sandbox_result(console: Console, passed: bool, output: str = "") -> None:
    if passed:
        console.print("  [green]\u2713 Sandbox test PASSED[/]")
    else:
        console.print("  [red]\u2717 Sandbox test FAILED[/]")
        if output:
            lines = output.strip().split("\n")[:5]
            for l in lines:
                console.print(f"    [dim]{l[:120]}[/]")
            if len(output.strip().split("\n")) > 5:
                console.print("    [dim]...[/]")
    console.print()


def show_dissect_success(console: Console) -> None:
    t = Text("  [Dissect] Patch applied. Publishing RESUME_TRAINING...")
    t.stylize("bold green")
    console.print(t)
    console.print()


def show_dissect_summary(
    console: Console,
    job_id: str,
    category: str,
    cascade_level: int,
    lines_changed: int,
    confidence: float,
) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    t = Text("  [Dissect] Repair Summary")
    t.stylize("bold red")
    console.print(t)
    console.print()

    def line(label: str, value: Any) -> None:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        console.print(f"  [bold]{label}[/]  {v}")

    line("Category", category)
    line("Cascade Level", str(cascade_level))
    line("Lines Changed", str(lines_changed))
    line("Confidence", f"{confidence:.2f}")

    console.print()
    console.print("  [green]\u2713 Patch Applied[/]")
    console.print("  [green]\u2713 Sandbox Verified[/]")
    console.print("  [green]\u2713 Patch Log Written[/]")
    console.print("  [green]\u2713 RESUME_TRAINING[/]   Published")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def show_dissect_escalated(
    console: Console,
    job_id: str,
    reason: str,
) -> None:
    console.print()
    console.print(f"  [red]\u2717 Dissect could not repair job {job_id}[/]")
    console.print(f"  [{Token.dim}]Reason: {reason}[/]")
    console.print(f"  [{Token.secondary}]Job escalated for human review.[/]")
    console.print()


def show_dissect_terminating(console: Console) -> None:
    console.print("  [red]Exceeded patch budget. Publishing RESUME_TRAINING...[/]")


def show_dissect_healing(console: Console, patched_script_path: str) -> None:
    console.print(f"  [yellow]Training script patched at {patched_script_path}[/]")


def show_dissect_waiting_furnace(console: Console) -> None:
    console.print()
    console.print("  [bold yellow]Dissect complete. Relaunching Furnace trainer...[/]")
    console.print()

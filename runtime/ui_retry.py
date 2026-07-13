"""CLI rendering for retry orchestration. No business logic."""

from __future__ import annotations

from typing import Any

from runtime.models import RetryAttemptRecord


def show_retry_reason(
    console: Any,
    reason: str,
    metric_name: str,
    metric_value: float,
    threshold: float | None,
) -> None:
    console.print()
    console.print(f"  [bold yellow]Retry Reason[/]: {reason}")
    console.print(f"  Metric: {metric_name} = {metric_value:.4f}", end="")
    if threshold is not None:
        console.print(f"  |  Threshold: {threshold}")
    else:
        console.print()
    console.print()


def show_retry_started(
    console: Any,
    attempt: int,
    max_attempts: int,
    strategy: str | None = None,
) -> None:
    console.print()
    console.print("  [bold cyan]─" + "─" * 58 + "[/]")
    console.print(f"  [bold cyan]Starting Retry {attempt} of {max_attempts}...[/]")
    if strategy:
        console.print(f"  [cyan]Strategy: {strategy}[/]")
    console.print("  [bold cyan]─" + "─" * 58 + "[/]")
    console.print()


def show_retry_limit_reached(
    console: Any,
    attempt: int,
    max_attempts: int,
    metric_name: str,
    last_value: float,
    threshold: float | None,
) -> None:
    console.print()
    console.print(f"  [bold red]Retry {attempt} of {max_attempts} failed.[/]")
    console.print("  [bold red]Maximum retry attempts reached.[/]")
    console.print()
    console.print("  Mission failed to satisfy deployment requirements.")
    console.print(f"  Best {metric_name}: {last_value:.4f} " f"(threshold: {threshold or 'N/A'})")
    console.print()


def show_retry_complete(
    console: Any,
    attempt: int,
    metric_name: str,
    metric_value: float,
    decision: str,
) -> None:
    console.print()
    console.print(
        f"  [bold green]Retry {attempt} complete: "
        f"{metric_name}={metric_value:.4f} → {decision}[/]"
    )
    console.print()


def show_retry_history(
    console: Any,
    history: list[RetryAttemptRecord],
    architecture: str,
    best_metric: float,
    best_architecture: str,
) -> None:
    """Show a summary table of all retry attempts after the retry loop ends.

    Args:
        console: Rich console.
        history: List of RetryAttemptRecord from MissionState.retry_history.
        architecture: Current architecture.
        best_metric: Best metric value achieved.
        best_architecture: Architecture that achieved best metric.
    """
    if not history:
        return

    console.print()
    console.print("  [bold cyan]─" + "─" * 58 + "[/]")
    console.print("  [bold cyan]Retry History Summary[/]")
    console.print("  [bold cyan]─" + "─" * 58 + "[/]")

    for entry in history:
        decision_tag = {
            "PASS": "[green]PASS[/]",
            "RETRY": "[yellow]RETRY[/]",
            "FAIL": "[red]FAIL[/]",
        }.get(entry.decision, entry.decision)

        arch_actual = entry.architecture or architecture
        metric_str = (
            f"{entry.metric_name}={entry.metric_value:.4f}" if entry.metric_value else "no metric"
        )
        crash_info = f" ⚠ crash: {entry.failure_category}" if entry.failure_category else ""
        console.print(
            f"  Attempt {entry.attempt}: [{arch_actual}] "
            f"{metric_str} → {decision_tag}{crash_info}"
        )

    console.print(f"  Best: {best_metric:.4f} with [{best_architecture}]")
    console.print("  [bold cyan]─" + "─" * 58 + "[/]")
    console.print()

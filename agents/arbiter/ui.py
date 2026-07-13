"""CLI rendering for the Arbiter agent. No business logic, no file I/O."""

from rich.console import Console
from rich.table import Table

from agents.arbiter.models import DecisionResult, EvaluationResult, MissionConstraints


def show_start(console: Console) -> None:
    console.print()
    console.print("  [bold cyan]Arbiter[/] evaluating model...")
    console.print()


def show_loading(console: Console, message: str) -> None:
    console.print(f"    [dim]{message}...[/]")


def show_metrics(
    console: Console,
    result: EvaluationResult,
    constraints: MissionConstraints,
) -> None:
    console.print()
    console.print("  [bold cyan]Evaluation Results[/]")
    console.print(f"  [bold]{'─' * 56}[/]")

    table = Table(
        show_header=False,
        box=None,
        padding=(0, 2),
    )
    table.add_column("Metric", style="bold")
    table.add_column("Value")

    for name in ("auc_roc", "f1", "precision", "recall", "accuracy", "rmse", "mae", "r2"):
        if name in result.all_metrics:
            val = result.all_metrics[name]
            if isinstance(val, (int, float)):
                table.add_row(name.upper(), f"{val:.4f}")

    console.print(table)

    precision = result.all_metrics.get("precision")
    recall = result.all_metrics.get("recall")
    if precision is not None and recall is not None:
        console.print(
            f"  [dim]At this precision, roughly {int(round(precision * 100))}% of customers "
            f"flagged as high-risk will actually churn. At this recall, the model "
            f"identifies {int(round(recall * 100))}% of customers who will churn before "
            f"they leave.[/]"
        )

    console.print()
    console.print("  [bold]Threshold[/]")
    if constraints.has_threshold:
        op = constraints.operator
        thresh = constraints.threshold
        metric = constraints.metric.upper() if constraints.metric else "METRIC"
        console.print(f"    {metric} {op} {thresh:.4f}")
    else:
        console.print("    [dim]Not specified[/]")

    console.print()
    console.print("  [bold]Decision[/]")


def show_decision(
    console: Console,
    result: EvaluationResult,
    decision: DecisionResult,
    constraints: MissionConstraints,
) -> None:
    """Combined metrics + decision display."""
    show_metrics(console, result, constraints)
    _render_decision_line(console, decision)
    console.print(f"  [bold]{'─' * 56}[/]")
    console.print()


def _render_decision_line(
    console: Console,
    decision: DecisionResult,
) -> None:
    if decision.decision == "PASS":
        console.print(f"    [bold green]PASS[/] {decision.explanation}")
    elif decision.decision == "RETRY":
        console.print(f"    [bold yellow]RETRY[/] {decision.explanation}")
    else:
        console.print(f"    [bold red]FAIL[/] {decision.explanation}")


def show_pass(console: Console) -> None:
    console.print()
    console.print("  [bold green]✓ Mission approved.[/]")
    console.print()


def show_retry(console: Console) -> None:
    console.print()
    console.print("  [bold yellow]⟳ Retry recommended.[/]")
    console.print()


def show_failure(console: Console) -> None:
    console.print()
    console.print("  [bold red]✗ Model does not meet requirements.[/]")
    console.print()


def show_error(console: Console, message: str) -> None:
    console.print()
    console.print(f"  [bold red]Arbiter error:[/] {message}")
    console.print()


def show_checkpoint_missing(console: Console, path: str) -> None:
    console.print()
    console.print(f"  [bold red]Checkpoint not found:[/] {path}")
    console.print("  [dim]Evaluation cannot proceed.[/]")
    console.print()

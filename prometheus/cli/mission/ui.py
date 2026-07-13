from __future__ import annotations

from typing import Any
from runtime.paths import get_job_paths

from rich.console import Console

from prometheus.mission.models import ParsedMission, ValidationResult
from prometheus.ui.styles import Token


def show_mission_banner(console: Console) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    console.print("  [bold]Describe your machine learning problem[/bold]")
    console.print()
    console.print(f"  [{Token.dim}]Type your ML problem. Include dataset path and target.[/]")
    console.print(f"  [{Token.dim}]Press Enter twice (empty line) when done.[/]")
    console.print(f"  [{Token.dim}]Type 'cancel' to abort.[/]")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def build_first_prompt() -> str:
    return "> "


def build_next_prompt() -> str:
    return "  "


def show_cancelled(console: Console) -> None:
    console.print()
    console.print("  [yellow]Mission cancelled.[/]")


def show_empty_input_warning(console: Console) -> None:
    console.print("  [red]Mission description cannot be empty.[/]")


def show_rejected_input(console: Console, message: str) -> None:
    console.print(f"  [red]{message}[/]")


def show_parsed_summary(console: Console, parsed: ParsedMission) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    console.print(f"  [bold]Understood.[/]  [{Token.dim}]Here's what I'll do:[/]")
    console.print()

    console.print("  [bold]Dataset[/]")
    if parsed.dataset_path:
        status = "[green]\u2713 Found[/]" if parsed.dataset_exists else "[red]\u2717 Not found[/]"
        console.print(f"    {parsed.dataset_path}  {status}")
    else:
        console.print("    [dim]Not specified[/]")

    console.print("  [bold]Target[/]")
    if parsed.target_column:
        console.print(f"    {parsed.target_column}")
    else:
        console.print("    [dim]Not specified[/]")

    console.print("  [bold]Task[/]")
    if _is_inferred(parsed.original_prompt, "task", parsed.task_type):
        console.print(f"    {parsed.task_type.title()}  [{Token.dim}]inferred[/]")
    else:
        console.print(f"    {parsed.task_type.title()}")

    metric_display = (
        parsed.evaluation_metric.upper() if parsed.evaluation_metric else "Not specified"
    )
    console.print("  [bold]Metric[/]")
    if _is_inferred(parsed.original_prompt, "metric", parsed.evaluation_metric):
        console.print(f"    {metric_display}  [{Token.dim}](inferred)[/]")
    else:
        console.print(f"    {metric_display}")

    console.print("  [bold]Deployment[/]")
    if parsed.deployment_threshold is not None:
        console.print(
            f"    {parsed.evaluation_metric.upper() or 'Metric'} > {parsed.deployment_threshold}"
        )
    else:
        console.print("    [dim]Not specified[/]")

    if parsed.constraints:
        console.print("  [bold]Constraints[/]")
        for c in parsed.constraints:
            console.print(f"    \u2022 {c}")

    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def _is_inferred(original: str, field: str, value: str) -> bool:
    if not value:
        return True
    return value.lower() not in original.lower()


def show_waiting_message(console: Console, message: str) -> None:
    console.print(f"  [{Token.dim}]{message}...[/]")


def show_validation_result(console: Console, result: ValidationResult) -> None:
    if result.valid:
        console.print()
        console.print("  [green]\u2713 Mission validated.[/]")
    else:
        console.print()
        console.print("  [red]\u2717 Mission validation failed.[/]")
        for err in result.errors:
            console.print(f"  [red]\u2022 {err}[/]")

    if result.warnings:
        for w in result.warnings:
            console.print(f"  [yellow]\u2022 {w}[/]")
    console.print()


def show_parsing_error(console: Console) -> None:
    console.print()
    console.print("  [red]Unable to understand the mission.[/]")
    console.print(f"  [{Token.dim}]Please rewrite your description and try again.[/]")
    console.print()


def show_mission_job_id(console: Console, job_id: str) -> None:
    console.print()
    console.print("  [bold]Creating mission...[/]")
    console.print(f"  Mission ID: [bold cyan]{job_id}[/]")
    console.print()


def show_scout_progress(console: Console, message: str) -> None:
    from rich.text import Text

    t = Text("  [Scout] ")
    t.stylize("bold cyan")
    t.append(message)
    console.print(t)


def show_scout_summary(console: Console, brief: dict[str, Any], job_id: str) -> None:
    from rich.text import Text

    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    t = Text("  [Scout] Dataset Analysis")
    t.stylize("bold cyan")
    console.print(t)
    console.print()

    ds = brief.get("dataset", {})
    dq = brief.get("data_quality", {})
    imb = dq.get("class_imbalance_ratio")

    def line(label: str, value: Any) -> None:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        console.print(f"  [bold]{label}[/]  {v}")

    line("Rows", ds.get("num_rows", "?"))
    line("Columns", ds.get("num_columns", "?"))
    line("Dataset", brief.get("dataset", {}).get("file_path", "?"))
    line("Target", brief.get("target_column", "?"))
    line("Task", brief.get("task_type", "?").replace("_", " ").title())
    line("Modality", brief.get("modality", "?").title())
    console.print()

    if imb is not None and imb > 0:
        console.print("  [bold]Class Distribution[/]")
        maj_pct = f"{imb/(1+imb)*100:.0f}%"
        min_pct = f"{1/(1+imb)*100:.0f}%"
        console.print(f"    Majority  {maj_pct}  (ratio 1:{imb:.1f})")
        console.print(f"    Minority  {min_pct}")
        console.print()
        console.print("  [bold]Imbalance[/]  Detected")
        strat = brief.get("imbalance_strategy", "none")
        console.print(f"  [bold]Strategy[/]   {strat}")
        console.print()
    else:
        console.print("  [bold]Imbalance[/]  None")
        console.print()

    missing = dq.get("missing_value_rate", {})
    n_missing = sum(1 for v in missing.values() if float(v) > 0)
    console.print(f"  [bold]Missing Values[/]  {n_missing}")
    console.print()

    metric = brief.get("evaluation_metric", "?").upper()
    console.print(f"  [bold]Metric[/]    {metric}")
    console.print()

    console.print("  [green]\u2713 Mission Brief[/]        Written")
    console.print("  [green]\u2713 Redis[/]                Stored")
    console.print("  [green]\u2713 MISSION_BRIEF_READY[/]   Published")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def show_scout_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [red]\u2717 Scout failed for job {job_id}[/]")
    console.print(f"  [{Token.dim}]Reason: {reason}[/]")
    console.print(f"  [{Token.secondary}]Mission aborted.[/]")
    console.print()


def show_forge_progress(console: Console, message: str) -> None:
    from rich.text import Text

    t = Text("  [Forge] ")
    t.stylize("bold magenta")
    t.append(message)
    console.print(t)


def show_forge_summary(
    console: Console,
    job_id: str,
    result: dict[str, Any],
) -> None:
    from rich.text import Text

    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    t = Text("  [Forge] Architecture & Training Plan")
    t.stylize("bold magenta")
    console.print(t)
    console.print()

    brief = result.get("brief") or {}
    script_path = result.get("script_path", "?")
    search_space = result.get("search_space") or {}

    def line(label: str, value: Any) -> None:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        console.print(f"  [bold]{label}[/]  {v}")

    arch = brief.get("engineering_reasoning", {}).get("architecture", {})
    arch_name = brief.get("recommended_architecture_family") or arch.get("selected", "lightgbm")
    line("Architecture", arch_name.title())

    task = brief.get("task_type", "?").replace("_", " ").title()
    line("Task", task)

    modality = brief.get("modality", "?").title()
    line("Modality", modality)

    metric = brief.get("evaluation_metric", "?").upper()
    line("Metric", metric)

    line("Training Script", script_path)

    n_hp = len(search_space)
    line("Hyperparameters", f"{n_hp} dimensions")

    strat = brief.get("imbalance_strategy", "none")
    line("Imbalance Strategy", strat)

    console.print()
    console.print("  [green]\u2713 Training Script[/]   Generated")
    console.print("  [green]\u2713 Search Space[/]      Stored in Redis")
    console.print("  [green]\u2713 TRAINING_SCRIPT_READY[/]  Published")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def show_forge_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [red]\u2717 Forge failed for job {job_id}[/]")
    console.print(f"  [{Token.dim}]Reason: {reason}[/]")
    console.print(f"  [{Token.secondary}]Mission aborted.[/]")
    console.print()


def show_furnace_progress(console: Console, message: str) -> None:
    from rich.text import Text

    t = Text("  [Furnace] ")
    t.stylize("bold yellow")
    t.append(message)
    console.print(t)


def show_furnace_summary(
    console: Console,
    job_id: str,
    result: dict[str, Any],
) -> None:
    from rich.text import Text

    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    t = Text("  [Furnace] Training Summary")
    t.stylize("bold yellow")
    console.print(t)
    console.print()

    def line(label: str, value: Any) -> None:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        console.print(f"  [bold]{label}[/]  {v}")

    container_name = f"prometheus-train-{job_id}"
    line("Container", container_name)

    total_epochs = result.get("total_epochs", result.get("total_trials", "?"))
    line("Trials", str(total_epochs))

    metric_val = result.get("best_metric", 0)
    metric_name = result.get("metric_name", "metric").upper()
    line(f"Best {metric_name}", f"{metric_val:.4f}")

    training_time = result.get("training_time", 0)
    if training_time:
        if training_time > 60:
            mins = int(training_time // 60)
            secs = int(training_time % 60)
            line("Training Time", f"{mins}m {secs}s")
        else:
            line("Training Time", f"{training_time:.0f}s")

    checkpoint = result.get("checkpoint_path", str(get_job_paths(job_id).checkpoint_path))
    line("Checkpoint", checkpoint)

    console.print()
    console.print("  [green]\u2713 Checkpoint Saved[/]")
    console.print("  [green]\u2713 TRAINING_COMPLETE[/]   Published")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def show_furnace_error(
    console: Console, job_id: str, reason: str, wait_for_dissect: bool = True
) -> None:
    from rich.text import Text

    console.print()
    console.print(f"  [red]\u2717 Furnace training failed for job {job_id}[/]")
    t = Text(f"    Reason: {reason}")
    t.stylize("dim")
    console.print(t)
    if wait_for_dissect:
        console.print()
        t2 = Text("  [Furnace] Training failed. Waiting for Dissect...")
        t2.stylize("bold yellow")
        console.print(t2)
        console.print(f"  [{Token.dim}]Dissect will attempt to repair the training script.[/]")
    console.print()

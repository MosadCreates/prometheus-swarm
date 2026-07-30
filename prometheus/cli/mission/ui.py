from __future__ import annotations

import os
import sys
import time
from typing import Any
from runtime.paths import get_job_paths

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prometheus.mission.models import ParsedMission, ValidationResult
from prometheus.ui.theme import Theme

_LINE_GAP_MS = 110
_CHECK_FRAME_MS = 50
_COLLAPSE_GAP_MS = 100

_AGENT_VOICES: dict[str, dict[str, Any]] = {
    "Scout": {
        "color": Theme.agent_scout,
        "verb": "scouted",
        "title": "Dataset Intelligence Report",
        "glyph": "\u25cb",
    },
    "Forge": {
        "color": Theme.agent_forge,
        "verb": "forged",
        "title": "Architecture & Training Plan",
        "glyph": "\u25cb",
    },
    "Furnace": {
        "color": Theme.agent_furnace,
        "verb": "trained",
        "title": "Training Summary",
        "glyph": "\u25cb",
    },
    "Dissect": {
        "color": Theme.agent_dissect,
        "verb": "dissected",
        "title": "Error Diagnosis",
        "glyph": "\u25cb",
    },
    "Arbiter": {
        "color": Theme.agent_arbiter,
        "verb": "judged",
        "title": "Evaluation Verdict",
        "glyph": "\u25cb",
    },
    "Harbor": {
        "color": Theme.agent_harbor,
        "verb": "deployed",
        "title": "Deployment Control",
        "glyph": "\u25cb",
    },
}


def _agent_header(agent_name: str) -> tuple[Text, dict[str, Any]]:
    """Build a styled agent header + voice config as a tuple."""
    voice = _AGENT_VOICES.get(agent_name, _AGENT_VOICES["Scout"])
    t = Text(f"  [{agent_name}] ")
    t.stylize(f"bold {voice['color']}")
    return t, voice


def _summary_panel(title: str, color: str, content: str) -> Panel:
    return Panel(
        content,
        title=f"[bold {color}]{title}[/]",
        border_style=color,
        padding=(1, 2),
        subtitle_align="right",
    )


def show_mission_banner(console: Console) -> None:
    console.print()
    panel = Panel(
        "[bold]Describe your machine learning problem[/]\n\n"
        f"[{str(Theme.muted)}]Include dataset path and target column.[/]\n"
        f"[{str(Theme.muted)}]Press Enter twice (empty line) when done. Type 'cancel' to abort.[/]",
        title="[bold]New Mission[/]",
        border_style=str(Theme.border),
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def build_first_prompt() -> str:
    return "> "


def build_next_prompt() -> str:
    return "  "


def show_cancelled(console: Console) -> None:
    console.print()
    console.print(f"  [{Theme.warning}]Mission cancelled.[/]")


def show_empty_input_warning(console: Console) -> None:
    console.print(f"  [{Theme.error}]Mission description cannot be empty.[/]")


def show_rejected_input(console: Console, message: str) -> None:
    console.print(f"  [{Theme.error}]{message}[/]")


def show_parsed_summary(console: Console, parsed: ParsedMission) -> None:
    parts: list[str] = []

    def safe(value: Any) -> str:
        return str(value).replace("[", "\\[").replace("]", "\\]")

    ds_status = (
        f"[{str(Theme.success)}]\u2713 Found[/]"
        if parsed.dataset_exists
        else f"[{str(Theme.error)}]\u2717 Not found[/]"
    )
    ds_value = (
        f"{safe(parsed.dataset_path)}  {ds_status}"
        if parsed.dataset_path
        else f"[{str(Theme.muted)}]Not specified[/]"
    )
    parts.append(f"  [bold]Dataset[/]  {ds_value}")

    parts.append(
        f"  [bold]Target[/]  {safe(parsed.target_column) if parsed.target_column else f'[{str(Theme.muted)}]Not specified[/]'}"
    )

    task_hint = (
        f" [{str(Theme.muted)}]inferred[/]"
        if _is_inferred(parsed.original_prompt, "task", parsed.task_type)
        else ""
    )
    parts.append(f"  [bold]Task[/]  {parsed.task_type.replace('_', ' ').title()}{task_hint}")

    metric_val = parsed.evaluation_metric.upper() if parsed.evaluation_metric else "Not specified"
    metric_hint = (
        f" [{str(Theme.muted)}]inferred[/]"
        if _is_inferred(parsed.original_prompt, "metric", parsed.evaluation_metric)
        else ""
    )
    parts.append(f"  [bold]Metric[/]  {metric_val}{metric_hint}")

    if parsed.deployment_threshold is not None:
        parts.append(
            f"  [bold]Threshold[/]  {parsed.evaluation_metric.upper() or 'Metric'} > {parsed.deployment_threshold}"
        )
    else:
        parts.append(f"  [bold]Threshold[/]  [{str(Theme.muted)}]Not specified[/]")

    if parsed.constraints:
        for c in parsed.constraints:
            parts.append(f"  [{str(Theme.muted)}]\u2022 {safe(c)}[/]")

    console.print()
    console.print(
        Panel(
            "\n".join(parts),
            title="[bold]Mission Understanding[/]",
            border_style=str(Theme.border),
            padding=(1, 2),
        )
    )
    console.print()


def _is_inferred(original: str, field: str, value: str) -> bool:
    if not value:
        return True
    return value.lower() not in original.lower()


def show_waiting_message(console: Console, message: str) -> None:
    console.print(f"  [{Theme.muted}]{message}...[/]")


def show_validation_result(console: Console, result: ValidationResult) -> None:
    if result.valid:
        console.print(f"  [{str(Theme.success)}]\u2713  Mission validated.[/]")
    else:
        console.print(f"  [{str(Theme.error)}]\u2717  Mission validation failed.[/]")
        for err in result.errors:
            console.print(f"  [{str(Theme.error)}]\u2022  {err}[/]")

    if result.warnings:
        for w in result.warnings:
            console.print(f"  [{str(Theme.warning)}]\u2022  {w}[/]")
    console.print()


def show_parsing_error(console: Console) -> None:
    console.print()
    panel = Panel(
        f"[{str(Theme.error)}]\u2717  Unable to understand the mission.[/]\n"
        f"[{str(Theme.muted)}]Please rewrite your description and try again.[/]",
        title="[bold]Parse Error[/]",
        border_style=str(Theme.error),
        padding=(1, 2),
    )
    console.print(panel)
    console.print()


def show_mission_job_id(console: Console, job_id: str, slug: str = "") -> None:
    display_id = slug if slug else job_id
    console.print(f"\n  Mission created: [bold]{display_id}[/]\n")


def show_scout_progress(console: Console, message: str) -> None:
    t, _ = _agent_header("Scout")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_scout_summary(console: Console, brief: dict[str, Any], job_id: str) -> None:
    scout_color = str(Theme.agent_scout)
    success_color = str(Theme.success)
    muted_color = str(Theme.muted)

    ds = brief.get("dataset", {})
    dq = brief.get("data_quality", {})
    imb = dq.get("class_imbalance_ratio")

    def item(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"  [bold]{label}[/]  {v}"

    # ── Overview ──
    overview_lines: list[str] = [
        "",
        f"  [{muted_color}]\u2501 Overview[/]",
        item("Rows", ds.get("num_rows", "?")),
        item("Columns", ds.get("num_columns", "?")),
        item("Dataset", brief.get("dataset", {}).get("file_path", "?")),
        item("Target", brief.get("target_column", "?")),
        item("Task", brief.get("task_type", "?").replace("_", " ").title()),
        item("Modality", brief.get("modality", "?").title()),
    ]

    # ── Dataset Health ──
    health_lines: list[str] = [
        "",
        f"  [{muted_color}]\u2501 Dataset Health[/]",
    ]

    missing = dq.get("missing_value_rate", {})
    missing_cols = [f"{k} ({float(v)*100:.0f}%)" for k, v in missing.items() if float(v) > 0]
    health_lines.append(item("Missing", ", ".join(missing_cols) if missing_cols else "None"))

    if imb is not None and imb > 0:
        maj_pct = f"{imb/(1+imb)*100:.0f}%"
        min_pct = f"{1/(1+imb)*100:.0f}%"
        health_lines.append(
            item("Balance", f"Majority {maj_pct} / Minority {min_pct} (1:{imb:.1f})")
        )
    else:
        health_lines.append(item("Balance", "Balanced"))

    # ── Mission Strategy ──
    strategy_lines: list[str] = [
        "",
        f"  [{muted_color}]\u2501 Mission Strategy[/]",
        item("Metric", brief.get("evaluation_metric", "?").upper()),
        item("Approach", brief.get("imbalance_strategy", "none").replace("_", " ").title()),
    ]

    # ── Artifacts ──
    artifact_lines: list[str] = [
        "",
        f"  [{muted_color}]\u2501 Artifacts[/]",
        f"  [{success_color}]\u2713[/]  Mission Brief  \u2014  Written",
        f"  [{success_color}]\u2713[/]  Redis Key     \u2014  Stored",
        f"  [{success_color}]\u2713[/]  Event         \u2014  MISSION_BRIEF_READY",
        "",
    ]

    all_parts = overview_lines + health_lines + strategy_lines + artifact_lines
    content = "\n".join(all_parts)

    console.print()
    console.print(
        Panel(
            content,
            title=f"[bold {scout_color}]|{_AGENT_VOICES['Scout']['glyph']}| Scout \u2014 {_AGENT_VOICES['Scout']['title']}[/]",
            border_style=scout_color,
            padding=(1, 2),
        )
    )
    console.print()


def show_scout_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [{Theme.error}]\u2717 |{_AGENT_VOICES['Scout']['glyph']}| Scout failed[/]")
    console.print(f"  [{Theme.muted}]  Job: {job_id}[/]")
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    console.print(f"  [{Theme.secondary}]Mission aborted.[/]")
    console.print()


def show_forge_progress(console: Console, message: str) -> None:
    t, _ = _agent_header("Forge")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_forge_summary(
    console: Console,
    job_id: str,
    result: dict[str, Any],
) -> None:
    from rich.text import Text

    voice = _AGENT_VOICES["Forge"]
    brief = result.get("brief") or {}
    script_path = result.get("script_path", "?")
    search_space = result.get("search_space") or {}

    def line(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"[bold]{label}[/]  {v}"

    arch = brief.get("engineering_reasoning", {}).get("architecture", {})
    arch_name = brief.get("recommended_architecture_family") or arch.get("selected", "lightgbm")
    n_hp = len(search_space)

    parts: list[str] = [
        line("Architecture", arch_name.title()),
        line("Task", brief.get("task_type", "?").replace("_", " ").title()),
        line("Modality", brief.get("modality", "?").title()),
        line("Metric", brief.get("evaluation_metric", "?").upper()),
        line("Training Script", script_path),
        line("Hyperparameters", f"{n_hp} dimensions" if n_hp else "Default"),
        line("Imbalance Strategy", brief.get("imbalance_strategy", "none")),
        line("Status", "\u2713 Training Script Generated  \u2713 TRAINING_SCRIPT_READY Published"),
    ]

    panel = Panel(
        "\n".join(parts),
        title=f"[bold {voice['color']}]|{voice['glyph']}| Forge \u2014 {voice['title']}[/]",
        border_style=str(voice["color"]),
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def show_forge_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [{Theme.error}]\u2717 |{_AGENT_VOICES['Forge']['glyph']}| Forge failed[/]")
    console.print(f"  [{Theme.muted}]  Job: {job_id}[/]")
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    console.print(f"  [{Theme.secondary}]Mission aborted.[/]")
    console.print()


def show_furnace_progress(console: Console, message: str) -> None:
    t, _ = _agent_header("Furnace")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_furnace_summary(
    console: Console,
    job_id: str,
    result: dict[str, Any],
) -> None:
    from rich.text import Text

    voice = _AGENT_VOICES["Furnace"]

    def line(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"[bold]{label}[/]  {v}"

    total_epochs = result.get("total_epochs", result.get("total_trials", "?"))
    metric_val = result.get("best_metric", 0)
    metric_name = result.get("metric_name", "metric").upper()

    training_time = result.get("training_time", 0)
    time_str = ""
    if training_time:
        if training_time > 60:
            mins = int(training_time // 60)
            secs = int(training_time % 60)
            time_str = f"{mins}m {secs}s"
        else:
            time_str = f"{training_time:.0f}s"

    checkpoint = result.get("checkpoint_path", str(get_job_paths(job_id).checkpoint_path))

    parts: list[str] = [
        line("Container", f"prometheus-train-{job_id}"),
        line("Trials", str(total_epochs)),
        line(f"Best {metric_name}", f"{metric_val:.4f}"),
    ]
    if time_str:
        parts.append(line("Training Time", time_str))
    parts.append(line("Checkpoint", checkpoint))
    parts.append(line("Status", "\u2713 Checkpoint Saved  \u2713 TRAINING_COMPLETE Published"))

    panel = Panel(
        "\n".join(parts),
        title=f"[bold {voice['color']}]|{voice['glyph']}| Furnace \u2014 {voice['title']}[/]",
        border_style=str(voice["color"]),
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def show_furnace_error(
    console: Console, job_id: str, reason: str, wait_for_dissect: bool = True
) -> None:
    from rich.text import Text

    console.print()
    console.print(
        f"  [{Theme.error}]\u2717 |{_AGENT_VOICES['Furnace']['glyph']}| Furnace training failed[/]"
    )
    t = Text(f"  Job: {job_id}")
    t.stylize("dim")
    console.print(t)
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    if wait_for_dissect:
        console.print()
        t2 = Text("  |\u25c6| [Dissect] Training failed. Diagnosing...")
        t2.stylize(f"bold {Theme.info}")
        console.print(t2)
        console.print(f"  [{Theme.muted}]Dissect will attempt to repair the training script.[/]")
    console.print()


def show_dissect_progress(console: Console, message: str) -> None:
    t, _ = _agent_header("Dissect")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_dissect_summary(
    console: Console,
    job_id: str,
    patch_log_entry: dict[str, Any],
) -> None:
    from rich.text import Text

    voice = _AGENT_VOICES["Dissect"]

    def line(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"[bold]{label}[/]  {v}"

    parts: list[str] = []
    if patch_log_entry.get("error_taxonomy_category"):
        parts.append(line("Error Category", patch_log_entry["error_taxonomy_category"]))
    if patch_log_entry.get("repair_strategy_used"):
        parts.append(line("Repair Strategy", patch_log_entry["repair_strategy_used"]))
    if patch_log_entry.get("lines_changed") is not None:
        parts.append(line("Lines Changed", str(patch_log_entry["lines_changed"])))
    if patch_log_entry.get("sandbox_test_result"):
        test_result = patch_log_entry["sandbox_test_result"]
        icon = "\u2713" if test_result == "pass" else "\u2717"
        parts.append(line("Sandbox Test", f"{icon} {test_result}"))
    if patch_log_entry.get("patch_outcome"):
        outcome = patch_log_entry["patch_outcome"]
        color = (
            Theme.success
            if outcome == "success"
            else Theme.error if outcome == "escalated" else Theme.warning
        )
        parts.append(line("Outcome", f"[{color}]{outcome}[/]"))
    if patch_log_entry.get("confidence_score") is not None:
        parts.append(line("Confidence", f"{patch_log_entry['confidence_score']:.2f}"))

    status = "\u2713 RESUME_TRAINING Published"
    if patch_log_entry.get("patch_outcome") == "escalated":
        status = "\u26a0 ESCALATED"

    parts.append(line("Status", status))

    panel = Panel(
        "\n".join(parts),
        title=f"[bold {voice['color']}]|{voice['glyph']}| Dissect \u2014 {voice['title']}[/]",
        border_style=str(voice["color"]),
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def show_dissect_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(
        f"  [{Theme.error}]\u2717 |{_AGENT_VOICES['Dissect']['glyph']}| Dissect failed[/]"
    )
    console.print(f"  [{Theme.muted}]  Job: {job_id}[/]")
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    console.print()


def show_arbiter_progress(console: Console, message: str) -> None:
    t, _ = _agent_header("Arbiter")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_arbiter_summary(
    console: Console,
    job_id: str,
    result: dict[str, Any],
) -> None:
    from rich.text import Text

    voice = _AGENT_VOICES["Arbiter"]

    def line(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"[bold]{label}[/]  {v}"

    decision = result.get("decision", "unknown")
    metric_name = result.get("metric_name", "").upper()
    metric_val = result.get("metric_value", 0)
    threshold = result.get("threshold", 0)
    report_path = result.get("report_path", "?")

    decision_color = {
        "pass": Theme.success,
        "retry": Theme.warning,
        "escalate": Theme.error,
    }.get(decision, Theme.muted)
    decision_icon = {"pass": "\u2713", "retry": "\u26a0", "escalate": "\u2717"}.get(decision, "?")

    parts: list[str] = [
        line("Decision", f"[{decision_color}]{decision_icon} {decision.upper()}[/]"),
        line(f"Best {metric_name}", f"{metric_val:.4f}"),
        line("Threshold", f"{threshold:.4f}"),
        line("Report", report_path),
    ]

    panel = Panel(
        "\n".join(parts),
        title=f"[bold {voice['color']}]|{voice['glyph']}| Arbiter \u2014 {voice['title']}[/]",
        border_style=str(decision_color),
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def show_arbiter_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(
        f"  [{Theme.error}]\u2717 |{_AGENT_VOICES['Arbiter']['glyph']}| Arbiter evaluation failed[/]"
    )
    console.print(f"  [{Theme.muted}]  Job: {job_id}[/]")
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    console.print()


def show_analysis_preview(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
    is_tty: bool,
) -> None:
    """Beat 2 — Instant analysis preview shown immediately after submission.

    Prints 2 lines sequentially with a checking-then-resolve animation
    on each line. Falls back to plain sequential text for non-TTY.
    """
    if is_tty:
        _show_preview_animated(console, dataset_path, file_type, row_count)
    else:
        _show_preview_plain(console, dataset_path, file_type, row_count)


def _show_preview_animated(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
) -> None:
    """Animated preview with checking state per line."""
    lines: list[tuple[str, str]] = []

    type_label = file_type.upper() if file_type else "FILE"
    lines.append((f"{type_label} detected        ", dataset_path))

    if row_count is not None:
        fmt_rows = f"{row_count:,}"
        lines.append(("rows found           ", fmt_rows))

    for label, value in lines:
        _print_checking_line(console)
        time.sleep(_CHECK_FRAME_MS / 1000)
        _print_resolved_line(console, label, value)
        time.sleep(_LINE_GAP_MS / 1000)


def _print_checking_line(console: Console) -> None:
    t = Text("  checking...", style=str(Theme.disabled))
    console.print(t, end="\r")


def _print_resolved_line(
    console: Console,
    label: str,
    value: str,
) -> None:
    t = Text()
    t.append("  ")
    t.append("\u2713 ", style=str(Theme.success))
    t.append(label, style=str(Theme.muted))
    t.append(value, style=str(Theme.body))
    console.print(t)


def _show_preview_plain(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
) -> None:
    """Non-animated preview for non-TTY / piped."""
    kw = {"markup": False, "highlight": False, "emoji": False}
    type_label = file_type.upper() if file_type else "FILE"
    console.print(f"  OK {type_label} detected        {dataset_path}", **kw)
    if row_count is not None:
        fmt_rows = f"{row_count:,}"
        console.print(f"  OK {fmt_rows} rows found", **kw)


def show_docked_badge(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
    is_tty: bool,
) -> None:
    """Beat 3 — Collapse the preview block into a compact docked badge.

    In TTY mode, plays a 3-frame collapse animation (<500ms total) using
    ANSI escape sequences. Falls back to plain badge for non-TTY.
    """
    if is_tty:
        _show_badge_animated(console, dataset_path, file_type, row_count)
    else:
        _show_badge_plain(console, dataset_path, file_type, row_count)


def _show_badge_animated(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
) -> None:
    """Collapse animation: 3 frames shrinking to a one-line badge."""
    type_upper = file_type.upper() if file_type else "FILE"
    sys.stdout.flush()

    # Frame 1: brief pause showing existing preview
    time.sleep(_COLLAPSE_GAP_MS / 1000)

    if row_count is not None:
        # 2 preview lines → Frame 2: merged + Frame 3: badge
        fmt = f"{row_count:,}"
        merged = f"  \u2713 {type_upper}  \u2713 {fmt} rows      {dataset_path}"

        # Frame 2: go up 2, clear display, print merged line
        sys.stdout.write("\033[2A\033[J")
        sys.stdout.flush()
        t2 = Text(merged, style=str(Theme.muted))
        console.print(t2)
        time.sleep(_COLLAPSE_GAP_MS / 1000)

        # Frame 3: go up 1 from merged, clear, print badge
        sys.stdout.write("\033[F\033[K")
    else:
        # 1 preview line → Frame 2: skip, go straight to badge
        sys.stdout.write("\033[F\033[K")

    sys.stdout.flush()
    t3 = Text()
    t3.append("[file] ", style=str(Theme.muted))
    t3.append(dataset_path, style=str(Theme.body))
    console.print(t3)
    sys.stdout.flush()


def _show_badge_plain(
    console: Console,
    dataset_path: str,
    file_type: str,
    row_count: int | None,
) -> None:
    """Non-animated badge for non-TTY / piped."""
    kw = {"markup": False, "highlight": False, "emoji": False}
    console.print(f"  [file] {dataset_path}", **kw)
    console.print(**kw)

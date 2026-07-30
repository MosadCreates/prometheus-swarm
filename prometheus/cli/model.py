from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import click

from prometheus.ui.renderers import renderer_from_ctx
from prometheus.utils.exit_codes import ExitCode


@click.group(
    name="model",
    context_settings=dict(help_option_names=["--help", "-h"]),
)
def model():
    """Manage trained models (list, export, inspect)."""


def _is_model_mission(dir_path: Path) -> bool:
    """Check if a directory contains a trained model (has eval report)."""
    mission_id = dir_path.name
    candidates = [
        dir_path / f"eval_report_{mission_id}.json",
        dir_path / "evaluation_report.json",
    ]
    return any(c.exists() for c in candidates)


def _load_eval_data(mission_id: str) -> dict | None:
    """Load eval report data from either format."""
    outputs_dir = Path("outputs") / mission_id
    path_a = outputs_dir / f"eval_report_{mission_id}.json"
    path_b = outputs_dir / "evaluation_report.json"

    for p in [path_a, path_b]:
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
    return None


def _load_brief(mission_id: str) -> dict:
    """Try to load mission brief for context."""
    try:
        from prometheus.ui.cockpit.trace_replay import find_brief_path

        bp = find_brief_path(mission_id)
        if bp:
            return json.loads(Path(bp).read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _find_checkpoints(mission_id: str) -> list[Path]:
    """Find checkpoint files for a mission."""
    ckpt_dir = Path("outputs") / mission_id / "checkpoints"
    if not ckpt_dir.exists():
        return []
    return sorted(ckpt_dir.iterdir())


@model.command(name="list")
@click.option("--limit", "-n", default=None, type=int, help="Max models to show")
@click.option(
    "--status", default=None, type=str, help="Filter by decision status (pass, retry, escalate)"
)
@click.option("--mission", "-m", default=None, type=str, help="Filter by mission ID (prefix match)")
@click.pass_context
def model_list(
    ctx: click.Context, limit: int | None, status: str | None, mission: str | None
) -> ExitCode:
    """List all trained models found in outputs/."""
    renderer = renderer_from_ctx(ctx)
    outputs_dir = Path("outputs")
    if not outputs_dir.exists():
        renderer.empty("No outputs found", hint="Train a model first with a mission.")
        return ExitCode.SUCCESS

    rows: list[list[str]] = []
    for child in sorted(outputs_dir.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        if not _is_model_mission(child):
            continue

        mission_id = child.name
        if mission and not mission_id.startswith(mission):
            continue

        eval_data = _load_eval_data(mission_id)

        if eval_data is None:
            continue

        decision = (eval_data.get("decision") or "").lower()
        if status and status.lower() != decision:
            continue

        metrics = eval_data.get("metrics") or eval_data.get("all_metrics") or {}
        primary_metric = eval_data.get("primary_metric") or eval_data.get("metric") or ""
        primary_value = eval_data.get("primary_metric_value") or eval_data.get("metric_value") or ""

        brief = _load_brief(mission_id)
        problem = brief.get("problem_description", "")[:48]

        timestamp = eval_data.get("timestamp") or eval_data.get("created_at", "")
        if timestamp:
            timestamp = timestamp[:19] if len(timestamp) > 19 else timestamp

        checkpoints = _find_checkpoints(mission_id)
        ckpt_str = str(len(checkpoints)) if checkpoints else ""

        rows.append(
            [
                mission_id[:24],
                problem,
                primary_metric,
                str(primary_value)[:8] if primary_value else "",
                decision.upper(),
                ckpt_str,
                timestamp[:16] if timestamp else "",
            ]
        )

    if limit:
        rows = rows[:limit]

    if not rows:
        if status:
            renderer.empty(
                f"No models found with status '{status}'.", hint="prometheus mission list"
            )
        else:
            renderer.empty("No trained models found.", hint="prometheus mission list")
        return ExitCode.SUCCESS

    headers = ["Mission ID", "Problem", "Metric", "Value", "Status", "CKPTs", "Date"]
    col_widths = [max(len(str(r[i])) for r in rows + [headers]) for i in range(len(headers))]
    fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)

    click.echo(fmt.format(*headers))
    click.echo("  " + "-" * (sum(col_widths) + 2 * (len(headers) - 1)))
    for r in rows:
        click.echo(fmt.format(*r))

    click.echo(f"  [dim]{len(rows)} model(s)[/dim]")
    return ExitCode.SUCCESS


@model.command(name="inspect")
@click.argument("mission_id")
@click.pass_context
def model_inspect(ctx: click.Context, mission_id: str) -> ExitCode:
    """Show model metadata, metrics, and evaluation results."""
    renderer = renderer_from_ctx(ctx)
    outputs_dir = Path("outputs") / mission_id
    if not outputs_dir.exists():
        renderer.error(f"No data found for mission '{mission_id}'", hint="prometheus model list")
        return ExitCode.ERROR_NOT_FOUND

    eval_data = _load_eval_data(mission_id)
    brief = _load_brief(mission_id)
    checkpoints = _find_checkpoints(mission_id)

    click.echo(f"Model: {mission_id[:24]}")
    click.echo("")

    if brief.get("problem_description"):
        click.echo(f"  Problem: {brief['problem_description'][:80]}")
    if brief.get("task_type"):
        click.echo(f"  Task: {brief['task_type']}  |  Modality: {brief.get('modality', '?')}")
    ds = brief.get("dataset", {})
    if ds:
        click.echo(f"  Dataset: {ds.get('file_path', '?')} ({ds.get('num_rows', '?')} rows)")
    click.echo("")

    if eval_data:
        decision = eval_data.get("decision", "?").upper()
        click.echo(f"  Decision: {decision}")
        click.echo(f"  Reason: {eval_data.get('reason', '')[:120]}")

        primary = eval_data.get("primary_metric") or eval_data.get("metric", "")
        primary_val = eval_data.get("primary_metric_value") or eval_data.get("metric_value", "")
        if primary:
            click.echo(f"  Primary: {primary} = {primary_val}")

        metrics = eval_data.get("metrics") or eval_data.get("all_metrics") or {}
        if metrics:
            click.echo("")
            click.echo("  All Metrics:")
            for k, v in metrics.items():
                click.echo(f"    {k}: {v}")

        crash_count = eval_data.get("crash_count", 0)
        if crash_count:
            click.echo("")
            click.echo(f"  Crashes during training: {crash_count}")
    else:
        click.echo("  (no evaluation report found)")
        click.echo(f"  Checkpoint files: {len(checkpoints)}")

    if checkpoints:
        click.echo("")
        click.echo("  Checkpoints:")
        total_size = 0
        for ckpt in checkpoints:
            size = ckpt.stat().st_size
            total_size += size
            click.echo(f"    {ckpt.name} ({_fmt_size(size)})")
        click.echo(f"  Total: {len(checkpoints)} file(s), {_fmt_size(total_size)}")

    timestamp = eval_data.get("timestamp") or eval_data.get("created_at", "") if eval_data else ""
    if timestamp:
        click.echo(f"  Evaluated: {timestamp[:19]}")

    return ExitCode.SUCCESS


# register show as alias for inspect via ctx.invoke
@model.command(name="show")
@click.argument("mission_id")
@click.pass_context
def _model_show(ctx: click.Context, mission_id: str) -> None:
    """Show model metadata, metrics, and evaluation results (alias for inspect)."""
    ctx.invoke(model_inspect, mission_id=mission_id)


@model.command(name="export")
@click.argument("mission_id")
@click.option(
    "--format",
    "output_format",
    default="onnx",
    type=click.Choice(["onnx", "pickle"]),
    help="Export format (default: onnx)",
)
@click.option(
    "--to", default=None, help="Output path (default: outputs/{mission_id}/model.{format})"
)
@click.pass_context
def model_export(
    ctx: click.Context, mission_id: str, output_format: str, to: str | None
) -> ExitCode:
    """Export a trained model to ONNX or pickle format."""
    renderer = renderer_from_ctx(ctx)
    checkpoints = _find_checkpoints(mission_id)
    if not checkpoints:
        renderer.error(
            f"No checkpoints found for mission '{mission_id}'", hint="Train the model first"
        )
        return ExitCode.ERROR_NOT_FOUND

    best_ckpt = next((c for c in checkpoints if c.name == "best.ckpt"), checkpoints[0])

    if to:
        out_path = Path(to)
    else:
        ext = "onnx" if output_format == "onnx" else "pkl"
        out_path = Path("outputs") / mission_id / f"model.{ext}"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    if output_format == "onnx":
        return _export_onnx(renderer, mission_id, best_ckpt, out_path)
    else:
        return _export_pickle(renderer, best_ckpt, out_path)


def _export_onnx(renderer: Any, mission_id: str, ckpt_path: Path, out_path: Path) -> ExitCode:
    """Export checkpoint to ONNX using onnxmltools."""
    try:
        import onnxmltools
    except ImportError:
        renderer.error("onnxmltools not installed.", hint="pip install onnxmltools")
        return ExitCode.ERROR

    try:
        import joblib

        model = joblib.load(ckpt_path)
    except Exception as exc:
        renderer.error(f"Could not load checkpoint {ckpt_path}: {exc}")
        return ExitCode.ERROR

    try:
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType

        initial_type = [("float_input", FloatTensorType([None, "auto"]))]
        onnx_model = convert_sklearn(model, initial_types=initial_type)
        with open(out_path, "wb") as f:
            f.write(onnx_model.SerializeToString())
    except Exception as exc:
        renderer.error(f"ONNX conversion failed: {exc}", hint="Falling back to pickle export.")
        return _export_pickle(renderer, ckpt_path, out_path.with_suffix(".pkl"))

    click.echo(f"Model exported to ONNX: {out_path}")
    click.echo(f"  Size: {_fmt_size(out_path.stat().st_size)}")
    return ExitCode.SUCCESS


def _export_pickle(renderer: Any, ckpt_path: Path, out_path: Path) -> ExitCode:
    """Copy checkpoint file as pickle export."""
    import shutil

    try:
        shutil.copy2(ckpt_path, out_path)
    except Exception as exc:
        renderer.error(f"Could not copy checkpoint: {exc}")
        return ExitCode.ERROR

    click.echo(f"Model exported to pickle: {out_path}")
    click.echo(f"  Size: {_fmt_size(out_path.stat().st_size)}")
    return ExitCode.SUCCESS


def _fmt_size(size_bytes: int) -> str:
    """Format byte size as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f}{unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f}TB"

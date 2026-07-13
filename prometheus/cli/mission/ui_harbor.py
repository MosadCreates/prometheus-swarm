"""Harbor UI — deployment progress and mission completion summary."""

from __future__ import annotations

import json
import os
import platform
from typing import Any

import pandas as pd
from rich.console import Console

from prometheus.ui.styles import Token


def build_sample_payload(job_id: str, dataset_path: str) -> dict:
    """Build a realistic /predict payload using the model's actual feature schema."""
    config_path = f"outputs/{job_id}/serving/deploy_config.json"
    if not os.path.exists(config_path):
        alt = f"outputs/{job_id}/serving_config.json"
        if os.path.exists(alt):
            config_path = alt
        if not os.path.exists(config_path):
            return {}

    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    feature_names = config.get("feature_names") or []
    numeric_cols = set(config.get("numeric_cols") or [])

    if not feature_names:
        return {}

    sample_row: dict[str, Any] = {}
    try:
        df = pd.read_csv(dataset_path, nrows=50)
        candidates = df[feature_names].dropna()
        if len(candidates) > 0:
            row = candidates.iloc[0]
            for col in feature_names:
                val = row[col]
                sample_row[col] = float(val) if col in numeric_cols else str(val)
    except Exception:
        pass

    if not sample_row:
        for col in feature_names:
            sample_row[col] = 0.0 if col in numeric_cols else "example"

    return sample_row


def format_test_command(endpoint_url: str, sample_payload: dict) -> str:
    """Generate copy-paste-ready test commands for the user's platform."""
    payload_json = json.dumps(sample_payload)
    url = f"{endpoint_url}/predict"
    lines: list[str] = []
    if platform.system() == "Windows":
        lines.append("  PowerShell:")
        lines.append(
            f'    Invoke-RestMethod -Uri "{url}" -Method Post '
            f"-ContentType \"application/json\" -Body '{payload_json}'"
        )
        lines.append("")
        lines.append("  If you have curl.exe installed:")
        escaped = payload_json.replace('"', '\\"')
        lines.append(
            f"    curl.exe -X POST {url} " f'-H "Content-Type: application/json" -d "{escaped}"'
        )
    else:
        lines.append(
            f"  curl -X POST {url} \\\n"
            f'    -H "Content-Type: application/json" \\\n'
            f"    -d '{payload_json}'"
        )
    return "\n".join(lines)


def show_harbor_progress(console: Console, message: str) -> None:
    from rich.text import Text

    t = Text("  [Harbor] ")
    t.stylize("bold cyan")
    t.append(message)
    console.print(t)


def show_harbor_summary(
    console: Console,
    job_id: str,
    deploy_config: dict[str, Any],
) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()
    console.print("  [bold cyan]Harbor Deployment Complete[/]")
    console.print()

    model_format = deploy_config.get("model_format", "onnx")
    endpoint_url: str | None = deploy_config.get("endpoint_url")
    status = (
        "[green]\u2714[/] Healthy" if deploy_config.get("healthy") else "[yellow]Pending check[/]"
    )

    console.print(f"  [bold]Format:[/]      {model_format.upper()}")
    if endpoint_url:
        console.print(f"  [bold]Endpoint:[/]    {endpoint_url}")
    console.print(f"  [bold]Health:[/]      {status}")

    if deploy_config.get("container_name"):
        console.print(f"  [bold]Container:[/]  {deploy_config['container_name']}")
    if deploy_config.get("model_path"):
        console.print(f"  [bold]Model Path:[/]  {deploy_config['model_path']}")

    console.print()
    console.print("  [green]\u2713 Model Serialized[/]")
    console.print("  [green]\u2713 FastAPI App Generated[/]")
    console.print("  [green]\u2713 Docker Image Built[/]")
    console.print("  [green]\u2713 Container Deployed[/]")
    console.print("  [green]\u2713 ENDPOINT_LIVE Published[/]")
    console.print()
    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()


def show_harbor_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [red]\u2717 Harbor deployment failed for job {job_id}[/]")
    console.print(f"  [{Token.dim}]Reason: {reason}[/]")
    console.print()


def show_mission_summary(
    console: Console,
    job_id: str,
    brief: dict[str, Any] | None,
    result: dict[str, Any],
    deploy_config: dict[str, Any] | None = None,
    api_cost_summary: dict[str, Any] | None = None,
) -> None:
    width = 70
    sep = "\u2500" * width
    console.print()
    console.print(f"  [{Token.heading}]{'=' * width}[/]")
    console.print("  [bold]MISSION SUMMARY[/]".center(width + 4))
    console.print(f"  [{Token.heading}]{'=' * width}[/]")
    console.print()

    status = "[green]\u2714 SUCCESS[/]" if deploy_config else "[yellow]\u26a0 RETRY NEEDED[/]"
    console.print(f"  [bold]Status:[/]      {status}")

    arch = brief.get("recommended_architecture_family", "lightgbm") if brief else "lightgbm"
    optuna = brief and brief.get("optuna_trials", 30) or 30
    console.print(f"  [bold]Model:[/]       {arch.title()} ({optuna} Optuna trials)")

    metric_name = result.get("metric_name", "AUC-ROC").upper().replace("_", "-")
    metric_val = result.get("metric_value", 0.0)
    console.print(f"  [bold]{metric_name}:[/]     {metric_val:.4f}")

    if deploy_config:
        endpoint_url: str | None = deploy_config.get("endpoint_url")
        if endpoint_url:
            console.print(f"  [bold]Endpoint:[/]    {endpoint_url}")

    duration = result.get("duration_seconds", 0)
    if duration:
        if duration > 60:
            mins = int(duration // 60)
            secs = int(duration % 60)
            console.print(f"  [bold]Duration:[/]    {mins}m {secs}s")
        else:
            console.print(f"  [bold]Duration:[/]    {duration:.0f}s")

    if api_cost_summary:
        cost = api_cost_summary.get("total_cost_usd", 0)
        console.print(f"  [bold]API Cost:[/]    ${cost:.2f}")

    if deploy_config:
        endpoint_url = deploy_config.get("endpoint_url")
        if endpoint_url:
            console.print()
            console.print(f"  [{Token.border}]{sep}[/]")
            console.print()
            dataset_path = brief.get("dataset", {}).get("file_path") if brief else None
            sample_payload: dict[str, Any] = {}
            if job_id and dataset_path:
                sample_payload = build_sample_payload(job_id, dataset_path)
            if not sample_payload:
                feature_names = deploy_config.get("feature_names", [])
                numeric_cols = set(deploy_config.get("numeric_cols", []))
                for col in feature_names:
                    sample_payload[col] = 0.0 if col in numeric_cols else "example"
            test_cmd = format_test_command(endpoint_url, sample_payload)
            console.print("  [bold]Test your endpoint:[/]")
            for line in test_cmd.split("\n"):
                if line.strip():
                    console.print(f"  [{Token.command}]{line}[/]")
                else:
                    console.print()
            console.print()

    console.print(f"  [{Token.border}]{sep}[/]")
    console.print()

    if not deploy_config:
        console.print("  [yellow]No endpoint deployed — mission requires retry or escalation.[/]")
        console.print()


async def get_api_cost_summary_from_redis(redis_client: Any, job_id: str) -> dict[str, Any] | None:
    try:
        raw = await redis_client.get(f"job:{job_id}:api_cost_summary")
        if raw:
            return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass
    return None

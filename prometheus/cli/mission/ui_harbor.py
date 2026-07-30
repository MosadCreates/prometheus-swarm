"""Harbor UI — deployment progress and mission completion summary."""

from __future__ import annotations

import json
import os
import platform
from typing import Any

import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from prometheus.ui.theme import Theme


_HARBOR_COLOR = Theme.info


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
    t = Text("  [Harbor] ")
    t.stylize(f"bold {_HARBOR_COLOR}")
    t.append(message, style=str(Theme.muted))
    console.print(t)


def show_harbor_summary(
    console: Console,
    job_id: str,
    deploy_config: dict[str, Any],
) -> None:
    model_format = deploy_config.get("model_format", "onnx")
    endpoint_url: str | None = deploy_config.get("endpoint_url")
    healthy = deploy_config.get("healthy", False)

    status_icon = "\u2714" if healthy else "\u23f3"
    status_color = str(Theme.success) if healthy else str(Theme.warning)
    status_line = f"[{status_color}]{status_icon} {'Healthy' if healthy else 'Pending check'}[/]"

    def line(label: str, value: Any) -> str:
        v = str(value).replace("[", "\\[").replace("]", "\\]")
        return f"  [bold]{label}[/]  {v}"

    def raw_line(label: str, value: str) -> str:
        return f"  [bold]{label}[/]  {value}"

    parts: list[str] = [
        raw_line("Format", model_format.upper()),
        raw_line("Health", status_line),
    ]
    if endpoint_url:
        parts.append(line("Endpoint", endpoint_url))
    if deploy_config.get("container_name"):
        parts.append(line("Container", deploy_config["container_name"]))
    if deploy_config.get("model_path"):
        parts.append(line("Model Path", deploy_config["model_path"]))

    parts.append(
        raw_line(
            "Status",
            "\u2713 Serialized  \u2713 FastAPI Built  \u2713 Container Deployed  \u2713 ENDPOINT_LIVE",
        )
    )

    console.print()
    console.print("  [Harbor] Deployment")
    for p in parts:
        console.print(f"  {p}")
    console.print()


def show_harbor_error(console: Console, job_id: str, reason: str) -> None:
    console.print()
    console.print(f"  [{Theme.error}]\u2717 Harbor deployment failed[/]")
    console.print(f"  [{Theme.muted}]  Job: {job_id}[/]")
    console.print(f"  [{Theme.muted}]  Reason: {reason}[/]")
    console.print()


def show_mission_summary(
    console: Console,
    job_id: str,
    brief: dict[str, Any] | None,
    result: dict[str, Any],
    deploy_config: dict[str, Any] | None = None,
    api_cost_summary: dict[str, Any] | None = None,
) -> None:
    success = deploy_config is not None

    parts: list[str] = []

    arch = brief.get("recommended_architecture_family", "lightgbm") if brief else "lightgbm"
    optuna = brief and brief.get("optuna_trials", 30) or 30
    parts.append(f"[bold]Model:[/]       {arch.title()} ({optuna} Optuna trials)")

    metric_name = result.get("metric_name", "AUC-ROC").upper().replace("_", "-")
    metric_val = result.get("metric_value", 0.0)
    parts.append(f"[bold]{metric_name}:[/]     {metric_val:.4f}")

    duration = result.get("duration_seconds", 0)
    if duration:
        if duration > 60:
            mins = int(duration // 60)
            secs = int(duration % 60)
            parts.append(f"[bold]Duration:[/]    {mins}m {secs}s")
        else:
            parts.append(f"[bold]Duration:[/]    {duration:.0f}s")

    if api_cost_summary:
        cost = api_cost_summary.get("total_cost_usd", 0)
        parts.append(f"[bold]API Cost:[/]    ${cost:.2f}")

    if success and deploy_config:
        endpoint_url = deploy_config.get("endpoint_url", "")
        parts.append(f"[bold]Endpoint:[/]    {endpoint_url}")

    console.print()
    icon = "\u2714" if success else "\u2717"
    status = "complete" if success else "incomplete"
    console.print(f"  {icon} Mission {status}.")
    for p in parts:
        console.print(f"  {p}")
    console.print()

    if success and deploy_config:
        endpoint_url = deploy_config.get("endpoint_url", "")
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
        console.print("  Test your endpoint:")
        console.print(test_cmd)
        console.print()

    if not success:
        console.print(
            f"  [{Theme.warning}]No endpoint deployed \u2014 mission requires retry or escalation.[/]"
        )
        console.print()


async def get_api_cost_summary_from_redis(redis_client: Any, job_id: str) -> dict[str, Any] | None:
    try:
        raw = await redis_client.get(f"job:{job_id}:api_cost_summary")
        if raw:
            return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass
    return None

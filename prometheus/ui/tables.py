from rich.panel import Panel
from rich.table import Table

from prometheus.ui.icons import CHECK, CROSS
from prometheus.ui.theme import Theme


def job_list_table(jobs: list[dict]) -> Table:
    table = Table(title="Jobs", border_style=str(Theme.border))
    table.add_column("Job ID")
    table.add_column("Status")
    table.add_column("Agent")
    table.add_column("Crashes")
    for j in jobs:
        table.add_row(
            j["job_id"][:8], j["status"], j.get("current_agent", ""), str(j["crash_count"])
        )
    return table


def deploy_list_table(containers: list[dict]) -> Table:
    table = Table(title="Active Deployments", border_style=str(Theme.border))
    table.add_column("Job ID")
    table.add_column("Port")
    table.add_column("Health")
    table.add_column("Status")
    table.add_column("Image")
    table.add_column("Container")
    for c in containers:
        port_str = str(c.get("host_port") or "?")
        health_str = c.get("health", "?")
        if health_str == "healthy":
            health_display = f"[{Theme.success}]{CHECK}[/] healthy[/]"
        elif health_str in ("unreachable", "n/a"):
            health_display = f"[{Theme.error}]{CROSS} {health_str}[/]"
        else:
            health_display = f"[{Theme.warning}]{health_str}[/]"
        table.add_row(
            c.get("job_id", "?"),
            port_str,
            health_display,
            c.get("status", "?"),
            c.get("image", "?"),
            c.get("name", "?"),
        )
    return table


def config_check_table(results: list[dict]) -> Table:
    table = Table(title="Prerequisite Check", border_style=str(Theme.border))
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")
    for r in results:
        if r["ok"]:
            icon = f"[{Theme.success}]{CHECK} PASS[/]"
        else:
            icon = f"[{Theme.error}]{CROSS} FAIL[/]"
        table.add_row(r["name"], icon, r["detail"])
    return table


def job_result_panel(result: dict) -> Panel:
    lines = []
    status = result.get("status", "?")
    if status == "complete":
        lines.append(f"[{Theme.success}]Pipeline complete[/]")
    elif status in ("escalated", "retry_needed"):
        lines.append(f"[{Theme.warning}]Pipeline finished: {status}[/]")
    else:
        lines.append(f"Status: {status}")

    if "decision" in result:
        lines.append(f"Decision: {result['decision']} \u2014 {result.get('reason', '')}")
    if result.get("metrics"):
        lines.append("Metrics:")
        for k, v in result["metrics"].items():
            if isinstance(v, (int, float)):
                lines.append(f"  {k}: {v:.4f}")
            else:
                lines.append(f"  {k}: {v}")
    if result.get("checkpoint_path"):
        lines.append(f"Checkpoint: {result['checkpoint_path']}")
    if result.get("endpoint_url"):
        lines.append(f"Endpoint: [{Theme.info}]{result['endpoint_url']}[/]")
        lines.append(f"  POST {result['endpoint_url']}/predict \u2014 send JSON instances")
        lines.append(f"  GET  {result['endpoint_url']}/health")
    return Panel(
        "\n".join(lines),
        title=f"Job {result.get('job_id', '')[:8]}",
        border_style=str(Theme.border),
    )

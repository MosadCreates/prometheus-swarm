from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.style import Style
from rich.text import Text

from prometheus.ui.theme import Theme


@dataclass
class MissionSummaryCard:
    mission_id: str = ""
    problem_description: str = ""
    dataset_name: str = ""
    num_rows: int = 0
    num_features: int = 0
    task_type: str = "classification"
    modality: str = "tabular"
    winner_architecture: str = "LightGBM"
    metric_name: str = "AUC-ROC"
    metric_value: float = 0.0
    threshold: float | None = None
    threshold_operator: str = ">"
    dissect_patches: int = 0
    dissect_categories: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    endpoint_url: str = ""
    duration_seconds: float = 0.0
    status: str = "complete"

    model_name: str = "Model"
    model_format: str = "onnx"
    health_status: str = "unknown"
    health_latency_ms: float | None = None
    drift_enabled: bool = False
    drift_feature: str = ""
    drift_psi: float = 0.0
    drift_threshold: float = 0.2

    _width: int = 76

    def update_width(self, width: int) -> None:
        self._width = max(60, min(width, 120))

    def _format_duration(self) -> str:
        secs = int(self.duration_seconds)
        if secs < 60:
            return f"{secs}s"
        mins = secs // 60
        secs = secs % 60
        return f"{mins}m {secs}s"

    def _build_artifact_line(self, artifact: dict[str, Any]) -> Text:
        name = artifact.get("name", "artifact")
        size = artifact.get("size_bytes", 0)
        if size < 1024:
            size_str = f"{size}B"
        elif size < 1024 * 1024:
            size_str = f"{size/1024:.0f}KB"
        else:
            size_str = f"{size/1024/1024:.1f}MB"
        t = Text()
        t.append("  \u2714 ", style="summary_artifact")
        t.append(f"{name:<30}", style="summary_value")
        t.append(f"({size_str})", style="summary_label")
        return t

    def _build_harbor_section(self, w: int, border_color: str, line: Text) -> None:
        """Rich Harbor deployment section inside the completion card."""
        line.append("\u2502", style=border_color)
        line.append(" " * w)
        line.append("\u2502\n", style=border_color)

        # Status health
        health_icon = "\u25cf"
        if self.health_status == "healthy":
            health_color = "harbor_health_ok"
        elif self.health_status == "degraded":
            health_color = "harbor_health_warn"
        elif self.health_status == "unreachable":
            health_color = "harbor_health_error"
        else:
            health_color = "muted"
        health_str = self.health_status.title()
        if self.health_latency_ms is not None:
            health_str += f" ({self.health_latency_ms:.0f}ms)"

        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Serving   ", style=str(Theme.muted))
        line.append(f"{health_icon} ", style=health_color)
        line.append(self.endpoint_url, style="harbor_endpoint")
        line.append(" " * max(1, w - len(self.endpoint_url) - 16))
        line.append("\u2502\n", style=border_color)

        model_str = f"{self.model_name} ({self.model_format.upper()})"
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Model     ", style=str(Theme.muted))
        line.append(model_str, style=str(Theme.body))
        line.append(" " * max(1, w - len(model_str) - 13))
        line.append("\u2502\n", style=border_color)

        pred_url = f"{self.endpoint_url}/predict"
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Predict   ", style=str(Theme.muted))
        line.append(f"POST {pred_url}", style="harbor_endpoint")
        line.append(" " * max(1, w - len(pred_url) - 14))
        line.append("\u2502\n", style=border_color)

        swagger_url = f"{self.endpoint_url}/docs"
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Swagger   ", style=str(Theme.muted))
        line.append(f"GET {swagger_url}", style="harbor_swagger")
        line.append(" " * max(1, w - len(swagger_url) - 13))
        line.append("\u2502\n", style=border_color)

        if self.drift_enabled:
            line.append("\u2502", style=border_color)
            line.append(" ", style=border_color)
            drift_str = f"PSI: {self.drift_psi:.3f} / {self.drift_threshold}"
            if self.drift_feature:
                drift_str += f" ({self.drift_feature})"
            line.append("Drift     ", style=str(Theme.muted))
            line.append(drift_str, style="harbor_swagger")
            line.append(" " * max(1, w - len(drift_str) - 13))
            line.append("\u2502\n", style=border_color)

    def render(self) -> Text:
        w = self._width - 2
        border_color = (
            "completion_border" if self.status == "complete" else "completion_border_error"
        )
        line = Text()

        line.append("\u256d", style=border_color)
        title = f" Mission Complete {self._format_duration()} "
        line.append("\u2500" * ((w - len(title)) // 2), style=border_color)
        line.append(
            title, style=Style(bgcolor=Theme.completion_border.hex, bold=True, color="#FFFFFF")
        )
        line.append("\u2500" * (w - (w - len(title)) // 2 - len(title)), style=border_color)
        line.append("\u256e\n", style=border_color)

        line.append("\u2502", style=border_color)
        line.append(" " * w)
        line.append("\u2502\n", style=border_color)

        # Status
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        if self.status == "complete":
            line.append("\u2714 ", style=str(Theme.success))
        else:
            line.append("\u2718 ", style=str(Theme.error))
        display_id = self.mission_id[:20] if self.mission_id else "\u2014"
        line.append(display_id, style=f"bold {Theme.accent}")
        line.append(" " * max(1, w - len(display_id) - 4))
        line.append("\u2502\n", style=border_color)

        line.append("\u2502", style=border_color)
        line.append(" " * w)
        line.append("\u2502\n", style=border_color)

        # Result
        result_text = (
            f"{self.winner_architecture} \u00b7 {self.metric_name}: {self.metric_value:.4f}"
        )
        if self.threshold is not None:
            result_text += f" (\u2265 {self.threshold:.4f}"
            passed = self.metric_value >= self.threshold
            result_text += " \u2714" if passed else " \u2718"
            result_text += ")"
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Result    ", style=str(Theme.muted))
        line.append(result_text, style=str(Theme.body))
        line.append(" " * max(1, w - len(result_text) - 12))
        line.append("\u2502\n", style=border_color)

        # Crashes
        if self.dissect_patches > 0:
            cats = ", ".join(self.dissect_categories) if self.dissect_categories else "auto-patch"
            crash_text = f"{self.dissect_patches} repaired ({cats})"
            line.append("\u2502", style=border_color)
            line.append(" ", style=border_color)
            line.append("Crashes   ", style=str(Theme.muted))
            line.append(crash_text, style=str(Theme.body))
            line.append(" " * max(1, w - len(crash_text) - 12))
            line.append("\u2502\n", style=border_color)

        # Harbor section (rich deployment info)
        if self.endpoint_url:
            self._build_harbor_section(w, border_color, line)

        # Empty line
        line.append("\u2502", style=border_color)
        line.append(" " * w)
        line.append("\u2502\n", style=border_color)

        # Artifacts
        if self.artifacts:
            line.append("\u2502", style=border_color)
            line.append(" ", style=border_color)
            line.append("Artifacts", style=str(Theme.muted))
            line.append(" " * (w - 11))
            line.append("\u2502\n", style=border_color)
            for artifact in self.artifacts:
                line.append("\u2502", style=border_color)
                line.append_text(self._build_artifact_line(artifact))
                line.append(" " * max(1, w - 50))
                line.append("\u2502\n", style=border_color)

        # Empty line
        line.append("\u2502", style=border_color)
        line.append(" " * w)
        line.append("\u2502\n", style=border_color)

        # Next steps
        line.append("\u2502", style=border_color)
        line.append(" ", style=border_color)
        line.append("Next steps", style=str(Theme.muted))
        line.append("\n", style=border_color)

        next_steps = []
        if self.endpoint_url:
            next_steps.append(f"curl -X POST {self.endpoint_url}/predict -d @input.json")
        next_steps.append(
            "prometheus mission report " + (self.mission_id[:8] if self.mission_id else "<id>")
        )
        if self.endpoint_url:
            next_steps.append("prometheus model export --to ./deploy")

        for step in next_steps:
            line.append("\u2502", style=border_color)
            line.append("  \u2022 ", style=str(Theme.muted))
            line.append(step, style=str(Theme.info))
            line.append(" " * max(1, w - len(step) - 5))
            line.append("\u2502\n", style=border_color)

        # Bottom border
        line.append("\u2570", style=border_color)
        line.append("\u2500" * w, style=border_color)
        line.append("\u256f", style=border_color)

        return line

    def print(self, console: Console | None = None) -> None:
        c = console or Console()
        c.print(self.render())

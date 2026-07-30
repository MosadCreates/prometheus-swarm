"""Harbor deployment data utilities.

NOTE: Harbor deployment info is now rendered inline inside
MissionSummaryCard (mission_summary.py).  This module provides the
data-transfer helper used to populate that section.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from prometheus.ui.components.streaming.mission_summary import MissionSummaryCard


@dataclass
class HarborData:
    """Harbor deployment data — feeds into MissionSummaryCard."""

    endpoint_url: str = ""
    model_name: str = "Model"
    model_format: str = "onnx"
    val_metric: float = 0.0
    metric_name: str = "AUC-ROC"
    port: int = 8080
    health_status: str = "unknown"
    health_latency_ms: float | None = None
    drift_enabled: bool = False
    drift_feature: str = ""
    drift_psi: float = 0.0
    drift_threshold: float = 0.2


def apply_harbor_data_to_summary(
    summary: MissionSummaryCard,
    data: HarborData | dict[str, Any],
) -> None:
    """Populate a MissionSummaryCard with Harbor deployment data."""
    if isinstance(data, dict):
        data = HarborData(**{k: data.get(k, v) for k, v in HarborData().__dict__.items()})
    summary.endpoint_url = data.endpoint_url
    summary.model_name = data.model_name
    summary.model_format = data.model_format
    summary.health_status = data.health_status
    summary.health_latency_ms = data.health_latency_ms
    summary.drift_enabled = data.drift_enabled
    summary.drift_feature = data.drift_feature
    summary.drift_psi = data.drift_psi
    summary.drift_threshold = data.drift_threshold


def extract_harbor_data_from_event(event_detail: dict[str, Any]) -> HarborData:
    """Extract HarborData from an agent event detail dict."""
    return HarborData(
        endpoint_url=event_detail.get("endpoint_url", ""),
        model_name=event_detail.get("model_name", "Model"),
        model_format=event_detail.get("model_format", "onnx"),
        val_metric=event_detail.get("val_metric", 0.0),
        metric_name=event_detail.get("metric_name", "auc_roc"),
        port=event_detail.get("port", 8080),
        health_status=event_detail.get("health_status", "unknown"),
        health_latency_ms=event_detail.get("health_latency_ms"),
        drift_enabled=event_detail.get("drift_enabled", False),
        drift_feature=event_detail.get("drift_feature", ""),
        drift_psi=event_detail.get("drift_psi", 0.0),
        drift_threshold=event_detail.get("drift_threshold", 0.2),
    )

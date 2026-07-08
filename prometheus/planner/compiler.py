"""Deterministic MissionSpecification → ExecutionPlan compiler.

Pure functions. No LLM calls. No dataset inspection. No code generation.
Consumes only MissionSpecification fields that Scout has already produced.
"""

from __future__ import annotations

import logging
from typing import Any

from prometheus.planner.models import (
    DAGNode,
    DependencyEdge,
    ExecutionConfidence,
    ExecutionPlan,
    PlanningHints,
    ResourceBudget,
    ResourceEstimates,
    ResourceRequirements,
    RetryPolicy,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Architecture knowledge — execution-level only (not engineering-level)
# These are compact enough to live here; Forge's planner.py has the rich
# engineering knowledge (pros/cons, metric ranges, hyperparameter strategies).
# ---------------------------------------------------------------------------

_ARCH_RESOURCES: dict[str, dict[str, Any]] = {
    "lightgbm": {
        "base_minutes": 0.5,
        "minutes_per_row": 1 / 50000,
        "base_ram_mb": 256,
        "ram_per_row": 0.001,
        "disk_mb": 10,
        "base_vram_mb": 0,
        "vram_per_row": 0,
        "gpu": False,
        "cuda": None,
    },
    "xgboost": {
        "base_minutes": 1.0,
        "minutes_per_row": 1 / 30000,
        "base_ram_mb": 256,
        "ram_per_row": 0.001,
        "disk_mb": 15,
        "base_vram_mb": 0,
        "vram_per_row": 0,
        "gpu": False,
        "cuda": None,
    },
    "tabnet": {
        "base_minutes": 5.0,
        "minutes_per_row": 1 / 10000,
        "base_ram_mb": 512,
        "ram_per_row": 0.005,
        "disk_mb": 100,
        "base_vram_mb": 2048,
        "vram_per_row": 0.002,
        "gpu": True,
        "cuda": "11.8",
    },
    "distilbert": {
        "base_minutes": 10.0,
        "minutes_per_row": 1 / 1000,
        "base_ram_mb": 2048,
        "ram_per_row": 0.01,
        "disk_mb": 500,
        "base_vram_mb": 4096,
        "vram_per_row": 0.005,
        "gpu": True,
        "cuda": "11.8",
    },
    "efficientnet": {
        "base_minutes": 15.0,
        "minutes_per_row": 1 / 500,
        "base_ram_mb": 2048,
        "ram_per_row": 0.01,
        "disk_mb": 200,
        "base_vram_mb": 4096,
        "vram_per_row": 0.01,
        "gpu": True,
        "cuda": "11.8",
    },
}

_ARCH_MATURITY: dict[str, float] = {
    "lightgbm": 0.95,
    "xgboost": 0.93,
    "tabnet": 0.70,
    "distilbert": 0.88,
    "efficientnet": 0.85,
}

# ---------------------------------------------------------------------------
# DAG topology — the standard pipeline
# ---------------------------------------------------------------------------

_STANDARD_NODES: list[DAGNode] = [
    DAGNode(
        id="forge_generate",
        agent="Forge",
        label="Generate training script",
        depends_on=[],
        max_retries=2,
    ),
    DAGNode(
        id="furnace_train",
        agent="Furnace",
        label="Train model",
        depends_on=["forge_generate"],
        max_retries=3,
    ),
    DAGNode(
        id="dissect_patch",
        agent="Dissect",
        label="Patch training errors",
        depends_on=["forge_generate"],
        max_retries=3,
        metadata={"trigger_event": "CRASH_EVENT"},
    ),
    DAGNode(
        id="arbiter_evaluate",
        agent="Arbiter",
        label="Evaluate model",
        depends_on=["furnace_train"],
    ),
    DAGNode(
        id="harbor_deploy",
        agent="Harbor",
        label="Deploy model",
        depends_on=["arbiter_evaluate"],
        condition="pass",
    ),
    DAGNode(
        id="forge_retry",
        agent="Forge",
        label="Retry with new architecture",
        depends_on=["arbiter_evaluate"],
        condition="retry",
        max_retries=2,
    ),
]

_STANDARD_EDGES: list[DependencyEdge] = [
    DependencyEdge(from_node="forge_generate", to_node="furnace_train"),
    DependencyEdge(from_node="forge_generate", to_node="dissect_patch"),
    DependencyEdge(from_node="furnace_train", to_node="arbiter_evaluate"),
    DependencyEdge(from_node="arbiter_evaluate", to_node="harbor_deploy", condition="pass"),
    DependencyEdge(from_node="arbiter_evaluate", to_node="forge_retry", condition="retry"),
    DependencyEdge(from_node="arbiter_evaluate", to_node="__plan_failed__", condition="escalate"),
    DependencyEdge(from_node="dissect_patch", to_node="furnace_train", condition="patch_success"),
    DependencyEdge(from_node="dissect_patch", to_node="__plan_failed__", condition="escalate"),
    DependencyEdge(from_node="forge_retry", to_node="furnace_train"),
    DependencyEdge(from_node="harbor_deploy", to_node="__plan_complete__"),
]

_DEFAULT_ARTIFACTS: list[str] = [
    "model.onnx",
    "eval_report.json",
    "feature_importance.csv",
    "patch_log_history.jsonl",
    "training_metrics.json",
]

_DEFAULT_CHECKPOINTS: list[str] = [
    "forge:training_script_ready",
    "furnace:model_trained",
    "arbiter:evaluation_passed",
    "harbor:deployment_live",
]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compile_plan(
    spec: dict[str, Any],
    job_id: str,
    hints: PlanningHints | None = None,
) -> ExecutionPlan:
    """Compile a MissionSpecification into an ExecutionPlan.

    Args:
        spec: The MissionSpecification dict from Redis (job:{job_id}:mission_spec).
        job_id: UUID for the job.
        hints: Optional PlanningHints from historical execution data.
               When provided and evidence_count >= 3, adjusts budget and
               retry policy estimates based on historical evidence.

    Returns:
        A fully populated ExecutionPlan with nodes, edges, budget,
        retry policy, confidence, and critical path.
    """
    dataset = spec.get("dataset_analysis", {})
    pipeline = spec.get("recommended_pipeline", {})
    constraints = spec.get("constraints", {})
    success_criteria = spec.get("success_criteria", {})

    num_rows = dataset.get("num_rows", 0)
    num_cols = dataset.get("num_columns", 0)
    modality = dataset.get("modality", "tabular")

    architecture = pipeline.get("architecture", "lightgbm")
    arch_info = _ARCH_RESOURCES.get(architecture, _ARCH_RESOURCES["lightgbm"])

    budget = _build_budget(arch_info, num_rows, num_cols, constraints)
    nodes = _build_nodes(spec, architecture)
    edges = _build_edges()
    retry_policy = _build_retry_policy(spec, architecture)
    confidence = _compute_confidence(spec, architecture, num_rows, num_cols, modality, budget)

    # Apply historical hints if provided (Planner stays deterministic —
    # same inputs always produce the same output)
    if hints and hints.evidence_count >= _MIN_HINTS_EVIDENCE:
        budget = _apply_hints_to_budget(budget, hints)
        retry_policy = _apply_hints_to_retry(retry_policy, hints)
        logger.info(
            f"PlanningHints applied: {architecture} "
            f"evidence={hints.evidence_count} "
            f"dur={budget.estimates.estimated_duration_minutes}min "
            f"ram={budget.estimates.estimated_ram_mb}MB"
        )

    critical_path, total_minutes = _compute_critical_path(nodes, edges, budget)

    return ExecutionPlan(
        job_id=job_id,
        nodes={n.id: n for n in nodes},
        edges=edges,
        resource_budget=budget,
        retry_policy=retry_policy,
        confidence=confidence,
        critical_path=critical_path,
        estimated_total_minutes=total_minutes,
        artifacts=list(_DEFAULT_ARTIFACTS),
        critical_checkpoints=list(_DEFAULT_CHECKPOINTS),
        metadata={
            "modality": modality,
            "architecture": architecture,
            "num_rows": num_rows,
            "num_columns": num_cols,
        },
    )


# ---------------------------------------------------------------------------
# Internal — budget
# ---------------------------------------------------------------------------


def _build_budget(
    arch_info: dict[str, Any],
    num_rows: int,
    num_cols: int,
    constraints: dict[str, Any],
) -> ResourceBudget:
    col_factor = 1.0 + (num_cols - 10) * 0.02 if num_cols > 10 else 1.0

    minutes = max(
        1,
        int(
            round(
                (arch_info["base_minutes"] + arch_info["minutes_per_row"] * num_rows) * col_factor
            )
        ),
    )
    ram = max(
        arch_info["base_ram_mb"],
        int(round(arch_info["base_ram_mb"] + arch_info["ram_per_row"] * num_rows)),
    )
    disk = arch_info["disk_mb"]
    vram = int(round(arch_info["base_vram_mb"] + arch_info.get("vram_per_row", 0) * num_rows))

    max_latency = constraints.get("max_latency_ms")
    if max_latency and max_latency < 100:
        cost_hint = "latency_optimized"
    elif arch_info["gpu"]:
        cost_hint = "gpu_required"
    elif num_rows > 500_000:
        cost_hint = "cpu_preferred_large"
    else:
        cost_hint = "cpu_preferred"

    return ResourceBudget(
        requirements=ResourceRequirements(
            gpu_required=arch_info["gpu"],
            cuda_version=arch_info.get("cuda"),
            min_ram_mb=ram,
            min_disk_mb=disk,
            min_vram_mb=vram,
        ),
        estimates=ResourceEstimates(
            estimated_duration_minutes=minutes,
            estimated_ram_mb=ram,
            estimated_disk_mb=disk,
            estimated_vram_mb=vram,
        ),
        cost_optimization_hint=cost_hint,
    )


# ---------------------------------------------------------------------------
# Internal — DAG
# ---------------------------------------------------------------------------


def _build_nodes(
    spec: dict[str, Any],
    architecture: str,
) -> list[DAGNode]:
    return [n.model_copy() for n in _STANDARD_NODES]


def _build_edges() -> list[DependencyEdge]:
    return [e.model_copy() for e in _STANDARD_EDGES]


# ---------------------------------------------------------------------------
# Internal — retry policy
# ---------------------------------------------------------------------------


def _build_retry_policy(spec: dict[str, Any], architecture: str) -> RetryPolicy:
    candidate_models = spec.get("candidate_models", {})
    candidates = candidate_models.get("models", []) if isinstance(candidate_models, dict) else []

    if not candidates:
        alt_map = {
            "lightgbm": ["xgboost", "tabnet"],
            "xgboost": ["lightgbm", "tabnet"],
            "tabnet": ["xgboost", "lightgbm"],
            "distilbert": ["lightgbm"],
            "efficientnet": ["resnet", "lightgbm"],
        }
        candidates = alt_map.get(architecture, ["lightgbm"])

    return RetryPolicy(
        max_attempts=3,
        fallback_models=candidates[:3],
    )


_MIN_HINTS_EVIDENCE = 3
_MAX_HISTORICAL_WEIGHT = 0.7


def _apply_hints_to_budget(budget: ResourceBudget, hints: PlanningHints) -> ResourceBudget:
    """Blend theoretical estimates with historical evidence.

    Uses weighted blend: weight = min(_MAX_HISTORICAL_WEIGHT, evidence_count / 20).
    When evidence_count < _MIN_HINTS_EVIDENCE, no adjustment is made.
    """
    weight = min(_MAX_HISTORICAL_WEIGHT, hints.evidence_count / 20)

    new_estimates = budget.estimates.model_copy()

    if hints.estimated_duration_minutes is not None:
        blended = round(
            weight * hints.estimated_duration_minutes
            + (1 - weight) * new_estimates.estimated_duration_minutes
        )
        new_estimates.estimated_duration_minutes = max(1, blended)

    if hints.estimated_ram_mb is not None:
        blended = round(
            weight * hints.estimated_ram_mb + (1 - weight) * new_estimates.estimated_ram_mb
        )
        new_estimates.estimated_ram_mb = max(64, blended)

    if hints.estimated_vram_mb is not None:
        blended = round(
            weight * hints.estimated_vram_mb + (1 - weight) * new_estimates.estimated_vram_mb
        )
        new_estimates.estimated_vram_mb = max(0, blended)

    new_requirements = budget.requirements.model_copy()
    if hints.gpu_recommended is not None and not budget.requirements.gpu_required:
        new_requirements.gpu_required = hints.gpu_recommended

    return ResourceBudget(
        requirements=new_requirements,
        estimates=new_estimates,
        cost_optimization_hint=budget.cost_optimization_hint,
    )


def _apply_hints_to_retry(retry_policy: RetryPolicy, hints: PlanningHints) -> RetryPolicy:
    """Reorder fallback models based on historical pass rates."""
    if hints.fallback_models:
        return RetryPolicy(
            max_attempts=retry_policy.max_attempts,
            fallback_models=hints.fallback_models[:3],
            fallback_strategies=retry_policy.fallback_strategies,
            escalation=retry_policy.escalation,
        )
    return retry_policy


# ---------------------------------------------------------------------------
# Internal — execution confidence
# ---------------------------------------------------------------------------


def _compute_confidence(
    spec: dict[str, Any],
    architecture: str,
    num_rows: int,
    num_cols: int,
    modality: str,
    budget: ResourceBudget,
) -> ExecutionConfidence:
    factors: dict[str, float] = {}

    # Architecture maturity (0-1)
    maturity = _ARCH_MATURITY.get(architecture, 0.5)
    factors["architecture_maturity"] = maturity

    # Dataset size factor: too small (<200) or too large (>10M) reduces confidence
    if num_rows < 200:
        size_factor = 0.3 + (num_rows / 200) * 0.5
    elif num_rows < 1000:
        size_factor = 0.8
    elif num_rows < 1_000_000:
        size_factor = 0.95
    elif num_rows < 10_000_000:
        size_factor = 0.75
    else:
        size_factor = 0.5
    factors["dataset_size"] = size_factor

    # Modality-architecture fit
    modality_fit = {
        ("tabular", "lightgbm"): 0.98,
        ("tabular", "xgboost"): 0.95,
        ("tabular", "tabnet"): 0.85,
        ("text", "distilbert"): 0.95,
        ("text", "lightgbm"): 0.60,
        ("image", "efficientnet"): 0.95,
        ("image", "distilbert"): 0.40,
    }.get((modality, architecture), 0.5)
    factors["modality_fit"] = modality_fit

    # GPU availability factor
    if budget.requirements.gpu_required and modality in ("text", "image"):
        gpu_factor = 0.95 if budget.estimates.estimated_vram_mb <= 8192 else 0.70
    elif budget.requirements.gpu_required:
        gpu_factor = 0.80
    else:
        gpu_factor = 0.95
    factors["gpu_readiness"] = gpu_factor

    # Column count factor
    if num_cols <= 5:
        col_factor = 0.85
    elif num_cols <= 50:
        col_factor = 0.95
    elif num_cols <= 500:
        col_factor = 0.80
    else:
        col_factor = 0.50
    factors["column_count"] = col_factor

    # Weighted average
    weights = {
        "architecture_maturity": 0.30,
        "dataset_size": 0.25,
        "modality_fit": 0.25,
        "gpu_readiness": 0.10,
        "column_count": 0.10,
    }
    score = sum(factors[k] * weights[k] for k in weights if k in factors)
    score = max(0.0, min(1.0, score))

    if score >= 0.85:
        assessment = "high"
    elif score >= 0.60:
        assessment = "medium"
    else:
        assessment = "low"

    return ExecutionConfidence(
        score=round(score, 4),
        factors=factors,
        assessment=assessment,
    )


# ---------------------------------------------------------------------------
# Internal — critical path
# ---------------------------------------------------------------------------


def _compute_critical_path(
    nodes: list[DAGNode],
    edges: list[DependencyEdge],
    budget: ResourceBudget,
) -> tuple[list[str], int]:
    """Compute the longest path through the DAG.

    Follows the happy path (unconditional edges + pass condition):
      forge_generate -> furnace_train -> arbiter_evaluate -> harbor_deploy -> complete

    Conditional edges (retry, escalate) are excluded from critical path
    since they represent branches, not the main execution flow.
    Terminal nodes contribute zero duration.
    """
    node_map = {n.id: n for n in nodes}

    total_duration = budget.estimates.estimated_duration_minutes

    duration_map: dict[str, int] = {}
    all_ids = list(node_map.keys()) + ["__plan_complete__", "__plan_failed__"]
    for nid in all_ids:
        if nid in ("__plan_complete__", "__plan_failed__"):
            duration_map[nid] = 0
        elif nid == "forge_generate":
            duration_map[nid] = max(1, int(total_duration * 0.02))
        elif nid == "furnace_train":
            duration_map[nid] = max(1, int(total_duration * 0.85))
        elif nid == "dissect_patch":
            duration_map[nid] = max(1, int(total_duration * 0.10))
        elif nid == "arbiter_evaluate":
            duration_map[nid] = max(1, int(total_duration * 0.02))
        elif nid == "harbor_deploy":
            duration_map[nid] = max(1, int(total_duration * 0.05))
        elif nid == "forge_retry":
            duration_map[nid] = max(1, int(total_duration * 0.30))
        else:
            duration_map[nid] = 1

    # Only follow unconditional edges + happy-path (pass condition) edges
    # Conditional edges (retry, escalate) create cycles in the graph
    happy_edges = [
        e
        for e in edges
        if not e.condition or e.condition == "pass" or e.condition == "patch_success"
    ]
    # Also add depends_on edges (unconditional)
    for n in nodes:
        for dep in n.depends_on:
            happy_edges.append(DependencyEdge(from_node=dep, to_node=n.id))

    adj: dict[str, list[str]] = {nid: [] for nid in all_ids}
    in_degree: dict[str, int] = {nid: 0 for nid in all_ids}
    for e in happy_edges:
        if e.from_node in adj and e.to_node in in_degree:
            adj[e.from_node].append(e.to_node)
            in_degree[e.to_node] = in_degree.get(e.to_node, 0) + 1

    topo: list[str] = []
    queue = [nid for nid in all_ids if in_degree.get(nid, 0) == 0]
    while queue:
        nid = queue.pop(0)
        topo.append(nid)
        for nb in adj.get(nid, []):
            in_degree[nb] -= 1
            if in_degree[nb] == 0:
                queue.append(nb)

    if len(topo) != len(all_ids):
        logger.warning("Critical path: DAG has a cycle in happy path, using fallback ordering")
        topo = [n for n in all_ids if n in topo]
        missing = [n for n in all_ids if n not in topo]
        topo.extend(missing)

    dp: dict[str, int] = {nid: 0 for nid in all_ids}
    prev: dict[str, str | None] = {nid: None for nid in all_ids}

    for nid in topo:
        for nb in adj.get(nid, []):
            cand = dp[nid] + duration_map.get(nb, 0)
            if cand > dp[nb]:
                dp[nb] = cand
                prev[nb] = nid

    terminals = ["__plan_complete__", "__plan_failed__"]
    term = max(terminals, key=lambda t: dp.get(t, 0))

    path: list[str] = []
    cur: str | None = term
    visited: set[str] = set()
    while cur is not None:
        if cur in visited:
            break
        visited.add(cur)
        if cur not in ("__plan_complete__", "__plan_failed__"):
            path.append(cur)
        cur = prev.get(cur)
    path.reverse()

    return path, total_duration

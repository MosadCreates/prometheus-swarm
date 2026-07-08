"""ExecutionPlan validators.

Five pure validation functions. Each returns a list of error strings.
Empty list = no errors in that category.
"""

from __future__ import annotations

from typing import Any

from prometheus.planner.models import ExecutionPlan


def validate_plan(plan: ExecutionPlan) -> list[str]:
    """Run all 5 validators. Returns list of error strings (empty = valid)."""
    return (
        _check_dag_cycles(plan)
        + _check_missing_task_refs(plan)
        + _check_unreachable_nodes(plan)
        + _check_conditions_covered(plan)
        + _check_terminals(plan)
    )


# ---------------------------------------------------------------------------
# 1. Cycle detection
# ---------------------------------------------------------------------------


def _check_dag_cycles(plan: ExecutionPlan) -> list[str]:
    """DFS-based cycle detection on the execution graph.

    Only unconditional edges are checked (edges without a condition).
    Conditional edges (retry, escalate, pass, patch_success) represent
    runtime branches that are mutually exclusive — only one branch is
    taken at a time, so they cannot form an actual execution cycle.

    depends_on edges are deliberately excluded: they represent scheduling
    constraints that may create artificial cycles through conditional
    paths (e.g. forge_retry depends_on arbiter_evaluate while also
    looping back to furnace_train). The actual execution flow is
    determined by edge conditions, not depends_on.
    """
    adj: dict[str, list[str]] = {}
    all_nodes = set(plan.nodes.keys()) | {"__plan_complete__", "__plan_failed__"}
    for nid in all_nodes:
        adj[nid] = []
    for e in plan.edges:
        if e.condition:
            continue
        if e.from_node in adj and e.to_node in adj:
            adj[e.from_node].append(e.to_node)

    # Include terminal nodes in adjacency for cycle detection
    for term in ("__plan_complete__", "__plan_failed__"):
        if term not in adj:
            adj[term] = []
    for e in plan.edges:
        if e.to_node in ("__plan_complete__", "__plan_failed__"):
            if e.from_node in adj and e.to_node not in adj[e.from_node]:
                adj[e.from_node].append(e.to_node)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {n: WHITE for n in adj}

    def dfs(nid: str) -> list[str]:
        color[nid] = GRAY
        for nb in adj.get(nid, []):
            if color.get(nb, WHITE) == GRAY:
                return [f"Cycle detected: {nid} -> {nb}"]
            if color.get(nb, WHITE) == WHITE:
                result = dfs(nb)
                if result:
                    return result
        color[nid] = BLACK
        return []

    errors: list[str] = []
    for nid in list(adj.keys()):
        if color.get(nid, WHITE) == WHITE:
            err = dfs(nid)
            if err:
                errors.extend(err)
    return errors


# ---------------------------------------------------------------------------
# 2. Missing task references
# ---------------------------------------------------------------------------


def _check_missing_task_refs(plan: ExecutionPlan) -> list[str]:
    """Every dependency and edge target references an existing node."""
    errors: list[str] = []
    known = set(plan.nodes.keys()) | {"__plan_complete__", "__plan_failed__"}

    for nid, node in plan.nodes.items():
        for dep in node.depends_on:
            if dep not in known:
                errors.append(f"Node '{nid}' depends on unknown node '{dep}'")

    for e in plan.edges:
        if e.from_node not in known:
            errors.append(f"Edge from unknown node '{e.from_node}'")
        if e.to_node not in known:
            errors.append(f"Edge to unknown node '{e.to_node}'")

    return errors


# ---------------------------------------------------------------------------
# 3. Unreachable nodes
# ---------------------------------------------------------------------------


def _check_unreachable_nodes(plan: ExecutionPlan) -> list[str]:
    """Every node must be reachable from at least one root (no incoming edges)."""
    if not plan.nodes:
        return ["No nodes in plan"]

    # Build incoming edge count
    incoming: dict[str, int] = {nid: 0 for nid in plan.nodes}
    incoming["__plan_complete__"] = 0
    incoming["__plan_failed__"] = 0

    for nid, node in plan.nodes.items():
        for dep in node.depends_on:
            if dep in incoming:
                incoming[nid] = incoming.get(nid, 0) + 1

    for e in plan.edges:
        if e.to_node in incoming:
            incoming[e.to_node] = incoming.get(e.to_node, 0) + 1

    roots = [nid for nid, cnt in incoming.items() if cnt == 0]
    if not roots:
        return ["No root node found (all nodes have incoming edges)"]

    # BFS from all roots
    adj: dict[str, list[str]] = {nid: [] for nid in incoming}
    for nid, node in plan.nodes.items():
        for dep in node.depends_on:
            if dep in adj:
                adj[dep].append(nid)
    for e in plan.edges:
        if e.from_node in adj:
            adj[e.from_node].append(e.to_node)

    reachable: set[str] = set()
    queue = list(roots)
    while queue:
        cur = queue.pop(0)
        if cur in reachable:
            continue
        reachable.add(cur)
        for nb in adj.get(cur, []):
            if nb not in reachable:
                queue.append(nb)

    unreachable = [nid for nid in incoming if nid not in reachable]
    if unreachable:
        return [f"Unreachable nodes: {', '.join(unreachable)}"]

    return []


# ---------------------------------------------------------------------------
# 4. Conditions coverage
# ---------------------------------------------------------------------------

_DECISION_CONDITIONS: dict[str, list[str]] = {
    "arbiter_evaluate": ["pass", "retry", "escalate"],
    "dissect_patch": ["patch_success", "escalate"],
}


def _check_conditions_covered(plan: ExecutionPlan) -> list[str]:
    """Every decision node must have all its conditions mapped in edges."""
    errors: list[str] = []

    for node_id, required_conditions in _DECISION_CONDITIONS.items():
        if node_id not in plan.nodes:
            continue

        outgoing = [e for e in plan.edges if e.from_node == node_id]

        if not outgoing:
            errors.append(
                f"Decision node '{node_id}' has no outgoing edges "
                f"(required conditions: {required_conditions})"
            )
            continue

        outgoing_conditions: set[str | None] = {e.condition for e in outgoing}

        # Check that all required conditions are present
        for rc in required_conditions:
            if rc not in outgoing_conditions:
                errors.append(
                    f"Decision node '{node_id}' missing condition '{rc}' "
                    f"(has: {outgoing_conditions})"
                )

    return errors


# ---------------------------------------------------------------------------
# 5. Terminal validation
# ---------------------------------------------------------------------------


def _check_terminals(plan: ExecutionPlan) -> list[str]:
    """Plan must have paths to completion and failure."""
    errors: list[str] = []

    has_complete = any(e.to_node == "__plan_complete__" for e in plan.edges)
    has_failed = any(e.to_node == "__plan_failed__" for e in plan.edges)

    if not has_complete:
        errors.append("No path to '__plan_complete__' terminal node")
    if not has_failed:
        errors.append("No path to '__plan_failed__' terminal node")

    return errors

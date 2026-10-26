"""Regression guards for the Week-1 orchestration fixes.

1. The Arbiter→RETRY path in orchestrator/runtime.py must follow the canonical
   state matrix (ARBITER_RUNNING→ARBITER_COMPLETED→RETRY_PENDING→RETRY_RUNNING→
   FORGE_RUNNING). The previous direct ARBITER_RUNNING→RETRY_RUNNING move raised
   ValueError, left the event un-ACKed, and silently killed orchestrated retry.
2. orchestrator/job_runner.py must persist a final terminal phase explicitly
   ("pass" → MISSION_PASSED, "crash"/"timeout"/"error" → MISSION_FAILED) instead
   of relying on canonical_phase(), which does not know those status words.
"""

import pytest

from contracts.state import (
    MISSION_PHASE_TRANSITIONS,
    validate_phase_transition,
)

RETRY_SEQUENCE = [
    "ARBITER_RUNNING",
    "ARBITER_COMPLETED",
    "RETRY_PENDING",
    "RETRY_RUNNING",
    "FORGE_RUNNING",
]


def test_retry_sequence_is_matrix_legal():
    for src, dst in zip(RETRY_SEQUENCE, RETRY_SEQUENCE[1:], strict=False):
        validate_phase_transition(src, dst)  # must not raise


def test_old_direct_retry_transition_is_illegal_regression_guard():
    """The bug we fixed: this exact edge must stay illegal so nobody re-adds it."""
    with pytest.raises(ValueError):
        validate_phase_transition("ARBITER_RUNNING", "RETRY_RUNNING")


def test_budget_exhaustion_escalate_edge_legal():
    # From ARBITER_COMPLETED, MISSION_FAILED (escalate) must be allowed
    assert "MISSION_FAILED" in MISSION_PHASE_TRANSITIONS["ARBITER_COMPLETED"]


def test_job_runner_status_map_targets_are_real_phases():
    """job_runner builds a status→phase map locally; keep its targets canonical."""
    import re
    from pathlib import Path

    src = Path("orchestrator/job_runner.py").read_text(encoding="utf-8")
    block = re.search(r"phase_by_status = \{(.*?)\}", src, re.DOTALL)
    assert block, "phase_by_status map missing from job_runner.py"
    phases = set(re.findall(r'"([A-Z_]+)"', block.group(1)))
    assert phases, "no phases parsed"
    for phase in phases:
        assert phase in MISSION_PHASE_TRANSITIONS, f"non-canonical phase {phase}"

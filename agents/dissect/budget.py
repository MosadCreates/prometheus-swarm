"""Repair Budget Management — LLM call budgets per job (Phase 8).

Limits:
  - Maximum LLM calls per job (DEFAULT_MAX_LLM_CALLS)
  - Maximum repair cost in USD (DEFAULT_MAX_COST)
  - Maximum repair latency in seconds (DEFAULT_MAX_LATENCY)
  - Maximum repair attempts per crash (DEFAULT_MAX_ATTEMPTS)

Dissect checks budget before calling LLM:
  - If budget exhausted → escalate immediately (no LLM call)
  - If remaining budget is low → prefer lower-certainty deterministic repairs
"""

import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

DEFAULT_MAX_LLM_CALLS = int(os.getenv("DISSECT_MAX_LLM_CALLS", "3"))
DEFAULT_MAX_COST = float(os.getenv("DISSECT_MAX_COST_USD", "0.50"))
DEFAULT_MAX_LATENCY = int(os.getenv("DISSECT_MAX_LATENCY_S", "300"))
DEFAULT_MAX_ATTEMPTS = int(os.getenv("DISSECT_MAX_ATTEMPTS", "3"))


@dataclass
class RepairBudget:
    job_id: str
    max_llm_calls: int = DEFAULT_MAX_LLM_CALLS
    max_cost: float = DEFAULT_MAX_COST
    max_latency: int = DEFAULT_MAX_LATENCY
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    llm_calls_used: int = 0
    total_cost: float = 0.0
    start_time: float = field(default_factory=time.time)
    attempt_count: int = 0

    def can_call_llm(self) -> bool:
        if self.llm_calls_used >= self.max_llm_calls:
            return False
        if self.total_cost >= self.max_cost:
            return False
        elapsed = time.time() - self.start_time
        if elapsed >= self.max_latency:
            return False
        if self.attempt_count >= self.max_attempts:
            return False
        return True

    def record_llm_call(self, cost: float = 0.0) -> None:
        self.llm_calls_used += 1
        self.total_cost += cost

    def record_attempt(self) -> None:
        self.attempt_count += 1

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def budget_remaining_ratio(self) -> float:
        """Return 0.0 (exhausted) to 1.0 (full budget)."""
        ratios = [
            1.0 - (self.llm_calls_used / max(self.max_llm_calls, 1)),
            1.0 - (self.total_cost / max(self.max_cost, 0.01)),
            1.0 - (self.elapsed_seconds() / max(self.max_latency, 1)),
        ]
        return max(0.0, min(ratios))

    def get_cascade_level_bias(self) -> int:
        """Return a cascade level floor based on remaining budget.

        If budget is nearly exhausted, skip straight to Level 5 (escalation).
        If budget is low, skip LLM (Level 4) and go to escalation.
        """
        remaining = self.budget_remaining_ratio()
        if remaining <= 0.0:
            return 5
        if remaining < 0.25:
            return 4
        if remaining < 0.5:
            return 3
        return 0

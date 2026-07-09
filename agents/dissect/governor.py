"""LLM Call Governor — failure-scoped budget enforcement.

Every unique failure fingerprint gets its own budget:
  - max 1 LLM call per fingerprint
  - max $0.10 per fingerprint
  - max 15000 tokens per fingerprint
  - max 3 minutes wall-clock per fingerprint

Budgets are independent by fingerprint. If `missing_column` consumed its
budget, a later `cuda_oom` with a different fingerprint gets a fresh budget.
"""

import logging
import os
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FINGERPRINT_MAX_LLM_CALLS = int(os.getenv("FP_MAX_LLM_CALLS", "1"))
FINGERPRINT_MAX_COST = float(os.getenv("FP_MAX_COST_USD", "0.10"))
FINGERPRINT_MAX_TOKENS = int(os.getenv("FP_MAX_TOKENS", "15000"))
FINGERPRINT_MAX_SECONDS = int(os.getenv("FP_MAX_SECONDS", "180"))


@dataclass
class FingerprintBudget:
    """Per-fingerprint budget. Created fresh for each unique failure."""

    fingerprint: str
    max_llm_calls: int = FINGERPRINT_MAX_LLM_CALLS
    max_cost: float = FINGERPRINT_MAX_COST
    max_tokens: int = FINGERPRINT_MAX_TOKENS
    max_seconds: int = FINGERPRINT_MAX_SECONDS

    llm_calls_used: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    start_time: float = field(default_factory=time.time)

    def can_call_llm(self) -> bool:
        if self.llm_calls_used >= self.max_llm_calls:
            return False
        if self.total_cost >= self.max_cost:
            return False
        if self.total_tokens >= self.max_tokens:
            return False
        if time.time() - self.start_time >= self.max_seconds:
            return False
        return True

    def record_llm_call(self, cost: float = 0.0, tokens: int = 0) -> None:
        self.llm_calls_used += 1
        self.total_cost += cost
        self.total_tokens += tokens

    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time

    def exhausted_reason(self) -> str:
        if self.llm_calls_used >= self.max_llm_calls:
            return "token_budget"
        if self.total_cost >= self.max_cost:
            return "cost_budget"
        if self.total_tokens >= self.max_tokens:
            return "token_budget"
        if time.time() - self.start_time >= self.max_seconds:
            return "time_budget"
        return "unknown"


class BudgetGovernor:
    """Manages per-fingerprint budgets for a job.

    Each unique fingerprint gets its own FingerprintBudget. Budgets are
    created on first encounter and queried/counted down on subsequent
    encounters. This prevents unrelated failures from sharing a budget
    while still capping cost per failure type.
    """

    def __init__(self, job_id: str):
        self._job_id = job_id
        self._budgets: dict[str, FingerprintBudget] = {}

    def get_or_create(self, fingerprint: str) -> FingerprintBudget:
        if fingerprint not in self._budgets:
            self._budgets[fingerprint] = FingerprintBudget(fingerprint=fingerprint)
        return self._budgets[fingerprint]

    def record_llm_call(self, fingerprint: str, cost: float = 0.0, tokens: int = 0) -> None:
        budget = self.get_or_create(fingerprint)
        budget.record_llm_call(cost, tokens)

    def can_call_llm(self, fingerprint: str) -> bool:
        budget = self.get_or_create(fingerprint)
        return budget.can_call_llm()

    def exhausted_reason(self, fingerprint: str) -> str:
        budget = self.get_or_create(fingerprint)
        return budget.exhausted_reason()

    def all_budgets(self) -> dict[str, dict]:
        return {
            fp: {
                "llm_calls_used": b.llm_calls_used,
                "total_cost": round(b.total_cost, 4),
                "total_tokens": b.total_tokens,
                "elapsed_seconds": round(b.elapsed_seconds(), 1),
            }
            for fp, b in self._budgets.items()
        }

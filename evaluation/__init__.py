"""Experimental campaign configuration and tooling — Milestone 7.

This package is the experiment configuration layer. It provides:
- Feature toggles for ablation studies (DISABLE_PLANNER, DISABLE_PATCH_MEMORY, DISABLE_DISSECT)
- Benchmark dataset validation
- Reproducibility checks
- Per-stage performance logging
- Stress/fault injection harness

No agents, contracts, buses, or schemas are modified. This is an
observational layer only.
"""

from evaluation import config as _eval_config
from evaluation.config import load_config


# Re-export: dynamic via delegation to config module
def __getattr__(name: str):
    return getattr(_eval_config, name)


__all__ = [
    "DISABLE_DISSECT",
    "DISABLE_PATCH_MEMORY",
    "DISABLE_PLANNER",
    "PROFILE_MODE",
    "STRESS_MODE",
    "load_config",
]

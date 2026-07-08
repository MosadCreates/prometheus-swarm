"""Experimental feature toggles.

All toggles are read from environment variables on every attribute access
via module-level __getattr__. No caching — so env var changes within the
same Python process are reflected immediately.

These are *not* production configuration flags. They are experimental
variables for the ablation and stress-test campaigns. Keeping them
separate from prometheus/config.py ensures they never leak into
production runtime behaviour.

Usage:
    from evaluation import config as eval_config
    if eval_config.DISABLE_PLANNER:
        ...
"""

import os


def _enabled(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in ("1", "true", "yes")


def load_config() -> dict[str, bool]:
    """Load all experimental toggles from environment variables (fresh each call)."""
    return {
        "DISABLE_PLANNER": _enabled("DISABLE_PLANNER"),
        "DISABLE_PATCH_MEMORY": _enabled("DISABLE_PATCH_MEMORY"),
        "DISABLE_DISSECT": _enabled("DISABLE_DISSECT"),
        "STRESS_MODE": _enabled("STRESS_MODE"),
        "PROFILE_MODE": _enabled("PROFILE_MODE"),
    }


_CONFIG_NAMES = frozenset(
    {
        "DISABLE_PLANNER",
        "DISABLE_PATCH_MEMORY",
        "DISABLE_DISSECT",
        "STRESS_MODE",
        "PROFILE_MODE",
    }
)


def __getattr__(name: str) -> bool:
    """Read config toggles fresh from env vars on every access."""
    if name in _CONFIG_NAMES:
        return _enabled(name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)

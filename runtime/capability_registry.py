"""Capability registry — dynamic detection of available ML libraries and frameworks.

Every agent uses this to determine what's actually installable/runnable,
not what's theoretically possible. Prevents selecting architectures whose
dependencies aren't present.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

from runtime.models import SUPPORTED_ARCHITECTURES

logger = logging.getLogger(__name__)

# ── Architecture → required import map ──

_ARCH_REQUIREMENTS: dict[str, dict[str, str]] = {
    "lightgbm": {
        "module": "lightgbm",
        "display": "LightGBM",
    },
    "xgboost": {
        "module": "xgboost",
        "display": "XGBoost",
    },
    "tabnet": {
        "module": "pytorch_tabnet",
        "display": "TabNet (pytorch-tabnet)",
    },
    "distilbert": {
        "module": "transformers",
        "display": "Transformers (HuggingFace)",
    },
    "efficientnet": {
        "module": "torchvision",
        "display": "TorchVision (EfficientNet)",
    },
}


def check_architecture_available(architecture: str) -> bool:
    """Check if all required packages for an architecture are importable.

    Args:
        architecture: Architecture name (must be in SUPPORTED_ARCHITECTURES).

    Returns:
        True if all required modules can be imported, False otherwise.
    """
    if architecture not in _ARCH_REQUIREMENTS:
        return False

    req = _ARCH_REQUIREMENTS[architecture]
    try:
        importlib.import_module(req["module"])
        return True
    except ImportError:
        logger.debug(
            f"Architecture '{architecture}' not available — " f"missing module '{req['module']}'"
        )
        return False


def get_available_architectures() -> list[str]:
    """Return list of architectures whose dependencies are installed.

    Iterates SUPPORTED_ARCHITECTURES in order and checks each.
    """
    available: list[str] = []
    for arch in SUPPORTED_ARCHITECTURES:
        if check_architecture_available(arch):
            available.append(arch)
    return available


def get_available_architectures_with_details() -> dict[str, dict[str, Any]]:
    """Return dict mapping arch → details for all available architectures.

    Includes: min_dimensions, display_name, installed_version.
    """
    result: dict[str, dict[str, Any]] = {}
    for arch in SUPPORTED_ARCHITECTURES:
        if not check_architecture_available(arch):
            continue
        req = _ARCH_REQUIREMENTS.get(arch, {})
        version: str | None = None
        try:
            mod = importlib.import_module(req.get("module", arch))
            version = getattr(mod, "__version__", None)
        except ImportError:
            pass
        result[arch] = {
            "min_dimensions": SUPPORTED_ARCHITECTURES[arch],
            "display_name": req.get("display", arch),
            "installed_version": version,
        }
    return result

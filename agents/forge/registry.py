"""Architecture registry — single source of truth for all architectures.

Every architecture must register:
  - Template:   Jinja template file(s) for script generation
  - Optuna Space:  Hyperparameter search space definition
  - Dispatcher:    f-string generator function (last resort)
  - Capabilities:  Metadata (modality, task_types, optuna, cv, imbalance)

Startup validation: every arch in SUPPORTED_ARCHITECTURES must have all 5.
Missing one raises RuntimeError at import time.
"""

from __future__ import annotations

import ast
import importlib
import logging
from typing import Any, Callable

from runtime.models import SUPPORTED_ARCHITECTURES

logger = logging.getLogger(__name__)


class ArchitectureEntry:
    """One complete architecture entry in the registry."""

    def __init__(
        self,
        name: str,
        template_ids: list[tuple[str, str]],
        optuna_space_fn: Callable[[], dict] | None,
        dispatcher_fn: Callable[..., str] | None,
        capabilities: dict[str, Any],
    ) -> None:
        self.name = name
        self.template_ids = template_ids
        self.optuna_space_fn = optuna_space_fn
        self.dispatcher_fn = dispatcher_fn
        self.capabilities = capabilities

    def has_template(self) -> bool:
        from agents.forge.template_renderer import has_template as _has_template

        for arch, task in self.template_ids:
            if _has_template(arch, task):
                return True
        return False

    def has_optuna_space(self) -> bool:
        return self.optuna_space_fn is not None

    def has_dispatcher(self) -> bool:
        return self.dispatcher_fn is not None

    def validate_script_imports(self, source: str) -> list[str]:
        """Check that every top-level import in the source can be resolved."""
        errors: list[str] = []
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            return [f"Syntax error: {e}"]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    try:
                        importlib.import_module(top)
                    except ImportError:
                        errors.append(f"Import '{top}' (from '{alias.name}') could not be resolved")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level is None:
                    top = node.module.split(".")[0]
                    try:
                        importlib.import_module(top)
                    except ImportError:
                        errors.append(
                            f"Import '{top}' (from '{node.module}') could not be resolved"
                        )
        return errors


_REGISTRY: dict[str, ArchitectureEntry] = {}


def register(entry: ArchitectureEntry) -> None:
    _REGISTRY[entry.name] = entry
    logger.debug(f"Registered architecture '{entry.name}' with {len(entry.template_ids)} templates")


def get(name: str) -> ArchitectureEntry | None:
    return _REGISTRY.get(name)


def get_all() -> dict[str, ArchitectureEntry]:
    return dict(_REGISTRY)


def validate_all() -> list[str]:
    """Validate every architecture in SUPPORTED_ARCHITECTURES is fully registered.

    Returns a list of error messages (empty if all pass).
    Raises RuntimeError on first missing component.
    """
    errors: list[str] = []
    registered_names = set(_REGISTRY.keys())
    expected = set(SUPPORTED_ARCHITECTURES.keys())

    for name in expected - registered_names:
        errors.append(
            f"Architecture '{name}' is in SUPPORTED_ARCHITECTURES but not registered "
            f"in the ArchitectureRegistry. Call register() for it."
        )

    for name in sorted(expected & registered_names):
        entry = _REGISTRY[name]
        if not entry.has_template():
            errors.append(
                f"Architecture '{name}': missing template. "
                f"Expected one of {entry.template_ids} to resolve to a Jinja file."
            )
        if not entry.has_optuna_space():
            errors.append(
                f"Architecture '{name}': missing optuna_space function. "
                f"Provide an optuna_space_fn or None if not applicable."
            )
        if not entry.has_dispatcher():
            errors.append(
                f"Architecture '{name}': missing dispatcher (f-string generator). "
                f"Provide a dispatcher_fn."
            )

    for name in registered_names - expected:
        logger.warning(
            f"Architecture '{name}' is registered but not in SUPPORTED_ARCHITECTURES. "
            f"Add it to runtime.models.SUPPORTED_ARCHITECTURES or remove the registration."
        )

    return errors


def validate_imports_in_script(architecture: str, script_source: str) -> list[str]:
    entry = _REGISTRY.get(architecture)
    if entry is None:
        return [f"Unknown architecture '{architecture}' — cannot validate imports"]
    return entry.validate_script_imports(script_source)


def _build_registry() -> None:
    """Populate the registry with all known architectures.

    Uses lazy imports to avoid circular dependencies.
    """
    from agents.forge.tools import (
        define_optuna_space,
        _write_lightgbm_script,
        _write_xgboost_script,
        _write_tabnet_script,
        _write_distilbert_script,
        _write_efficientnet_script,
    )
    from agents.forge.template_renderer import ARCHITECTURE_TASK_MAP

    for arch_name in sorted(SUPPORTED_ARCHITECTURES):
        if arch_name in _REGISTRY:
            continue

        task_types = ARCHITECTURE_TASK_MAP.get(arch_name, [])
        template_ids = [(arch_name, t) for t in task_types]
        optuna_fn = (lambda a=arch_name: lambda: define_optuna_space(a))()

        if arch_name == "lightgbm":
            register(
                ArchitectureEntry(
                    name="lightgbm",
                    template_ids=template_ids,
                    optuna_space_fn=lambda: define_optuna_space("lightgbm"),
                    dispatcher_fn=lambda mb, jid, sd, ds, **kw: _write_lightgbm_script(
                        mb, jid, sd, ds, **kw
                    ),
                    capabilities={
                        "modality": "tabular",
                        "task_types": ["binary", "multiclass", "regression"],
                        "supports_optuna": True,
                        "supports_cv": True,
                        "imbalance_strategies": ["smote", "class_weight", "none"],
                        "gpu_required": False,
                    },
                )
            )
        elif arch_name == "xgboost":
            register(
                ArchitectureEntry(
                    name="xgboost",
                    template_ids=template_ids,
                    optuna_space_fn=lambda: define_optuna_space("xgboost"),
                    dispatcher_fn=lambda mb, jid, sd, ds, **kw: _write_xgboost_script(
                        mb, jid, sd, ds, **kw
                    ),
                    capabilities={
                        "modality": "tabular",
                        "task_types": ["binary", "multiclass", "regression"],
                        "supports_optuna": True,
                        "supports_cv": True,
                        "imbalance_strategies": ["class_weight", "none"],
                        "gpu_required": False,
                    },
                )
            )
        elif arch_name == "tabnet":
            register(
                ArchitectureEntry(
                    name="tabnet",
                    template_ids=template_ids,
                    optuna_space_fn=lambda: define_optuna_space("tabnet"),
                    dispatcher_fn=lambda mb, jid, sd, ds, **kw: _write_tabnet_script(
                        mb, jid, sd, ds, **kw
                    ),
                    capabilities={
                        "modality": "tabular",
                        "task_types": ["binary", "multiclass", "regression"],
                        "supports_optuna": True,
                        "supports_cv": True,
                        "imbalance_strategies": ["none"],
                        "gpu_required": True,
                    },
                )
            )
        elif arch_name == "distilbert":
            register(
                ArchitectureEntry(
                    name="distilbert",
                    template_ids=template_ids,
                    optuna_space_fn=lambda: define_optuna_space("distilbert"),
                    dispatcher_fn=lambda mb, jid, sd, ds, **kw: _write_distilbert_script(
                        mb, jid, sd, ds, **kw
                    ),
                    capabilities={
                        "modality": "text",
                        "task_types": ["binary", "multiclass"],
                        "supports_optuna": True,
                        "supports_cv": False,
                        "imbalance_strategies": ["class_weight", "none"],
                        "gpu_required": True,
                    },
                )
            )
        elif arch_name == "efficientnet":
            register(
                ArchitectureEntry(
                    name="efficientnet",
                    template_ids=template_ids,
                    optuna_space_fn=lambda: define_optuna_space("efficientnet"),
                    dispatcher_fn=lambda mb, jid, sd, ds, **kw: _write_efficientnet_script(
                        mb, jid, sd, ds, **kw
                    ),
                    capabilities={
                        "modality": "image",
                        "task_types": ["binary", "multiclass"],
                        "supports_optuna": True,
                        "supports_cv": False,
                        "imbalance_strategies": ["class_weight", "none"],
                        "gpu_required": True,
                    },
                )
            )

    registered_count = len(_REGISTRY)
    expected_count = len(SUPPORTED_ARCHITECTURES)
    errors = validate_all()
    if errors:
        msg = (
            f"Architecture registry validation FAILED at startup "
            f"({len(errors)} error(s)):\n  "
            + "\n  ".join(errors)
            + f"\n\nExpected {expected_count} architectures in SUPPORTED_ARCHITECTURES, "
            f"registered {registered_count}. "
            f"Every architecture must have template, optuna_space, dispatcher, and capabilities."
        )
        raise RuntimeError(msg)
    logger.info(
        f"Architecture registry validated: {registered_count}/{expected_count} "
        f"architectures fully registered"
    )


# Populate registry at import time — triggers startup validation.
_build_registry()

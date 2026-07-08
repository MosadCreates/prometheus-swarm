"""Experiment persistence — save/load experiments to/from JSON files."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from research.validation.models import Experiment, ExperimentRun, ExperimentSet

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path(__file__).resolve().parent.parent.parent / "experiments"


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _serialize(obj: Any) -> Any:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, (list, tuple)):
        return [_serialize(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    return obj


# ---------------------------------------------------------------------------
# ExperimentSet
# ---------------------------------------------------------------------------


def save_experiment_set(
    exp_set: ExperimentSet,
    directory: str | Path | None = None,
) -> Path:
    """Save an ExperimentSet to a JSON file.

    Returns the path it was saved to.
    """
    directory = Path(directory) if directory else _DEFAULT_DIR
    _ensure_dir(directory)
    path = directory / f"{exp_set.set_id}.json"
    data = _serialize(exp_set)
    path.write_text(json.dumps(data, indent=2, default=str))
    logger.info(f"Experiment set saved: {path}")
    return path


def load_experiment_set(
    path: str | Path,
) -> ExperimentSet:
    """Load an ExperimentSet from a JSON file."""
    path = Path(path)
    data = json.loads(path.read_text())
    return ExperimentSet(**data)


def list_experiment_sets(
    directory: str | Path | None = None,
) -> list[Path]:
    """List all experiment set JSON files in directory, newest first."""
    directory = Path(directory) if directory else _DEFAULT_DIR
    if not directory.exists():
        return []
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def delete_experiment_set(
    set_id: str,
    directory: str | Path | None = None,
) -> bool:
    """Delete an experiment set file by ID. Returns True if deleted."""
    directory = Path(directory) if directory else _DEFAULT_DIR
    path = directory / f"{set_id}.json"
    if path.exists():
        path.unlink()
        logger.info(f"Experiment set deleted: {path}")
        return True
    return False


# ---------------------------------------------------------------------------
# Individual experiments
# ---------------------------------------------------------------------------


def save_experiment(
    experiment: Experiment,
    directory: str | Path | None = None,
) -> Path:
    """Save a single Experiment (legacy, prefer save_experiment_set)."""
    directory = Path(directory) if directory else _DEFAULT_DIR
    _ensure_dir(directory)
    path = directory / f"{experiment.experiment_id}_{experiment.hypothesis.value}.json"
    data = _serialize(experiment)
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def load_experiment(path: str | Path) -> Experiment:
    data = json.loads(Path(path).read_text())
    return Experiment(**data)

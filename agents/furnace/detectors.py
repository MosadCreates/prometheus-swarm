"""Pure training-health detectors for Furnace.

Each predicate is a pure function over metric/loss history — no I/O, no agent
state — so they can be unit-tested without Redis, Docker, or a live training
run. Furnace's ``_handle_json_progress`` feeds them one value per epoch.

Metrics are either *higher-is-better* (accuracy, auc, f1) or *lower-is-better*
(rmse, mae, logloss). Callers pass ``higher_is_better`` (for metric-based
detectors) or ``lower_is_better`` (for the train/val overfit detector) to set
the direction.
"""

from __future__ import annotations

import math

_EPS = 1e-9


def _invalid(value: float | None) -> bool:
    """True when a value is missing or not a finite real number."""
    return value is None or math.isnan(value) or math.isinf(value)


def detect_divergence(
    history: list[float],
    higher_is_better: bool = True,
    window: int = 4,
    tol: float = 0.05,
) -> bool:
    """True when recent epochs are NaN/inf or show a *sustained* bad trend.

    Requires at least ``window + 1`` points: the last ``window`` values must be
    monotone in the bad direction AND the latest value must sit more than
    ``tol`` (relative) past the best value seen before the window. A temporary
    one-epoch dip is not divergence — only a run that keeps getting worse.
    """
    if not history or len(history) < window + 1:
        return False
    if any(_invalid(v) for v in history[-window:]):
        return True

    tail = [float(v) for v in history[-window:]]
    reference = max(history[:-window]) if higher_is_better else min(history[:-window])

    if higher_is_better:
        monotone_bad = all(tail[i] <= tail[i - 1] + _EPS for i in range(1, len(tail)))
        if not monotone_bad:
            return False
        return tail[-1] < reference * (1.0 - tol)
    else:
        monotone_bad = all(tail[i] >= tail[i - 1] - _EPS for i in range(1, len(tail)))
        if not monotone_bad:
            return False
        return tail[-1] > reference * (1.0 + tol)


def detect_plateau(
    history: list[float],
    higher_is_better: bool = True,
    patience: int = 10,
    tol: float = 1e-4,
) -> bool:
    """True when the last ``patience`` epochs produced no improvement over earlier history.

    Compares the best value in the recent ``patience`` window against the best
    value in all *prior* epochs.  If the recent window has not beaten the prior
    best by more than ``tol`` (relative), training has plateaued.
    """
    if len(history) < patience + 1:
        return False
    if any(_invalid(v) for v in history):
        return False

    prior = history[:-patience]
    recent = history[-patience:]

    prior_best = max(prior) if higher_is_better else min(prior)
    recent_best = max(recent) if higher_is_better else min(recent)

    threshold = tol * max(1.0, abs(prior_best))

    if higher_is_better:
        return recent_best - prior_best <= threshold
    return prior_best - recent_best <= threshold


def detect_overfitting(
    train_history: list[float],
    val_history: list[float],
    lower_is_better: bool = True,
    window: int = 3,
    gap_tol: float = 0.15,
) -> bool:
    """True when validation stops improving while training keeps improving.

    The classic generalization-gap signal: over the trailing ``window`` epochs,
    training is still making progress but validation has drifted more than
    ``gap_tol`` (relative) from its own best value.

    Args:
        train_history: Per-epoch training values (loss or metric), oldest first.
        val_history:  Per-epoch validation values, aligned with train_history.
        lower_is_better: True for loss-style values (val rising = bad); False
            for metric-style values (val falling = bad).
    """
    if len(train_history) < window or len(val_history) < window:
        return False
    if len(train_history) != len(val_history):
        return False
    if any(_invalid(v) for v in train_history[-window:]) or any(
        _invalid(v) for v in val_history[-window:]
    ):
        return False

    train_start, train_now = float(train_history[-window]), float(train_history[-1])
    val_now = float(val_history[-1])

    if lower_is_better:
        train_improving = train_now < train_start * (1.0 - _EPS)
        val_best = min(float(v) for v in val_history)
        val_worse = val_now > val_best * (1.0 + gap_tol)
        return train_improving and val_worse

    train_improving = train_now > train_start * (1.0 + _EPS)
    val_best = max(float(v) for v in val_history)
    val_stalled = val_now < val_best * (1.0 - gap_tol)
    return train_improving and val_stalled

"""Unit tests for agents.furnace.detectors — pure functions, no I/O."""

from agents.furnace.detectors import (
    detect_divergence,
    detect_overfitting,
    detect_plateau,
)


# ── detect_divergence ─────────────────────────────────────────────────────


class TestDetectDivergence:
    """Divergence requires window+1 points, NaN/inf or sustained bad trend."""

    def test_too_short_history(self):
        assert detect_divergence([0.9, 0.8, 0.7], window=4) is False

    def test_nan_in_tail(self):
        history = [0.9, 0.88, 0.87, 0.86, float("nan")]
        assert detect_divergence(history, window=4) is True

    def test_inf_in_tail(self):
        history = [0.6, 0.7, 0.8, 0.5, float("inf")]
        assert detect_divergence(history, window=4) is True

    def test_monotone_decline_higher_is_better(self):
        # Best before window is 0.90; tail drops 0.84→0.82→0.80→0.78
        # 0.78 < 0.90 * 0.95 = 0.855 → diverged
        history = [0.90, 0.84, 0.82, 0.80, 0.78]
        assert detect_divergence(history, higher_is_better=True, window=4, tol=0.05) is True

    def test_small_dip_not_diverged(self):
        # Best 0.90, tail drops to 0.88 — within 5% tolerance
        history = [0.90, 0.90, 0.89, 0.89, 0.88]
        assert detect_divergence(history, higher_is_better=True, window=4, tol=0.05) is False

    def test_non_monotone_not_diverged(self):
        # Tail has a recovery → not monotone bad
        history = [0.90, 0.80, 0.85, 0.80, 0.78]
        assert detect_divergence(history, higher_is_better=True, window=4, tol=0.05) is False

    def test_lower_is_better_divergence(self):
        # Loss going up: 0.10, 0.20, 0.25, 0.30, 0.35
        history = [0.10, 0.20, 0.25, 0.30, 0.35]
        assert detect_divergence(history, higher_is_better=False, window=4, tol=0.05) is True

    def test_lower_is_better_no_divergence(self):
        # Loss rises but not monotone (recovery dip breaks the monotone check)
        history = [0.10, 0.11, 0.10, 0.12, 0.13]
        assert detect_divergence(history, higher_is_better=False, window=4, tol=0.05) is False

    def test_empty_history(self):
        assert detect_divergence([], window=4) is False


# ── detect_plateau ────────────────────────────────────────────────────────


class TestDetectPlateau:
    """Plateau requires patience+1 points with no new best in recent window."""

    def test_too_short_for_plateau(self):
        assert detect_plateau([0.8] * 5, patience=10) is False

    def test_flat_history_is_plateau(self):
        history = [0.80] + [0.8001] * 11
        assert detect_plateau(history, higher_is_better=True, patience=10, tol=1e-4) is True

    def test_improving_history_no_plateau(self):
        history = [0.70 + i * 0.02 for i in range(15)]
        assert detect_plateau(history, higher_is_better=True, patience=10) is False

    def test_plateau_lower_is_better(self):
        # RMSE stuck at 0.50 for 11 epochs
        history = [0.50] * 12
        assert detect_plateau(history, higher_is_better=False, patience=10) is True

    def test_slight_improvement_breaks_plateau(self):
        # Best overall is 0.80; recent window achieves 0.81 → new best → not plateau
        history = [0.80] + [0.79] * 9 + [0.81]
        assert detect_plateau(history, higher_is_better=True, patience=10) is False

    def test_nan_in_history_returns_false(self):
        history = [0.80] * 5 + [float("nan")] + [0.80] * 6
        assert detect_plateau(history, patience=10) is False


# ── detect_overfitting ────────────────────────────────────────────────────


class TestDetectOverfitting:
    """Overfitting: train improves but val drifts from its best."""

    def test_too_short(self):
        assert detect_overfitting([0.5, 0.4], [0.5, 0.6], window=3) is False

    def test_classic_overfit_lower_is_better(self):
        # Train loss falls: 0.5 → 0.4 → 0.3
        # Val loss rises: 0.5 → 0.6 → 0.7
        # val_best=0.5, val_now=0.7, gap = 0.7 > 0.5*(1+0.15) = 0.575 → overfit
        train = [0.5, 0.4, 0.3]
        val = [0.5, 0.6, 0.7]
        assert detect_overfitting(train, val, lower_is_better=True, window=3) is True

    def test_no_overfit_both_improving(self):
        train = [0.5, 0.4, 0.3]
        val = [0.5, 0.45, 0.4]
        assert detect_overfitting(train, val, lower_is_better=True, window=3) is False

    def test_higher_is_better_overfit(self):
        # metric-style: train goes up, val stalls then drops
        train = [0.70, 0.80, 0.90]
        val = [0.70, 0.68, 0.55]
        # val_best=0.70, val_now=0.55, 0.55 < 0.70*(1-0.15)=0.595 → overfit
        assert detect_overfitting(train, val, lower_is_better=False, window=3) is True

    def test_mismatched_lengths(self):
        assert detect_overfitting([0.5, 0.4], [0.5, 0.6, 0.7]) is False

    def test_nan_in_window(self):
        train = [0.5, 0.4, float("nan")]
        val = [0.5, 0.6, 0.7]
        assert detect_overfitting(train, val, window=3) is False

    def test_train_not_improving(self):
        # Train flat → not really overfitting (both stuck)
        train = [0.5, 0.5, 0.5]
        val = [0.5, 0.6, 0.7]
        assert detect_overfitting(train, val, lower_is_better=True, window=3) is False

"""PSI (Population Stability Index) drift monitor for model serving.

Compares live inference inputs against training distribution.
PSI > 0.2 triggers a DRIFT_ALERT.
"""

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

PSI_THRESHOLD = 0.2


def compute_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    bins: int = 10,
) -> float:
    """Compute Population Stability Index between two distributions.

    PSI = sum((actual_pct - expected_pct) * ln(actual_pct / expected_pct))

    Args:
        expected: Training distribution values
        actual: Live inference distribution values
        bins: Number of bins for histogram

    Returns:
        PSI score (0 = identical, > 0.2 = significant drift)
    """
    expected = np.asarray(expected, dtype=np.float64).flatten()
    actual = np.asarray(actual, dtype=np.float64).flatten()

    if len(expected) == 0 or len(actual) == 0:
        return 0.0

    min_val = min(expected.min(), actual.min())
    max_val = max(expected.max(), actual.max())

    if min_val == max_val:
        return 0.0

    bin_edges = np.linspace(min_val, max_val, bins + 1)

    expected_counts, _ = np.histogram(expected, bins=bin_edges)
    actual_counts, _ = np.histogram(actual, bins=bin_edges)

    expected_pct = expected_counts / len(expected)
    actual_pct = actual_counts / len(actual)

    # Avoid log(0) by replacing 0 with a small epsilon
    eps = 1e-6
    expected_pct = np.clip(expected_pct, eps, 1.0)
    actual_pct = np.clip(actual_pct, eps, 1.0)

    psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
    return float(psi)


def check_drift(
    feature_name: str,
    expected: np.ndarray,
    actual: np.ndarray,
    threshold: float = PSI_THRESHOLD,
) -> dict[str, Any]:
    """Check if drift has occurred for a feature.

    Args:
        feature_name: Name of the feature being checked
        expected: Training distribution
        actual: Live inference distribution (last N samples)
        threshold: PSI threshold for alert

    Returns:
        Dict with keys: feature, psi, threshold, drift_detected
    """
    psi = compute_psi(expected, actual)
    drift_detected = psi > threshold

    if drift_detected:
        logger.warning(f"Drift detected | feature={feature_name} PSI={psi:.4f} threshold={threshold}")

    return {
        "feature": feature_name,
        "psi": round(psi, 4),
        "threshold": threshold,
        "drift_detected": drift_detected,
    }

"""Label normalizer — deterministic target encoding across retries.

Fixes Bug 7: Target labels not normalized between retries.
The label encoder is fitted once, serialized with every checkpoint,
and restored on resume. Training scripts import this instead of
creating ad-hoc LabelEncoders.
"""

from __future__ import annotations

import logging
import os
import pickle
from typing import Any

import numpy as np
from sklearn.preprocessing import LabelEncoder

logger = logging.getLogger(__name__)

_LABEL_ENCODER_FILE = "label_encoder.pkl"


def normalize_target(
    labels: np.ndarray | list,
    encoder_path: str | None = None,
    fit: bool = True,
) -> tuple[np.ndarray, LabelEncoder | None]:
    """Normalize target labels to 0-based integer encoding.

    If a saved LabelEncoder exists at encoder_path, loads and reuses it.
    Otherwise fits a new LabelEncoder and optionally saves it.

    Args:
        labels: Raw target labels (strings, ints, or floats).
        encoder_path: Directory path where encoder.pkl is/should be stored.
            If None, no save/load is attempted.
        fit: If True, fit a new encoder. If False, only transform with
            existing encoder (raises if none found).

    Returns:
        Tuple of (encoded_labels, encoder).
    """
    labels_arr = np.asarray(labels)

    # Try to load existing encoder
    encoder = _try_load_encoder(encoder_path)

    if encoder is not None:
        # Reuse existing encoder — ensures consistent encoding across retries
        try:
            encoded = encoder.transform(labels_arr)
            logger.info(f"Reused existing LabelEncoder ({len(encoder.classes_)} classes)")
            return encoded.astype(np.int64), encoder
        except ValueError as e:
            logger.warning(f"Existing LabelEncoder rejected labels ({e}) — refitting")
            encoder = None

    if not fit:
        raise ValueError(
            "No saved LabelEncoder found and fit=False. " "Cannot normalize labels without fitting."
        )

    encoder = LabelEncoder()
    encoded = encoder.fit_transform(labels_arr)
    logger.info(
        f"Fitted new LabelEncoder ({len(encoder.classes_)} classes: " f"{list(encoder.classes_)})"
    )

    # Save encoder for reuse across retries
    _save_encoder(encoder, encoder_path)

    return encoded.astype(np.int64), encoder


def _try_load_encoder(encoder_path: str | None) -> LabelEncoder | None:
    """Try to load a previously saved LabelEncoder."""
    if encoder_path is None:
        return None
    encoder_file = os.path.join(encoder_path, _LABEL_ENCODER_FILE)
    if not os.path.exists(encoder_file):
        return None
    try:
        with open(encoder_file, "rb") as f:
            encoder = pickle.load(f)
        if isinstance(encoder, LabelEncoder):
            logger.info(f"Loaded LabelEncoder from {encoder_file}")
            return encoder
    except Exception as e:
        logger.warning(f"Failed to load LabelEncoder: {e}")
    return None


def _save_encoder(encoder: LabelEncoder, encoder_path: str | None) -> None:
    """Save the LabelEncoder for reuse across retries."""
    if encoder_path is None:
        return
    os.makedirs(encoder_path, exist_ok=True)
    encoder_file = os.path.join(encoder_path, _LABEL_ENCODER_FILE)
    try:
        with open(encoder_file, "wb") as f:
            pickle.dump(encoder, f)
        logger.info(f"Saved LabelEncoder to {encoder_file}")
    except Exception as e:
        logger.warning(f"Failed to save LabelEncoder: {e}")


def is_label_encoded(labels: np.ndarray) -> bool:
    """Check if labels appear already 0-index-encoded.

    Heuristic: if labels are integer type and values are in [0, n_classes-1]
    with no gaps, they're likely already encoded.
    """
    if not np.issubdtype(labels.dtype, np.integer):
        return False
    if len(labels) == 0:
        return False
    unique = np.unique(labels)
    if len(unique) <= 1:
        return len(unique) == 1 and unique[0] == 0
    return bool(np.array_equal(unique, np.arange(len(unique))))


def normalizer_code_snippet(output_dir: str) -> str:
    """Return a Python code snippet that importing agents can inline.

    This is used by f-string generators in tools.py to include label
    normalization at the top of training scripts.
    """
    return f"""# ── Label normalization (Bug 7 fix) ──
from training.label_normalizer import normalize_target, is_label_encoded

LABEL_ENCODER_DIR = "{output_dir}"
os.makedirs(LABEL_ENCODER_DIR, exist_ok=True)

# Normalize target labels deterministically
labels_np = df["{{target_col}}"].values
if not is_label_encoded(labels_np):
    labels_encoded, label_encoder = normalize_target(
        labels_np, encoder_path=LABEL_ENCODER_DIR, fit=True
    )
    df["{{target_col}}"] = labels_encoded
    logger.info(f"Encoded target: {{len(label_encoder.classes_)}} classes")
else:
    labels_encoded, label_encoder = normalize_target(
        labels_np, encoder_path=LABEL_ENCODER_DIR, fit=False
    )
    logger.info("Target already encoded — reused LabelEncoder")
"""

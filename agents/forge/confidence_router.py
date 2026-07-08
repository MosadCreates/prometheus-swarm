"""Confidence Threshold Router — chooses script generation strategy by confidence.

The cascade (in order of preference):
  1. Template  (confidence ≥ 0.85) — deterministic Jinja, no LLM, no cache check
  2. Cache     (confidence ≥ 0.55) — fingerprint cache → template fallback
  3. LLM       (confidence < 0.55) — f-string generators (most flexible)

This implements Missing Piece 5 of the post-audit sprint:
  "The LLM should be reached because confidence is too low, not because
   generation started."
"""

import logging
from typing import Literal

logger = logging.getLogger(__name__)

# ── Threshold constants (tunable via environment) ──────────────────────
TEMPLATE_THRESHOLD = 0.85
CACHE_THRESHOLD = 0.55

Strategy = Literal["template", "cache", "llm"]


def get_generation_strategy(confidence: float | None) -> Strategy:
    """Select script generation strategy based on confidence.

    Args:
        confidence: Scout's overall_confidence (0.0–1.0), or None if unknown.

    Returns:
        "template" if confidence ≥ TEMPLATE_THRESHOLD,
        "cache"    if confidence ≥ CACHE_THRESHOLD,
        "llm"      if confidence < CACHE_THRESHOLD or None.
    """
    if confidence is None:
        return "llm"

    if confidence >= TEMPLATE_THRESHOLD:
        return "template"
    elif confidence >= CACHE_THRESHOLD:
        return "cache"
    else:
        return "llm"


def strategy_label(strategy: Strategy) -> str:
    labels = {"template": "Template", "cache": "Cache", "llm": "LLM"}
    return labels.get(strategy, "Unknown")

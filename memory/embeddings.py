"""Singleton SentenceTransformer model for ChromaDB embedding generation.

Lazily loaded on first call. All memory collection modules use this
single instance instead of loading the model independently, reducing
the per-campaign load count from 70+ to 1.
"""

import logging
import os
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = Lock()
_MODEL: Any = None
_MODEL_NAME: str | None = None


def get_embedding_model(model_name: str | None = None) -> Any:
    """Return the shared SentenceTransformer instance (singleton).

    Args:
        model_name: Optional override; defaults to EMBEDDING_MODEL env var
            or "all-MiniLM-L6-v2".

    Returns:
        SentenceTransformer instance, or None if loading fails.
    """
    global _MODEL, _MODEL_NAME

    name = model_name or os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

    if _MODEL is not None and _MODEL_NAME == name:
        return _MODEL

    with _LOCK:
        if _MODEL is not None and _MODEL_NAME == name:
            return _MODEL
        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(name)
            _MODEL_NAME = name
            logger.info(f"Loaded embedding model: {name}")
        except Exception as e:
            logger.warning(f"Failed to load embedding model '{name}': {e}")
            _MODEL = None
            _MODEL_NAME = None

    return _MODEL


def get_embedding(text: str, model_name: str | None = None) -> list[float] | None:
    """Get the embedding vector for a text string using the singleton model.

    Returns None if the model could not be loaded.
    """
    model = get_embedding_model(model_name)
    if model is None:
        return None
    try:
        return model.encode(text, normalize_embeddings=True).tolist()
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None

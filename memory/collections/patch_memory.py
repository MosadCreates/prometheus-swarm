"""patch_memory collection: Dissect stores and retrieves past error patches."""

import json
import logging
import os
from typing import Any

from memory.chroma_client import ChromaClient

logger = logging.getLogger(__name__)

COLLECTION_NAME = "patch_memory"


def _get_collection():
    return ChromaClient().get_or_create_collection(COLLECTION_NAME)


def store_patch(
    patch_id: str,
    job_id: str,
    exception_type: str,
    exception_message: str,
    category: str,
    repair_strategy: str,
    diff_applied: str,
    outcome: str,
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
) -> None:
    """Store a patch attempt in ChromaDB for future retrieval.

    Args:
        patch_id: UUID of the patch
        job_id: UUID of the job
        exception_type: e.g. "ValueError"
        exception_message: Full error message
        category: Error taxonomy category
        repair_strategy: Which strategy was used
        diff_applied: Unified diff string
        outcome: "success", "rollback", or "escalated"
        embedding_model: sentence-transformers model name
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(embedding_model)
    except Exception as e:
        logger.warning(f"Embedding model load failed: {e}")
        return

    text = f"{exception_type}: {exception_message}\nCategory: {category}\nStrategy: {repair_strategy}"
    embedding = model.encode(text).tolist()

    metadata = {
        "job_id": job_id,
        "exception_type": exception_type,
        "exception_message": exception_message[:500],
        "category": category,
        "repair_strategy": repair_strategy,
        "outcome": outcome,
        "patch_id": patch_id,
    }

    collection = _get_collection()
    collection.add(
        ids=[patch_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[diff_applied[:2000]],
    )

    logger.info(f"Patch stored in ChromaDB: {patch_id} | category={category} outcome={outcome}")


def query_similar_patches(
    error_text: str,
    category: str | None = None,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve K most similar past patches from ChromaDB.

    Args:
        error_text: The error description to match against
        category: Optional filter by error category
        k: Number of results to return (default 3)

    Returns:
        List of dicts with keys: patch_id, similarity_score, category, outcome, repair_strategy
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        embedding = model.encode(error_text).tolist()
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return []

    collection = _get_collection()

    where_filter = {"category": category} if category else None

    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where=where_filter,
    )

    patches = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0.0
            similarity = max(0.0, 1.0 - float(distance))

            patches.append({
                "patch_id": doc_id,
                "similarity_score": round(similarity, 4),
                "category": metadata.get("category", ""),
                "outcome": metadata.get("outcome", ""),
                "repair_strategy": metadata.get("repair_strategy", ""),
            })

    return patches

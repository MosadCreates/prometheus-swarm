"""architecture_memory collection: Forge stores and retrieves past architecture decisions."""

import json
import logging
import os
from typing import Any

from memory.chroma_client import ChromaClient

logger = logging.getLogger(__name__)

COLLECTION_NAME = "architecture_memory"


def _get_collection():
    return ChromaClient().get_or_create_collection(COLLECTION_NAME)


def store_architecture(
    decision_id: str,
    job_id: str,
    modality: str,
    task_type: str,
    num_rows: int,
    class_imbalance_ratio: float | None,
    model_selected: str,
    imbalance_strategy: str,
    outcome_metric: float | None = None,
    outcome_label: str = "unknown",
) -> None:
    """Store an architecture decision for future retrieval.

    Args:
        decision_id: UUID for this decision
        job_id: UUID of the job
        modality: "tabular", "text", or "image"
        task_type: "classification", "regression", etc.
        num_rows: Number of rows in dataset
        class_imbalance_ratio: Positive/negative ratio or None
        model_selected: Architecture family selected
        imbalance_strategy: SMOTE, class_weight, focal_loss, or none
        outcome_metric: Final evaluation metric value (e.g., AUC)
        outcome_label: "success", "retry", "escalate", or "unknown"
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    except Exception as e:
        logger.warning(f"Embedding model load failed: {e}")
        return

    text = f"Modality: {modality} Task: {task_type} Rows: {num_rows} Imbalance: {class_imbalance_ratio} Model: {model_selected}"
    embedding = model.encode(text).tolist()

    metadata = {
        "job_id": job_id,
        "modality": modality,
        "task_type": task_type,
        "num_rows": num_rows,
        "class_imbalance_ratio": str(class_imbalance_ratio) if class_imbalance_ratio else "none",
        "model_selected": model_selected,
        "imbalance_strategy": imbalance_strategy,
        "outcome_metric": str(outcome_metric) if outcome_metric else "none",
        "outcome_label": outcome_label,
    }

    collection = _get_collection()
    collection.add(
        ids=[decision_id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[text],
    )

    logger.info(f"Architecture stored: {decision_id} | model={model_selected} outcome={outcome_label}")


def query_similar_architectures(
    modality: str,
    task_type: str,
    k: int = 3,
) -> list[dict[str, Any]]:
    """Retrieve K most similar past architecture decisions.

    Args:
        modality: "tabular", "text", or "image"
        task_type: "classification", "regression", etc.
        k: Number of results

    Returns:
        List of dicts with keys: model_selected, outcome, metric, similarity_score
    """
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        text = f"Modality: {modality} Task: {task_type}"
        embedding = model.encode(text).tolist()
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return []

    collection = _get_collection()

    where_filter = {"modality": modality}

    results = collection.query(
        query_embeddings=[embedding],
        n_results=k,
        where=where_filter,
    )

    archs = []
    if results and results["ids"] and results["ids"][0]:
        for i, doc_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 0.0

            archs.append({
                "decision_id": doc_id,
                "similarity_score": round(max(0.0, 1.0 - float(distance)), 4),
                "model_selected": meta.get("model_selected", ""),
                "outcome_label": meta.get("outcome_label", ""),
                "outcome_metric": meta.get("outcome_metric", ""),
                "imbalance_strategy": meta.get("imbalance_strategy", ""),
            })

    return archs

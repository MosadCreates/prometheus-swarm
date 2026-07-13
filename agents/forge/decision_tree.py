"""Architecture selection decision tree with optional ChromaDB memory."""

import logging

logger = logging.getLogger(__name__)


def select_architecture(
    mission_brief: dict,
    use_memory: bool = True,
    similar_architectures: list[dict] | None = None,
) -> str:
    modality = mission_brief.get("modality", "tabular")
    num_rows = mission_brief.get("dataset", {}).get("num_rows", 0)
    if modality == "tabular":
        if num_rows < 1_000_000:
            default = "lightgbm"
        else:
            default = "tabnet"
    elif modality == "text":
        default = "distilbert"
    elif modality == "image":
        default = "efficientnet"
    else:
        default = "lightgbm"

    # If memory is enabled and similar past architectures exist, boost preference
    if use_memory and similar_architectures:
        succeeded = [
            a["model_selected"]
            for a in similar_architectures
            if a.get("outcome_label") == "success"
        ]
        if succeeded:
            preferred = succeeded[0]
            if preferred != default:
                logger.info(
                    f"Architecture memory suggests {preferred} (default would be {default}), "
                    f"using memory-backed decision"
                )
                return preferred
        failed = [
            a["model_selected"]
            for a in similar_architectures
            if a.get("outcome_label") in ("escalate", "retry")
        ]
        if failed and default in failed:
            # Default architecture previously failed — try alternative
            alternatives = {
                "lightgbm": "xgboost",
                "xgboost": "lightgbm",
                "tabnet": "lightgbm",
                "distilbert": "lightgbm",
                "efficientnet": "lightgbm",
            }
            alt = alternatives.get(default, "lightgbm")
            logger.info(f"Default architecture {default} previously failed, switching to {alt}")
            return alt

    return default


def select_imbalance_strategy(imbalance_ratio, mission_brief):
    brief_strategy = mission_brief.get("imbalance_strategy", "none")
    if brief_strategy != "none":
        return brief_strategy
    if imbalance_ratio is None:
        return "none"
    if imbalance_ratio > 20:
        return "smote"
    if imbalance_ratio > 5:
        return "class_weight"
    return "none"

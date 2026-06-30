"""Architecture selection decision tree."""


def select_architecture(mission_brief: dict) -> str:
    modality = mission_brief.get("modality", "tabular")
    num_rows = mission_brief.get("dataset", {}).get("num_rows", 0)
    if modality == "tabular":
        if num_rows < 1_000_000:
            return "lightgbm"
        else:
            return "tabnet"
    elif modality == "text":
        return "distilbert"
    elif modality == "image":
        return "efficientnet"
    return "lightgbm"


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
    if imbalance_ratio > 3:
        return "focal_loss"
    return "none"

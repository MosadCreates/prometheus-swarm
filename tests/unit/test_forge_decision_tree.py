"""Unit tests for Forge decision tree."""

from agents.forge.decision_tree import select_architecture, select_imbalance_strategy


def test_select_lightgbm_for_small_tabular():
    brief = {
        "modality": "tabular",
        "task_type": "classification",
        "dataset": {"num_rows": 1000},
    }
    assert select_architecture(brief) == "lightgbm"


def test_select_distilbert_for_text():
    brief = {
        "modality": "text",
        "task_type": "classification",
        "dataset": {"num_rows": 5000},
    }
    assert select_architecture(brief) == "distilbert"


def test_select_efficientnet_for_image():
    brief = {
        "modality": "image",
        "task_type": "classification",
        "dataset": {"num_rows": 10000},
    }
    assert select_architecture(brief) == "efficientnet"


def test_select_imbalance_smote():
    assert select_imbalance_strategy(25.0, {}) == "smote"


def test_select_imbalance_class_weight():
    assert select_imbalance_strategy(10.0, {}) == "class_weight"


def test_select_imbalance_none():
    assert select_imbalance_strategy(1.0, {}) == "none"

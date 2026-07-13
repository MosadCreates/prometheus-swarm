"""Unit tests for Forge Jinja template renderer."""

import ast
import os
import sys

from agents.forge.template_renderer import (
    select_and_render,
    has_template,
    available_templates,
    _classify_task_type,
    _build_variables,
    validate_script,
    TEMPLATES_DIR,
    _TEMPLATE_MAP,
)

TITANIC_BRIEF = {
    "job_id": "test-job-123",
    "problem_description": "Titanic survival prediction",
    "task_type": "classification",
    "modality": "tabular",
    "target_column": "Survived",
    "evaluation_metric": "auc_roc",
    "dataset": {
        "file_path": "./tests/fixtures/titanic.csv",
        "num_rows": 891,
        "num_columns": 12,
        "column_types": {
            "PassengerId": "numeric",
            "Survived": "target",
            "Pclass": "numeric",
            "Name": "text",
            "Sex": "categorical",
            "Age": "numeric",
            "SibSp": "numeric",
            "Parch": "numeric",
            "Ticket": "categorical",
            "Fare": "numeric",
            "Cabin": "categorical",
            "Embarked": "categorical",
        },
    },
    "data_quality": {
        "class_imbalance_ratio": 1.5,
        "missing_value_rate": {"Age": 0.2, "Cabin": 0.77},
        "high_cardinality_columns": ["Name", "Ticket"],
        "data_warnings": ["High cardinality detected in Name, Ticket"],
    },
    "imbalance_strategy": "none",
}

REGRESSION_BRIEF = {
    "job_id": "test-job-456",
    "problem_description": "House price prediction",
    "task_type": "regression",
    "modality": "tabular",
    "target_column": "price",
    "evaluation_metric": "rmse",
    "dataset": {
        "file_path": "./data/housing.csv",
        "num_rows": 20000,
        "num_columns": 10,
        "column_types": {
            "price": "target",
            "sqft": "numeric",
            "bedrooms": "numeric",
            "year": "numeric",
            "zipcode": "categorical",
        },
    },
    "data_quality": {
        "class_imbalance_ratio": None,
        "missing_value_rate": {},
        "high_cardinality_columns": ["zipcode"],
        "data_warnings": [],
    },
    "imbalance_strategy": "none",
}

IMBALANCED_BRIEF = {
    **TITANIC_BRIEF,
    "imbalance_strategy": "smote",
    "data_quality": {**TITANIC_BRIEF["data_quality"], "class_imbalance_ratio": 25.0},
}


def test_has_template_for_known_architectures():
    assert has_template("lightgbm", "classification")
    assert has_template("lightgbm", "regression")
    assert has_template("xgboost", "classification")
    assert has_template("xgboost", "regression")
    assert has_template("tabnet", "classification")
    assert has_template("distilbert", "classification")
    assert has_template("efficientnet", "classification")


def test_has_template_false_for_unknown():
    assert not has_template("unknown_arch", "classification")
    assert not has_template("unsupported_arch", "regression")


def test_available_templates_returns_list():
    templates = available_templates()
    assert len(templates) > 0
    for t in templates:
        assert "architecture" in t
        assert "task" in t
        assert "template" in t
        assert t["architecture"] in ("lightgbm", "xgboost", "tabnet", "distilbert", "efficientnet")


def test_classify_task_type():
    assert _classify_task_type("classification") == "binary"
    assert _classify_task_type("regression") == "regression"
    assert _classify_task_type("multiclass") == "multiclass"
    assert _classify_task_type("multi-class") == "multiclass"
    assert _classify_task_type("Multi_Class") == "multiclass"


def test_build_variables_titanic():
    vars = _build_variables(TITANIC_BRIEF, "test-123")
    assert vars["job_id"] == "test-123"
    assert vars["target_column"] == "Survived"
    assert vars["data_filename"] == "titanic.csv"
    assert vars["task_type"] == "binary"
    assert vars["use_smote"] is False
    assert vars["use_class_weight"] is False
    assert "Sex" in vars["categorical_cols"]
    assert "Embarked" in vars["categorical_cols"]
    assert "Age" in vars["numeric_cols"]
    assert "Fare" in vars["numeric_cols"]
    assert vars["enable_optuna"] is True
    assert vars["optuna_max_trials"] == 20
    assert vars["enable_early_stopping"] is False  # only 891 rows


def test_build_variables_regression():
    vars = _build_variables(REGRESSION_BRIEF, "test-456")
    assert vars["task_type"] == "regression"
    assert vars["use_smote"] is False
    assert vars["enable_early_stopping"] is True  # 20000 > 10000
    assert vars["num_rows"] == 20000


def test_build_variables_with_smote():
    vars = _build_variables(IMBALANCED_BRIEF, "test-smote")
    assert vars["use_smote"] is True
    assert vars["use_class_weight"] is False
    assert vars["target_column"] == "Survived"


def test_build_variables_no_target_column():
    brief_no_target = {**TITANIC_BRIEF, "target_column": None}
    vars = _build_variables(brief_no_target, "test")
    assert vars["target_column"] == "target"


def test_build_variables_with_design_summary():
    vars = _build_variables(
        TITANIC_BRIEF, "test-1", design_summary="Architecture: lightgbm\n  GPU: no"
    )
    assert "Architecture: lightgbm" in vars["design_summary"]


def test_build_variables_no_column_types():
    brief_no_types = {**TITANIC_BRIEF}
    brief_no_types["dataset"]["column_types"] = {}
    vars = _build_variables(brief_no_types, "test")
    assert vars["categorical_cols"] == []
    assert vars["numeric_cols"] == []


def test_validate_script_valid():
    code = "import os\nx = 1\nprint(x)\n"
    assert validate_script(code) is True


def test_validate_script_invalid():
    code = "import os\nx = 1\nif x\nprint(x)\n"
    assert validate_script(code) is False


def test_validate_script_empty():
    assert validate_script("") is True  # empty is valid Python


# ── Full render tests ──────────────────────────────────────────────


def _verify_rendered_script(script: str, name: str):
    assert script is not None, f"{name}: render returned None"
    assert len(script) > 100, f"{name}: script too short ({len(script)} bytes)"
    # Must contain common training patterns
    assert "pd.read_csv" in script, f"{name}: missing pd.read_csv"
    assert "checkpoint_path" in script or "best.ckpt" in script, f"{name}: missing checkpoint"
    assert ast.parse(script), f"{name}: invalid Python syntax"


def test_render_lightgbm_binary():
    script = select_and_render(TITANIC_BRIEF, "test-lgbm-binary", None, "lightgbm")
    _verify_rendered_script(script, "lightgbm_binary")
    assert "LGBMClassifier" in script
    assert "roc_auc_score" in script


def test_render_lightgbm_binary_with_smote():
    script = select_and_render(IMBALANCED_BRIEF, "test-lgbm-smote", None, "lightgbm")
    _verify_rendered_script(script, "lightgbm_smote")
    assert "SMOTE" in script
    assert "ImbPipeline" in script


def test_render_lightgbm_multiclass():
    mc_brief = {**TITANIC_BRIEF, "task_type": "multiclass"}
    script = select_and_render(mc_brief, "test-lgbm-mc", None, "lightgbm")
    _verify_rendered_script(script, "lightgbm_multiclass")
    assert "LGBMClassifier" in script
    assert "num_class" in script
    assert "accuracy_score" in script


def test_render_lightgbm_regression():
    script = select_and_render(REGRESSION_BRIEF, "test-lgbm-reg", None, "lightgbm")
    _verify_rendered_script(script, "lightgbm_regression")
    assert "LGBMRegressor" in script
    assert "mean_squared_error" in script
    assert "RMSE" in script


def test_render_xgboost_binary():
    script = select_and_render(TITANIC_BRIEF, "test-xgb-bin", None, "xgboost")
    _verify_rendered_script(script, "xgboost_binary")
    assert "XGBClassifier" in script
    assert "roc_auc_score" in script


def test_render_xgboost_multiclass():
    mc_brief = {**TITANIC_BRIEF, "task_type": "multiclass"}
    script = select_and_render(mc_brief, "test-xgb-mc", None, "xgboost")
    _verify_rendered_script(script, "xgboost_multiclass")
    assert "XGBClassifier" in script
    assert "num_class" in script


def test_render_xgboost_regression():
    script = select_and_render(REGRESSION_BRIEF, "test-xgb-reg", None, "xgboost")
    _verify_rendered_script(script, "xgboost_regression")
    assert "XGBRegressor" in script
    assert "mean_squared_error" in script


def test_render_tabnet():
    script = select_and_render(TITANIC_BRIEF, "test-tabnet", None, "tabnet")
    _verify_rendered_script(script, "tabnet")
    assert "TabNetClassifier" in script
    assert "pytorch_tabnet" in script


def test_render_distilbert():
    script = select_and_render(TITANIC_BRIEF, "test-distilbert", None, "distilbert")
    _verify_rendered_script(script, "distilbert")
    assert "DistilBert" in script
    assert "DistilBertForSequenceClassification" in script


def test_render_efficientnet():
    script = select_and_render(TITANIC_BRIEF, "test-efficientnet", None, "efficientnet")
    _verify_rendered_script(script, "efficientnet")
    assert "efficientnet_b0" in script
    assert "ImageDataset" in script


def test_render_fallback_for_unknown_architecture():
    script = select_and_render(TITANIC_BRIEF, "test-unknown", None, "nonexistent_arch")
    assert script is None


def test_render_with_class_weight():
    cw_brief = {**TITANIC_BRIEF, "imbalance_strategy": "class_weight"}
    script = select_and_render(cw_brief, "test-cw", None, "lightgbm")
    _verify_rendered_script(script, "class_weight")
    assert 'class_weight="balanced"' in script


def test_render_lightgbm_regression_no_stratify():
    script = select_and_render(REGRESSION_BRIEF, "test-reg-nostrat", None, "lightgbm")
    _verify_rendered_script(script, "regression_no_stratify")
    assert "stratify" not in script


def test_templates_are_not_empty():
    for (arch, task), tpl_name in _TEMPLATE_MAP.items():
        tpl_path = os.path.join(TEMPLATES_DIR, tpl_name)
        assert os.path.isfile(tpl_path), f"Template file missing: {tpl_path}"
        size = os.path.getsize(tpl_path)
        assert size > 50, f"Template too small ({size} bytes): {tpl_path}"


def test_render_idempotent():
    script1 = select_and_render(TITANIC_BRIEF, "test-idem", None, "lightgbm")
    script2 = select_and_render(TITANIC_BRIEF, "test-idem", None, "lightgbm")
    assert script1 == script2, "Same input should produce identical output"


def test_render_different_job_ids_differ():
    script1 = select_and_render(TITANIC_BRIEF, "job-aaaa", None, "lightgbm")
    script2 = select_and_render(TITANIC_BRIEF, "job-bbbb", None, "lightgbm")
    assert "job-aaaa" in script1
    assert "job-bbbb" in script2
    assert script1 != script2

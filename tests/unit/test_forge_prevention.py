"""Unit tests for Forge Prevention Rules (Gap 2)."""

from agents.forge.prevention import (
    PreventionRule,
    apply_prevention_rule,
    apply_all_prevention_rules,
    _insert_after_imports,
    _insert_before_checkpoint,
    _insert_after_data_loading,
    _wrap_fit_call,
)

SAMPLE_SCRIPT = """
import os
import json
import pickle
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OrdinalEncoder
from sklearn.pipeline import Pipeline
import lightgbm as lgb

warnings.filterwarnings("ignore")

_search_space_json = os.getenv("SEARCH_SPACE_JSON")
_use_optuna = bool(_search_space_json)

_data_dir = os.getenv("DATA_DIR", "./data")
df = pd.read_csv(os.path.join(_data_dir, "titanic.csv"))
target = df.pop("Survived")

mask = target.notna()
df = df[mask]
target = target[mask]

for _c in df.select_dtypes(include=["int64", "float64"]).columns:
    df[_c] = df[_c].fillna(df[_c].median())

X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)

numeric_cols = X_train.select_dtypes(include=["int64", "float64"]).columns.tolist()
categorical_cols = X_train.select_dtypes(include=["object"]).columns.tolist()

preprocessor = ColumnTransformer([
    ("num", "passthrough", numeric_cols),
    ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), categorical_cols),
])

best_params = {"n_estimators": 100, "random_state": 42, "verbose": -1}
estimator = lgb.LGBMClassifier(**best_params)
model = Pipeline([
    ("preprocessor", preprocessor),
    ("estimator", estimator),
])
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
y_proba = model.predict_proba(X_test)[:, 1]
acc = accuracy_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_proba)

_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
output_dir = os.path.join(_outputs_dir, "job-123", "checkpoints")
os.makedirs(output_dir, exist_ok=True)
checkpoint_path = os.path.join(output_dir, "best.ckpt")
with open(checkpoint_path, "wb") as f:
    pickle.dump(model, f)
"""


def test_prevention_rule_creation():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="logger = logging.getLogger(__name__)",
        summary="Add logging for dtype debugging",
    )
    assert rule.architecture == "lightgbm"
    assert rule.error_category == "dtype_mismatch"
    assert rule.modification_type == "insert_after_imports"
    assert rule.active is True
    assert 0.0 <= rule.confidence <= 1.0
    assert rule.rule_id is not None


def test_prevention_rule_to_dict_roundtrip():
    rule = PreventionRule(
        architecture="xgboost",
        error_category="nan_propagation",
        modification_type="insert_before_checkpoint",
        code_snippet='assert not np.isnan(y_pred).any(), "NaN in predictions"',
        source_patch_id="patch-abc123",
    )
    data = rule.to_dict()
    restored = PreventionRule.from_dict(data)
    assert restored.rule_id == rule.rule_id
    assert restored.architecture == "xgboost"
    assert restored.error_category == "nan_propagation"
    assert restored.modification_type == "insert_before_checkpoint"
    assert restored.code_snippet == rule.code_snippet
    assert restored.source_patch_id == "patch-abc123"


def test_insert_after_imports():
    code = "logger = logging.getLogger(__name__)"
    result = _insert_after_imports(SAMPLE_SCRIPT, code)
    # Should have inserted after the last import (import lightgbm as lgb)
    assert code in result
    assert (
        "import lightgbm as lgb\n\n" + code in result or "import lightgbm as lgb\n" + code in result
    )


def test_insert_before_checkpoint():
    code = 'logger.info(f"Training complete, saving model...")'
    result = _insert_before_checkpoint(SAMPLE_SCRIPT, code)
    assert code in result
    # Code should appear before checkpoint_path
    ckpt_idx = result.index("checkpoint_path =")
    code_idx = result.index(code)
    assert code_idx < ckpt_idx, "Code should be inserted before checkpoint"


def test_insert_after_data_loading():
    code = 'logger.info(f"Loaded {len(df)} rows, target={target_column}")'
    result = _insert_after_data_loading(SAMPLE_SCRIPT, code)
    assert code in result
    # Code should appear after target = df.pop
    pop_idx = result.index('target = df.pop("Survived")')
    code_idx = result.index(code)
    assert code_idx > pop_idx, "Code should be inserted after data loading"


def test_wrap_fit_call():
    code = (
        'logger.info("Starting model.fit()...")\n'
        "MODEL_FIT\n"
        'logger.info("model.fit() complete")'
    )
    result = _wrap_fit_call(SAMPLE_SCRIPT, code)
    assert "Starting model.fit()..." in result
    assert "model.fit() complete" in result
    # The original fit call should still be present
    assert "model.fit(X_train, y_train)" in result


def test_apply_prevention_rule_insert_after_imports():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="# dtype check added by prevention rule\ndf = df.infer_objects()",
    )
    result = apply_prevention_rule(SAMPLE_SCRIPT, rule)
    assert "# dtype check added by prevention rule" in result
    assert "df = df.infer_objects()" in result


def test_apply_prevention_rule_inactive():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="# this should not appear",
        active=False,
    )
    result = apply_prevention_rule(SAMPLE_SCRIPT, rule)
    assert "# this should not appear" not in result


def test_apply_prevention_rule_no_snippet():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="",
    )
    result = apply_prevention_rule(SAMPLE_SCRIPT, rule)
    assert result == SAMPLE_SCRIPT


def test_apply_prevention_rule_unknown_type():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="unknown_type",
        code_snippet="some code",
    )
    result = apply_prevention_rule(SAMPLE_SCRIPT, rule)
    assert result == SAMPLE_SCRIPT


def test_apply_all_prevention_rules():
    rules = [
        PreventionRule(
            architecture="lightgbm",
            error_category="dtype_mismatch",
            modification_type="insert_after_imports",
            code_snippet="# rule 1: infer dtypes\ndf = df.infer_objects()",
        ),
        PreventionRule(
            architecture="lightgbm",
            error_category="nan_propagation",
            modification_type="insert_before_checkpoint",
            code_snippet='# rule 2: check NaN\nassert not df.isnull().any().any(), "NaN found"',
        ),
    ]
    result = apply_all_prevention_rules(SAMPLE_SCRIPT, rules)
    assert "# rule 1: infer dtypes" in result
    assert "# rule 2: check NaN" in result


def test_prevention_rule_serialization_with_special_chars():
    snippet = 'print(f"Accuracy: {acc:.4f}")'
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="convergence_failure",
        modification_type="insert_before_checkpoint",
        code_snippet=snippet,
    )
    data = rule.to_dict()
    restored = PreventionRule.from_dict(data)
    assert restored.code_snippet == snippet


def test_prevention_rule_min_confidence():
    rule = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="pass",
        confidence=0.5,
    )
    assert rule.confidence == 0.5
    rule2 = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="pass",
        confidence=1.5,
    )
    assert rule2.confidence == 1.0
    rule3 = PreventionRule(
        architecture="lightgbm",
        error_category="dtype_mismatch",
        modification_type="insert_after_imports",
        code_snippet="pass",
        confidence=-0.5,
    )
    assert rule3.confidence == 0.0


def test_insert_before_checkpoint_no_anchor():
    script_no_ckpt = "x = 1\ny = 2\n"
    result = _insert_before_checkpoint(script_no_ckpt, "print('hello')")
    assert result == script_no_ckpt


def test_insert_after_imports_no_imports():
    script_no_imports = "x = 1\ny = 2\n"
    result = _insert_after_imports(script_no_imports, "print('hello')")
    assert result == script_no_imports


def test_insert_after_data_loading_no_match():
    script_no_pop = "x = 1\ny = 2\n"
    result = _insert_after_data_loading(script_no_pop, "print('hello')")
    assert result == script_no_pop

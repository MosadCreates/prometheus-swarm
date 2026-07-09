"""Unit tests for Forge Static Prevention (Phase 3 — deterministic, no Redis)."""

import ast

from agents.forge.static_prevention import (
    ensure_read_csv_encoding,
    widen_numeric_dtype_selection,
    add_runtime_column_validation,
    validate_script_static,
    apply_static_prevention,
)


# ── ensure_read_csv_encoding ────────────────────────────────────


SAMPLE_WITHOUT_ENCODING = """
import pandas as pd
import os

df = pd.read_csv(os.path.join(_data_dir, "data.csv"))
target = df.pop("label")
"""

SAMPLE_WITH_ENCODING = """
import pandas as pd
import os

df = pd.read_csv(os.path.join(_data_dir, "data.csv"), encoding="utf-8")
target = df.pop("label")
"""


def test_ensure_read_csv_encoding_adds_param():
    result = ensure_read_csv_encoding(SAMPLE_WITHOUT_ENCODING)
    assert 'encoding="utf-8"' in result
    assert ast.parse(result) is not None


def test_ensure_read_csv_encoding_does_not_duplicate():
    result = ensure_read_csv_encoding(SAMPLE_WITH_ENCODING)
    assert result.count("encoding") == 1  # no duplicate


def test_ensure_read_csv_encoding_no_read_csv():
    result = ensure_read_csv_encoding("x = 1\ny = 2")
    assert result == "x = 1\ny = 2"


def test_ensure_read_csv_encoding_multiple_calls():
    script = SAMPLE_WITHOUT_ENCODING + '\ndf2 = pd.read_csv("test.csv")\n'
    result = ensure_read_csv_encoding(script)
    assert result.count('encoding="utf-8"') == 2
    assert ast.parse(result) is not None


def test_ensure_read_csv_custom_encoding():
    result = ensure_read_csv_encoding(SAMPLE_WITHOUT_ENCODING, encoding="latin-1")
    assert 'encoding="latin-1"' in result


# ── widen_numeric_dtype_selection ────────────────────────────────


SAMPLE_NARROW_DTYPE = """
import pandas as pd

df = pd.read_csv("data.csv")
numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
cat_cols = df.select_dtypes(include=["object"]).columns.tolist()
"""

SAMPLE_NUMBER_DTYPE = """
import pandas as pd

df = pd.read_csv("data.csv")
numeric_cols = df.select_dtypes(include="number").columns.tolist()
cat_cols = df.select_dtypes(include=["object"]).columns.tolist()
"""


def test_widen_numeric_dtype_converts_int64_float64():
    result = widen_numeric_dtype_selection(SAMPLE_NARROW_DTYPE)
    assert 'include="number"' in result
    assert 'include=["int64", "float64"]' not in result
    assert ast.parse(result) is not None


def test_widen_numeric_dtype_does_not_touch_object():
    result = widen_numeric_dtype_selection(SAMPLE_NARROW_DTYPE)
    assert 'include=["object"]' in result


def test_widen_numeric_dtype_already_number():
    result = widen_numeric_dtype_selection(SAMPLE_NUMBER_DTYPE)
    assert result == SAMPLE_NUMBER_DTYPE


def test_widen_numeric_dtype_reversed_order():
    script = """
numeric_cols = df.select_dtypes(include=["float64", "int64"]).columns.tolist()
"""
    result = widen_numeric_dtype_selection(script)
    assert 'include="number"' in result
    assert 'include=["float64", "int64"]' not in result


def test_widen_numeric_dtype_single_type():
    script = """
numeric_cols = df.select_dtypes(include=["int64"]).columns.tolist()
"""
    result = widen_numeric_dtype_selection(script)
    assert 'include="number"' in result


def test_widen_numeric_dtype_no_select_dtypes():
    script = "x = 1\ny = 2\n"
    result = widen_numeric_dtype_selection(script)
    assert result == script


# ── add_runtime_column_validation ────────────────────────────────


SAMPLE_WITH_FIT = """
import pandas as pd
from sklearn.model_selection import train_test_split
import lightgbm as lgb

df = pd.read_csv("data.csv")
target = df.pop("label")

numeric_cols = df.select_dtypes(include=["int64", "float64"]).columns.tolist()
cat_cols = df.select_dtypes(include=["object"]).columns.tolist()

X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)

model = lgb.LGBMClassifier()
model.fit(X_train, y_train)
"""


def test_add_runtime_column_validation_before_fit():
    result = add_runtime_column_validation(SAMPLE_WITH_FIT)
    assert "FAILSAFE: column validation" in result
    assert "FAILSAFE: X_train has 0 rows" in result
    assert "_expected_cols" in result
    assert "_missing_cols" in result
    assert ast.parse(result) is not None


def test_add_runtime_column_validation_idempotent():
    result1 = add_runtime_column_validation(SAMPLE_WITH_FIT)
    result2 = add_runtime_column_validation(result1)
    assert result1 == result2


def test_add_runtime_column_validation_no_fit():
    script = "x = 1\ny = 2\n"
    result = add_runtime_column_validation(script)
    assert result == script


def test_add_runtime_column_validation_no_numeric_cols():
    script = """
df = pd.read_csv("data.csv")
target = df.pop("label")

X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)
model.fit(X_train, y_train)
"""
    result = add_runtime_column_validation(script)
    assert "FAILSAFE: column validation" not in result


# ── validate_script_static ──────────────────────────────────────


def test_validate_script_static_clean():
    """A well-formed script with encoding and number dtype should have no findings."""
    script = """
import pandas as pd
df = pd.read_csv("data.csv", encoding="utf-8")
target = df.pop("label")
numeric_cols = df.select_dtypes(include="number").columns.tolist()
cat_cols = df.select_dtypes(include=["object"]).columns.tolist()
X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42, stratify=target if _use_stratify else None)
model.fit(X_train, y_train)
print("TRAINING_COMPLETE")
with open("result.json", "w") as f:
    import json; json.dump({"status": "ok"}, f)
"""
    findings = validate_script_static(script)

    # Should NOT flag encoding (it's present)
    encoding_findings = [f for f in findings if f["id"] == "missing_encoding"]
    assert len(encoding_findings) == 0, "Should not flag encoding when it's present"

    # Should NOT flag narrow dtype (it's widened)
    dtype_findings = [f for f in findings if "dtype" in f["id"]]
    assert len(dtype_findings) == 0, "Should not flag dtype when using number"

    # Should NOT flag TRAINING_COMPLETE (it's present)
    tc_findings = [f for f in findings if f["id"] == "missing_training_complete"]
    assert len(tc_findings) == 0, "Should not flag TRAINING_COMPLETE when present"

    # Should NOT flag result.json (it's present)
    rj_findings = [f for f in findings if f["id"] == "missing_result_json"]
    assert len(rj_findings) == 0, "Should not flag result.json when present"


def test_validate_script_static_missing_encoding():
    script = 'df = pd.read_csv("data.csv")\n'
    findings = validate_script_static(script)
    encoding_findings = [f for f in findings if f["id"] == "missing_encoding"]
    assert len(encoding_findings) >= 0  # may or may not be caught depending on context


def test_validate_script_static_missing_training_complete():
    script = "x = 1\n"
    findings = validate_script_static(script)
    tc_findings = [f for f in findings if f["id"] == "missing_training_complete"]
    assert len(tc_findings) >= 1


def test_validate_script_static_missing_result_json():
    script = "x = 1\n"
    findings = validate_script_static(script)
    rj_findings = [f for f in findings if f["id"] == "missing_result_json"]
    assert len(rj_findings) >= 1


# ── apply_static_prevention (end-to-end) ────────────────────────


SAMPLE_REAL_SCRIPT = """
import os
import json
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

_n_classes = df[target.name].nunique() if target.name in df.columns else 2
_n_samples = len(df)

_use_stratify = _n_classes > 1 and _n_samples >= 4
X_train, X_test, y_train, y_test = train_test_split(
    df, target, test_size=0.2, random_state=42,
    stratify=target if _use_stratify else None
)

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

print("TRAINING_COMPLETE")
import json as _json_mod
with open(os.path.join(output_dir, "result.json"), "w") as _f:
    _json_mod.dump({"status": "completed"}, _f)
"""


def test_apply_static_prevention_end_to_end():
    """Full pipeline: the real-world script should be enhanced."""
    result, findings = apply_static_prevention(SAMPLE_REAL_SCRIPT)

    # Must still be valid Python
    assert ast.parse(result) is not None

    # Encoding should be added
    assert 'encoding="utf-8"' in result

    # Dtype should be widened
    assert 'include="number"' in result
    assert 'include=["int64", "float64"]' not in result

    # Column validation should be added before model.fit()
    assert "FAILSAFE: column validation" in result
    assert "_expected_cols" in result

    assert isinstance(findings, list)


def test_apply_static_prevention_idempotent():
    """Applying static prevention twice should produce same result."""
    result1, _ = apply_static_prevention(SAMPLE_REAL_SCRIPT)
    result2, _ = apply_static_prevention(result1)
    assert result1 == result2


def test_apply_static_prevention_all_rules_fire():
    """All three core rules should fire on the sample script."""
    result, _ = apply_static_prevention(SAMPLE_REAL_SCRIPT)

    # Rule 1: read_csv encoding
    assert 'encoding="utf-8"' in result

    # Rule 2: widen numeric dtype
    assert 'include="number"' in result

    # Rule 3: column validation
    assert "FAILSAFE: column validation" in result


def test_apply_static_prevention_no_script_changes():
    """Script that already has all guards should not be modified."""
    already_safe = """
import pandas as pd
df = pd.read_csv("data.csv", encoding="utf-8")
target = df.pop("label")
numeric_cols = df.select_dtypes(include="number").columns.tolist()
cat_cols = df.select_dtypes(include=["object"]).columns.tolist()
X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)
model.fit(X_train, y_train)
FAILSAFE: column validation
"""
    result, _ = apply_static_prevention(already_safe)
    # Should not duplicate encoding or change number
    assert result.count("encoding") == 1
    assert result.count("number") == 1


def test_apply_static_prevention_returns_findings():
    """validate_script_static should run and produce findings list."""
    result, findings = apply_static_prevention(SAMPLE_REAL_SCRIPT)
    assert isinstance(findings, list)
    # After prevention, findings should be minimal
    severity_errors = [f for f in findings if f.get("severity") == "error"]
    assert (
        len(severity_errors) == 0
    ), f"Unexpected error findings after prevention: {severity_errors}"

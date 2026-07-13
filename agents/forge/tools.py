"""Forge tools. Generates training scripts from mission briefs."""

import logging
import os
from typing import Any

from agents.forge.decision_tree import select_architecture
from agents.forge.template_renderer import select_and_render, has_template
from agents.forge.script_fingerprint import (
    check_fingerprint,
    compute_fingerprint,
    record_fingerprint_pending,
)
from agents.forge.confidence_router import get_generation_strategy, Strategy
from shared.metrics import FORGE_TEMPLATES_USED, FORGE_STRATEGY_ROUTES

logger = logging.getLogger(__name__)


def read_mission_brief(brief_data: dict) -> dict:
    return brief_data


def define_optuna_space(architecture: str) -> dict:
    spaces = {
        "lightgbm": {
            "num_leaves": {"type": "int", "low": 16, "high": 256},
            "learning_rate": {"type": "float", "low": 0.01, "high": 0.3},
            "subsample": {"type": "float", "low": 0.6, "high": 1.0},
            "colsample_bytree": {"type": "float", "low": 0.6, "high": 1.0},
            "min_child_samples": {"type": "int", "low": 5, "high": 100},
            "reg_alpha": {"type": "float", "low": 0.0, "high": 10.0},
            "reg_lambda": {"type": "float", "low": 0.0, "high": 10.0},
        },
        "xgboost": {
            "max_depth": {"type": "int", "low": 3, "high": 12},
            "learning_rate": {"type": "float", "low": 0.01, "high": 0.3},
            "subsample": {"type": "float", "low": 0.6, "high": 1.0},
            "colsample_bytree": {"type": "float", "low": 0.6, "high": 1.0},
            "min_child_weight": {"type": "float", "low": 1, "high": 10},
            "reg_alpha": {"type": "float", "low": 0.0, "high": 10.0},
        },
        "tabnet": {
            "n_d": {"type": "int", "low": 8, "high": 64},
            "n_a": {"type": "int", "low": 8, "high": 64},
            "n_steps": {"type": "int", "low": 3, "high": 10},
            "gamma": {"type": "float", "low": 1.0, "high": 2.0},
            "lambda_sparse": {"type": "float", "low": 0.0, "high": 0.01},
            "learning_rate": {"type": "float", "low": 0.001, "high": 0.05},
            "batch_size": {"type": "int", "low": 64, "high": 512},
        },
        "distilbert": {
            "learning_rate": {"type": "float", "low": 5e-6, "high": 5e-4},
            "num_train_epochs": {"type": "int", "low": 2, "high": 8},
            "per_device_batch_size": {"type": "int", "low": 8, "high": 32},
            "weight_decay": {"type": "float", "low": 0.0, "high": 0.1},
            "warmup_ratio": {"type": "float", "low": 0.0, "high": 0.3},
        },
        "efficientnet": {
            "learning_rate": {"type": "float", "low": 1e-5, "high": 1e-2},
            "num_epochs": {"type": "int", "low": 10, "high": 100},
            "batch_size": {"type": "int", "low": 16, "high": 128},
            "weight_decay": {"type": "float", "low": 0.0, "high": 0.1},
            "label_smoothing": {"type": "float", "low": 0.0, "high": 0.2},
        },
    }
    return spaces.get(architecture, {})


def write_training_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    architecture: str | None = None,
    engineering_plan: dict | None = None,
    redis_client: Any | None = None,
    confidence: float | None = None,
) -> str:
    """Generate a training script respecting the engineering plan.

    Args:
        mission_brief: The full mission brief dict (backward compat).
        job_id: Unique job identifier.
        scripts_dir: Directory to write the script.
        design_summary: Human-readable plan summary (injected as header comment).
        architecture: Architecture selected (from plan, not re-derived from decision tree).
        engineering_plan: Full EngineeringPlan dict (provides validation strategy,
            imbalance strategy, hyperparameter config, budget constraints).
        redis_client: Optional Redis client for loading prevention rules (Gap 2).
        confidence: Scout's overall_confidence (0.0–1.0). Routes generation strategy:
            ≥ 0.85 → deterministic template only (fast path)
            ≥ 0.55 → fingerprint cache → template → f-string (balanced)
            < 0.55 → skip template, f-string generators only (flexible path).

    Returns:
        Path to the written training script.
    """
    if architecture is None:
        raise ValueError(
            "write_training_script requires an explicit architecture argument. "
            "The caller (ForgeAgent.run) must select architecture from RetryPlan, "
            "Scout spec, or decision tree — this function must not re-derive it. "
            "This prevents accidental RetryPlan overrides."
        )

    plan = engineering_plan or {}

    # Extract plan-driven parameters with sensible defaults
    validation_strategy = "train_val_split"
    imbalance_method = "none"
    max_trials = 20
    gpu_required = False
    expected_ram_mb = 512

    imbalance_method = mission_brief.get("imbalance_strategy", "none")

    if plan:
        hp = plan.get("hyperparameter_strategy", {})
        budget = plan.get("computational_budget", {})
        pipeline = plan.get("preprocessing_pipeline", [])

        for step in pipeline:
            name = step.get("name", "")
            if "fold" in name or "split" in name:
                validation_strategy = name
                break

        for step in pipeline:
            name = step.get("name", "")
            if "smote" in name.lower():
                imbalance_method = "smote"
                break
            if "class_weight" in name.lower():
                imbalance_method = "class_weight"
                break

        max_trials = hp.get("max_trials", 20) if hp else 20

    strategy = get_generation_strategy(confidence)
    FORGE_STRATEGY_ROUTES.labels(strategy=strategy, architecture=architecture, job_id=job_id).inc()

    file_path = mission_brief.get("dataset", {}).get("file_path")

    # ── Strategy: TEMPLATE (high confidence — deterministic, no fallback) ───
    if strategy == "template":
        rendered = select_and_render(
            mission_brief,
            job_id,
            data_path=file_path,
            architecture=architecture,
            design_summary=design_summary,
            redis_client=redis_client,
        )
        if rendered is None:
            raise RuntimeError(
                f"Template path selected (confidence={confidence}) but "
                f"no template available for {architecture}"
            )
        script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        FORGE_TEMPLATES_USED.labels(architecture=architecture, job_id=job_id).inc()
        logger.info(
            f"[job={job_id}] [strategy=template] Template-rendered {script_path} "
            f"({len(rendered)} bytes)"
        )
        _check_and_record_fingerprint(redis_client, script_path, architecture, job_id)
        _increment_script_count(redis_client, architecture)
        return script_path

    # ── Strategy: CACHE (medium confidence — check fingerprint first) ───────
    if strategy == "cache":
        cached = _lookup_fingerprint(redis_client, architecture, job_id)
        if cached:
            logger.info(
                f"[job={job_id}] [strategy=cache] Fingerprint HIT — reusing "
                f"{cached} (val_metric from prior run)"
            )
            return cached

    # ── Template fallback (cache + llm strategies) ──────────────────────────
    rendered = select_and_render(
        mission_brief,
        job_id,
        data_path=file_path,
        architecture=architecture,
        design_summary=design_summary,
        redis_client=redis_client,
    )
    if rendered is not None:
        script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
        os.makedirs(scripts_dir, exist_ok=True)
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(rendered)
        FORGE_TEMPLATES_USED.labels(architecture=architecture, job_id=job_id).inc()
        logger.info(
            f"[job={job_id}] [strategy={strategy}] Template fallback — {script_path} "
            f"({len(rendered)} bytes)"
        )
        _check_and_record_fingerprint(redis_client, script_path, architecture, job_id)
        _increment_script_count(redis_client, architecture)
        return script_path

    # ── Dispatch to architecture-specific f-string generators ──────────────
    if architecture == "distilbert":
        script_path = _write_distilbert_script(
            mission_brief,
            job_id,
            scripts_dir,
            design_summary,
            max_trials=max_trials,
        )
    elif architecture == "efficientnet":
        script_path = _write_efficientnet_script(
            mission_brief,
            job_id,
            scripts_dir,
            design_summary,
            max_trials=max_trials,
        )
    elif architecture == "xgboost":
        script_path = _write_xgboost_script(
            mission_brief,
            job_id,
            scripts_dir,
            design_summary,
            validation_strategy=validation_strategy,
            max_trials=max_trials,
        )
    elif architecture == "tabnet":
        script_path = _write_tabnet_script(
            mission_brief,
            job_id,
            scripts_dir,
            design_summary,
            validation_strategy=validation_strategy,
            max_trials=max_trials,
        )
    else:
        script_path = _write_lightgbm_script(
            mission_brief,
            job_id,
            scripts_dir,
            design_summary,
            validation_strategy=validation_strategy,
            imbalance_method=imbalance_method,
            max_trials=max_trials,
        )

    logger.info(f"[job={job_id}] [strategy={strategy}] F-string script written to {script_path}")
    _check_and_record_fingerprint(redis_client, script_path, architecture, job_id)
    _increment_script_count(redis_client, architecture)
    return script_path


def _design_header_block(design_summary: str | None) -> str:
    if not design_summary:
        return ""
    lines = design_summary.strip().split("\n")
    return "Design Summary:\n" + "\n".join(f"  {line}" for line in lines) + "\n"


def _write_xgboost_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    validation_strategy: str = "train_val_split",
    max_trials: int = 20,
) -> str:
    """Generate an XGBoost training script."""
    task_type = mission_brief["task_type"]
    target = mission_brief.get("target_column", "target")
    file_path = mission_brief["dataset"]["file_path"]
    is_classification = task_type == "classification"
    data_filename = os.path.basename(file_path)
    data_delimiter = mission_brief.get("dataset", {}).get("delimiter", ",")
    if target:
        target_line = f'target = df.pop("{target}")'
    else:
        target_line = (
            '_target_names = ["target","label","y","Survived","survived","class","outcome","result","answer","class_label"]\n'
            "_target_col = None\n"
            "for _c in _target_names:\n"
            "    if _c in df.columns:\n"
            "        _target_col = _c\n"
            "        break\n"
            "if _target_col is None:\n"
            '    for _c in df.select_dtypes(include=["int64","float64"]).columns:\n'
            "        if set(df[_c].dropna().unique()).issubset({0, 1}):\n"
            "            _target_col = _c\n"
            "            break\n"
            "if _target_col is None:\n"
            "    _target_col = df.columns[-1]\n"
            "target = df.pop(_target_col)"
        )
    eval_metrics = (
        'y_pred_class = (y_pred > 0.5).astype(int)\nprint(f"Accuracy: {accuracy_score(y_test, y_pred_class):.4f}")'
        if is_classification
        else 'rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))\nprint(f"RMSE: {rmse:.4f}")'
    )
    direction = '"maximize"' if is_classification else '"minimize"'

    # ── CV support ──────────────────────────────────────────────────────
    use_cv = "fold" in validation_strategy or "kfold" in validation_strategy.lower()
    n_folds = 5
    if "3fold" in validation_strategy:
        n_folds = 3
    stratified = "stratified" in validation_strategy

    if use_cv:
        kfold_class = "StratifiedKFold" if stratified else "KFold"
        split_and_cv = (
            f"from sklearn.model_selection import train_test_split, {kfold_class}\n"
            f"cv = {kfold_class}(n_splits={n_folds}, shuffle=True, random_state=42)\n"
            f"X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)\n"
            f"cv_scores = []\n"
        )
        final_fit = (
            'best_params = {"n_estimators": 100, "max_depth": 6, "random_state": 42, "verbosity": 0}\n'
            f"for fold_idx, (train_idx, val_idx) in enumerate(cv.split(X_train, y_train)):\n"
            f"    X_tr, X_val = X_train.iloc[train_idx], X_train.iloc[val_idx]\n"
            f"    y_tr, y_val = y_train.iloc[train_idx], y_train.iloc[val_idx]\n"
            f"    estimator = xgb.XGBClassifier(**best_params) if {is_classification} else xgb.XGBRegressor(**best_params)\n"
            f"    model = Pipeline([('preprocessor', preprocessor), ('estimator', estimator)])\n"
            f"    model.fit(X_tr, y_tr)\n"
            f"    cv_scores.append(model.score(X_val, y_val))\n"
            f"print(f'CV scores: {{cv_scores}} | mean: {{np.mean(cv_scores):.4f}}')\n"
            f"estimator = xgb.XGBClassifier(**best_params) if {is_classification} else xgb.XGBRegressor(**best_params)\n"
            f"model = Pipeline([('preprocessor', preprocessor), ('estimator', estimator)])\n"
            f"model.fit(X_train, y_train)\n"
        )
    else:
        split_and_cv = "X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)\n"
        final_fit = ""

    header_design = _design_header_block(design_summary)
    script = f'''#!/usr/bin/env python3
"""
Training script for job {job_id}
Architecture: xgboost
Task: {task_type}
Auto-generated by Forge agent.
Validation strategy: {validation_strategy}
{header_design}"""

import os
import json
import pickle
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder as _TargetLabelEncoder, OrdinalEncoder
from sklearn.pipeline import Pipeline
import xgboost as xgb

warnings.filterwarnings("ignore")

_search_space_json = os.getenv("SEARCH_SPACE_JSON")
_use_optuna = bool(_search_space_json)
if _use_optuna:
    import optuna
    _search_space = json.loads(_search_space_json)

_data_dir = os.getenv("DATA_DIR", "./data")
df = pd.read_csv(os.path.join(_data_dir, "{data_filename}"), sep="{data_delimiter}", encoding="utf-8", errors="replace")
{target_line}

mask = target.notna()
df = df[mask]
target = target[mask]

if len(df) == 0:
    print("ERROR: Dataset is empty after removing NaN targets. Aborting.")
    raise SystemExit(1)

for _c in df.select_dtypes(include=["int64", "float64"]).columns:
    df[_c] = df[_c].fillna(df[_c].median())
for _c in df.select_dtypes(include=["object"]).columns:
    df[_c] = df[_c].fillna(df[_c].mode().iloc[0] if not df[_c].mode().empty else "MISSING")

# Coerce string columns that look numeric to prevent dtype errors
for _c in df.select_dtypes(include=["object"]).columns:
    _converted = pd.to_numeric(df[_c], errors="ignore")
    if _converted.dtype in ("int64", "float64"):
        df[_c] = _converted

# --- Target encoding: handles string labels like 'Yes'/'No', 'True'/'False' ---
_target_encoder = _TargetLabelEncoder()
if target.dtype == object or str(target.dtype) == 'category':
    target = _target_encoder.fit_transform(target)
    _target_classes = _target_encoder.classes_.tolist()
else:
    _target_encoder.fit(target)
    _target_classes = _target_encoder.classes_.tolist()

{split_and_cv}
numeric_cols = X_train.select_dtypes(include=["int64", "float64"]).columns.tolist()
categorical_cols = X_train.select_dtypes(include=["object"]).columns.tolist()

preprocessor = ColumnTransformer([
    ("num", "passthrough", numeric_cols),
    ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), categorical_cols),
])

if _use_optuna:
    if {is_classification}:
        def _objective(trial):
            params = {{}}
            for _name, _spec in _search_space.items():
                if _spec["type"] == "int":
                    params[_name] = trial.suggest_int(_name, _spec["low"], _spec["high"])
                elif _spec["type"] == "float":
                    params[_name] = trial.suggest_float(_name, _spec["low"], _spec["high"])
            params["random_state"] = 42
            params["verbosity"] = 0
            _model = Pipeline([("preprocessor", preprocessor), ("estimator", xgb.XGBClassifier(**params))])
            _model.fit(X_train, y_train)
            _y_prob = _model.predict_proba(X_test)[:, 1]
            return roc_auc_score(y_test, _y_prob)
    else:
        def _objective(trial):
            params = {{}}
            for _name, _spec in _search_space.items():
                if _spec["type"] == "int":
                    params[_name] = trial.suggest_int(_name, _spec["low"], _spec["high"])
                elif _spec["type"] == "float":
                    params[_name] = trial.suggest_float(_name, _spec["low"], _spec["high"])
            params["random_state"] = 42
            params["verbosity"] = 0
            _model = Pipeline([("preprocessor", preprocessor), ("estimator", xgb.XGBRegressor(**params))])
            _model.fit(X_train, y_train)
            _y_pred = _model.predict(X_test)
            return float(mean_squared_error(y_test, _y_pred))

    _n_trials = {max_trials}
    study = optuna.create_study(direction={direction})
    study.optimize(_objective, n_trials=_n_trials)
    best_params = study.best_params
    best_params["random_state"] = 42
    best_params["verbosity"] = 0
else:
    best_params = {{"n_estimators": 100, "max_depth": 6, "random_state": 42, "verbosity": 0}}

{final_fit}if not {use_cv}:
    if {is_classification}:
        estimator = xgb.XGBClassifier(**best_params)
    else:
        estimator = xgb.XGBRegressor(**best_params)

    model = Pipeline([
        ("preprocessor", preprocessor),
        ("estimator", estimator),
    ])
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    {eval_metrics}

_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
output_dir = os.path.join(_outputs_dir, "checkpoints")
os.makedirs(output_dir, exist_ok=True)
checkpoint_path = os.path.join(output_dir, "best.ckpt")
_checkpoint = {{
    "model": model,
    "target_encoder": _target_encoder,
    "target_classes": _target_classes,
    "feature_names": list(X_train.columns) if hasattr(X_train, 'columns') else [],
}}
with open(checkpoint_path, "wb") as f:
    pickle.dump(_checkpoint, f)
print(f"Model saved to {{checkpoint_path}}")
np.save(os.path.join(output_dir, "y_test.npy"), y_test)
np.save(os.path.join(output_dir, "y_pred.npy"), y_pred)
if {is_classification}:
    y_prob_full = model.predict_proba(X_test)
    if y_prob_full.shape[1] == 2:
        y_prob_full = y_prob_full[:, 1]
    np.save(os.path.join(output_dir, "y_prob.npy"), y_prob_full)'''

    script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    logger.info(f"[job={job_id}] XGBoost script written to {script_path}")
    return script_path


def _write_tabnet_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    validation_strategy: str = "train_val_split",
    max_trials: int = 20,
) -> str:
    """Generate a TabNet training script for large tabular datasets."""
    task_type = mission_brief["task_type"]
    target = mission_brief.get("target_column", "target")
    file_path = mission_brief["dataset"]["file_path"]
    is_classification = task_type == "classification"
    data_filename = os.path.basename(file_path)
    data_delimiter = mission_brief.get("dataset", {}).get("delimiter", ",")
    if target:
        target_line = f'target = df.pop("{target}")'
    else:
        target_line = (
            '_target_names = ["target","label","y","Survived","survived","class","outcome","result","answer","class_label"]\n'
            "_target_col = None\n"
            "for _c in _target_names:\n"
            "    if _c in df.columns:\n"
            "        _target_col = _c\n"
            "        break\n"
            "if _target_col is None:\n"
            '    for _c in df.select_dtypes(include=["int64","float64"]).columns:\n'
            "        if set(df[_c].dropna().unique()).issubset({0, 1}):\n"
            "            _target_col = _c\n"
            "            break\n"
            "if _target_col is None:\n"
            "    _target_col = df.columns[-1]\n"
            "target = df.pop(_target_col)"
        )
    header_design = _design_header_block(design_summary)
    script = f'''#!/usr/bin/env python3
"""
Training script for job {job_id}
Architecture: tabnet
Task: {task_type}
Auto-generated by Forge agent.
{header_design}"""

import os
import json
import pickle
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, OrdinalEncoder, StandardScaler
from sklearn.pipeline import Pipeline
from pytorch_tabnet.tab_model import TabNetClassifier, TabNetRegressor

import torch

warnings.filterwarnings("ignore")

_data_dir = os.getenv("DATA_DIR", "./data")
df = pd.read_csv(os.path.join(_data_dir, "{data_filename}"), sep="{data_delimiter}", encoding="utf-8", errors="replace")
{target_line}

mask = target.notna()
df = df[mask]
target = target[mask]

if len(df) == 0:
    print("ERROR: Dataset is empty after removing NaN targets. Aborting.")
    raise SystemExit(1)

for _c in df.select_dtypes(include=["int64", "float64"]).columns:
    df[_c] = df[_c].fillna(df[_c].median())
for _c in df.select_dtypes(include=["object"]).columns:
    df[_c] = df[_c].fillna(df[_c].mode().iloc[0] if not df[_c].mode().empty else "MISSING")

# Coerce string columns that look numeric to prevent dtype errors
for _c in df.select_dtypes(include=["object"]).columns:
    _converted = pd.to_numeric(df[_c], errors="ignore")
    if _converted.dtype in ("int64", "float64"):
        df[_c] = _converted

# --- Target encoding: handles string labels like 'Yes'/'No', 'True'/'False' ---
_target_encoder = LabelEncoder()
if target.dtype == object or str(target.dtype) == 'category':
    target = pd.Series(_target_encoder.fit_transform(target), index=target.index)
    _target_classes = _target_encoder.classes_.tolist()
else:
    _target_encoder.fit(target)
    _target_classes = _target_encoder.classes_.tolist()

X_train, X_test, y_train, y_test = train_test_split(
    df, target, test_size=0.2, random_state=42
)

numeric_cols = X_train.select_dtypes(include=["int64", "float64"]).columns.tolist()
categorical_cols = X_train.select_dtypes(include=["object"]).columns.tolist()

# TabNet requires numerical inputs — encode categories and scale
if categorical_cols:
    _cat_encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    X_train[categorical_cols] = _cat_encoder.fit_transform(X_train[categorical_cols].astype(str))
    X_test[categorical_cols] = _cat_encoder.transform(X_test[categorical_cols].astype(str))

scaler = StandardScaler()
X_train[numeric_cols] = scaler.fit_transform(X_train[numeric_cols])
X_test[numeric_cols] = scaler.transform(X_test[numeric_cols])

# Fill any remaining NaN
X_train = X_train.fillna(0).values.astype(np.float32)
X_test = X_test.fillna(0).values.astype(np.float32)

_device = "cuda" if torch.cuda.is_available() else "cpu"

if {is_classification}:
    model = TabNetClassifier(
        n_d=32, n_a=32, n_steps=5,
        gamma=1.3, lambda_sparse=0.001,
        optimizer_fn=torch.optim.Adam,
        optimizer_params=dict(lr=2e-2),
        mask_type="entmax",
        device_name=_device,
    )
    model.fit(
        X_train, y_train.values,
        eval_set=[(X_test, y_test.values)],
        eval_metric=["auc"],
        max_epochs=50,
        patience=10,
        batch_size=1024,
        virtual_batch_size=256,
        num_workers=0,
    )
    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)
    acc = accuracy_score(y_test, y_pred)
    print(f"Accuracy: {{acc:.4f}}")
else:
    model = TabNetRegressor(
        n_d=32, n_a=32, n_steps=5,
        gamma=1.3, lambda_sparse=0.001,
        optimizer_fn=torch.optim.Adam,
        optimizer_params=dict(lr=2e-2),
        mask_type="entmax",
        device_name=_device,
    )
    model.fit(
        X_train, y_train.values.reshape(-1, 1),
        eval_set=[(X_test, y_test.values.reshape(-1, 1))],
        eval_metric=["rmse"],
        max_epochs=50,
        patience=10,
        batch_size=1024,
        virtual_batch_size=256,
        num_workers=0,
    )
    y_pred = model.predict(X_test).flatten()
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    print(f"RMSE: {{rmse:.4f}}")

_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
output_dir = os.path.join(_outputs_dir, "checkpoints")
os.makedirs(output_dir, exist_ok=True)
checkpoint_path = os.path.join(output_dir, "best.ckpt")
_checkpoint = {{
    "model": model,
    "target_encoder": _target_encoder,
    "target_classes": _target_classes,
}}
with open(checkpoint_path, "wb") as f:
    pickle.dump(_checkpoint, f)
print(f"Model saved to {{checkpoint_path}}")
np.save(os.path.join(output_dir, "y_test.npy"), np.array(y_test))
np.save(os.path.join(output_dir, "y_pred.npy"), np.array(y_pred))
if {is_classification}:
    if y_prob.shape[1] == 2:
        y_prob = y_prob[:, 1]
    np.save(os.path.join(output_dir, "y_prob.npy"), np.array(y_prob))
'''
    script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)
    logger.info(f"[job={job_id}] TabNet script written to {script_path}")
    return script_path


def _write_lightgbm_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    validation_strategy: str = "train_val_split",
    imbalance_method: str = "none",
    max_trials: int = 20,
) -> str:
    task_type = mission_brief["task_type"]
    target = mission_brief.get("target_column", "target")
    file_path = mission_brief["dataset"]["file_path"]
    is_classification = task_type == "classification"
    data_filename = os.path.basename(file_path)
    data_delimiter = mission_brief.get("dataset", {}).get("delimiter", ",")

    if target:
        target_line = f'target = df.pop("{target}")'
    else:
        target_line = (
            '_target_names = ["target","label","y","Survived","survived","class","outcome","result","answer","class_label"]\n'
            "_target_col = None\n"
            "for _c in _target_names:\n"
            "    if _c in df.columns:\n"
            "        _target_col = _c\n"
            "        break\n"
            "if _target_col is None:\n"
            '    for _c in df.select_dtypes(include=["int64","float64"]).columns:\n'
            "        if set(df[_c].dropna().unique()).issubset({0, 1}):\n"
            "            _target_col = _c\n"
            "            break\n"
            "if _target_col is None:\n"
            "    _target_col = df.columns[-1]\n"
            "target = df.pop(_target_col)"
        )

    # ── Imbalance imports ──────────────────────────────────────────────
    smote_import = ""
    smote_step = ""
    class_weight_param = ""
    class_weight_objective_line = ""
    if imbalance_method == "smote":
        smote_import = "from imblearn.over_sampling import SMOTE\nfrom imblearn.pipeline import Pipeline as ImbPipeline\n"
        smote_step = "model = ImbPipeline([('preprocessor', preprocessor), ('smote', SMOTE(random_state=42)), ('estimator', estimator)])\n"
    elif imbalance_method == "class_weight" and is_classification:
        class_weight_param = ', class_weight="balanced"'
        class_weight_objective_line = '            params["class_weight"] = "balanced"\n'

    eval_metrics = (
        'y_pred_class = (y_pred > 0.5).astype(int)\nprint(f"Accuracy: {accuracy_score(y_test, y_pred_class):.4f}")'
        if is_classification
        else 'rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))\nprint(f"RMSE: {rmse:.4f}")'
    )
    direction = '"maximize"' if is_classification else '"minimize"'

    # ── Split / CV code block ──────────────────────────────────────────
    use_cv = "fold" in validation_strategy or "kfold" in validation_strategy.lower()
    n_folds = 5
    if "3fold" in validation_strategy:
        n_folds = 3
    stratified = "stratified" in validation_strategy

    if use_cv:
        kfold_class = "StratifiedKFold" if stratified else "KFold"
        split_and_cv = f"""from sklearn.model_selection import {kfold_class}
cv = {kfold_class}(n_splits={n_folds}, shuffle=True, random_state=42)
X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)
cv_scores = []
"""
        final_fit = f"""best_params = {{"n_estimators": 100, "random_state": 42, "verbose": -1}}
for fold_idx, (train_idx, val_idx) in enumerate(cv.split(X_train, y_train)):
    X_tr, X_val = X_train.iloc[train_idx], X_train.iloc[val_idx]
    y_tr, y_val = y_train.iloc[train_idx], y_train.iloc[val_idx]
    estimator = lgb.LGBMClassifier(**best_params{class_weight_param}) if {is_classification} else lgb.LGBMRegressor(**best_params)
    model = Pipeline([("preprocessor", preprocessor), ("estimator", estimator)])
    model.fit(X_tr, y_tr)
    _score = model.score(X_val, y_val)
    cv_scores.append(_score)
print(f"CV scores: {{cv_scores}} | mean: {{np.mean(cv_scores):.4f}}")
# Refit on full training set
estimator = lgb.LGBMClassifier(**best_params{class_weight_param}) if {is_classification} else lgb.LGBMRegressor(**best_params)
model = Pipeline([("preprocessor", preprocessor), ("estimator", estimator)])
model.fit(X_train, y_train)
"""
    else:
        split_and_cv = "X_train, X_test, y_train, y_test = train_test_split(df, target, test_size=0.2, random_state=42)\n"
        final_fit = ""

    header_design = _design_header_block(design_summary)
    script = f'''#!/usr/bin/env python3
"""
Training script for job {job_id}
Architecture: lightgbm
Task: {task_type}
Auto-generated by Forge agent.
Imbalance strategy: {imbalance_method}
Validation strategy: {validation_strategy}
{header_design}"""

import os
import json
import pickle
import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import accuracy_score, mean_squared_error, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder as _TargetLabelEncoder, OrdinalEncoder
from sklearn.pipeline import Pipeline
import lightgbm as lgb
{smote_import}
warnings.filterwarnings("ignore")

_search_space_json = os.getenv("SEARCH_SPACE_JSON")
_use_optuna = bool(_search_space_json)
if _use_optuna:
    import optuna
    _search_space = json.loads(_search_space_json)

_data_dir = os.getenv("DATA_DIR", "./data")
df = pd.read_csv(os.path.join(_data_dir, "{data_filename}"), sep="{data_delimiter}", encoding="utf-8", errors="replace")
{target_line}

mask = target.notna()
df = df[mask]
target = target[mask]

if len(df) == 0:
    print("ERROR: Dataset is empty after removing NaN targets. Aborting.")
    raise SystemExit(1)

for _c in df.select_dtypes(include=["int64", "float64"]).columns:
    df[_c] = df[_c].fillna(df[_c].median())
for _c in df.select_dtypes(include=["object"]).columns:
    df[_c] = df[_c].fillna(df[_c].mode().iloc[0] if not df[_c].mode().empty else "MISSING")

# Coerce string columns that look numeric to prevent dtype errors
for _c in df.select_dtypes(include=["object"]).columns:
    _converted = pd.to_numeric(df[_c], errors="ignore")
    if _converted.dtype in ("int64", "float64"):
        df[_c] = _converted

# --- Target encoding: handles string labels like 'Yes'/'No', 'True'/'False' ---
_target_encoder = _TargetLabelEncoder()
if target.dtype == object or str(target.dtype) == 'category':
    target = _target_encoder.fit_transform(target)
    _target_classes = _target_encoder.classes_.tolist()
else:
    _target_encoder.fit(target)
    _target_classes = _target_encoder.classes_.tolist()

{split_and_cv}
numeric_cols = X_train.select_dtypes(include=["int64", "float64"]).columns.tolist()
categorical_cols = X_train.select_dtypes(include=["object"]).columns.tolist()

preprocessor = ColumnTransformer([
    ("num", "passthrough", numeric_cols),
    ("cat", OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1), categorical_cols),
])

if _use_optuna:
    if {is_classification}:
        def _objective(trial):
            params = {{}}
            for _name, _spec in _search_space.items():
                if _spec["type"] == "int":
                    params[_name] = trial.suggest_int(_name, _spec["low"], _spec["high"])
                elif _spec["type"] == "float":
                    params[_name] = trial.suggest_float(_name, _spec["low"], _spec["high"])
            params["random_state"] = 42
            params["verbosity"] = -1
            {class_weight_objective_line}            _model = Pipeline([("preprocessor", preprocessor), ("estimator", lgb.LGBMClassifier(**params))])
            _model.fit(X_train, y_train)
            _y_prob = _model.predict_proba(X_test)[:, 1]
            return roc_auc_score(y_test, _y_prob)
    else:
        def _objective(trial):
            params = {{}}
            for _name, _spec in _search_space.items():
                if _spec["type"] == "int":
                    params[_name] = trial.suggest_int(_name, _spec["low"], _spec["high"])
                elif _spec["type"] == "float":
                    params[_name] = trial.suggest_float(_name, _spec["low"], _spec["high"])
            params["random_state"] = 42
            params["verbosity"] = -1
            _model = Pipeline([("preprocessor", preprocessor), ("estimator", lgb.LGBMRegressor(**params))])
            _model.fit(X_train, y_train)
            _y_pred = _model.predict(X_test)
            return float(mean_squared_error(y_test, _y_pred))

    _n_trials = {max_trials}
    study = optuna.create_study(direction={direction})
    study.optimize(_objective, n_trials=_n_trials)
    best_params = study.best_params
    best_params["random_state"] = 42
    best_params["verbose"] = -1
else:
    best_params = {{"n_estimators": 100, "random_state": 42, "verbose": -1}}

{final_fit}if not {use_cv}:
    if {is_classification}:
        estimator = lgb.LGBMClassifier(**best_params{class_weight_param})
    else:
        estimator = lgb.LGBMRegressor(**best_params)
    {smote_step}model = Pipeline([
        ("preprocessor", preprocessor),
        ("estimator", estimator),
    ])
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    {eval_metrics}

_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
output_dir = os.path.join(_outputs_dir, "checkpoints")
os.makedirs(output_dir, exist_ok=True)
checkpoint_path = os.path.join(output_dir, "best.ckpt")
_checkpoint = {{
    "model": model,
    "target_encoder": _target_encoder,
    "target_classes": _target_classes,
    "feature_names": list(X_train.columns) if hasattr(X_train, 'columns') else [],
}}
with open(checkpoint_path, "wb") as f:
    pickle.dump(_checkpoint, f)
print(f"Model saved to {{checkpoint_path}}")
np.save(os.path.join(output_dir, "y_test.npy"), y_test)
np.save(os.path.join(output_dir, "y_pred.npy"), y_pred)
if {is_classification}:
    y_prob_full = model.predict_proba(X_test)
    if y_prob_full.shape[1] == 2:
        y_prob_full = y_prob_full[:, 1]
    np.save(os.path.join(output_dir, "y_prob.npy"), y_prob_full)
'''

    script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    logger.info(f"[job={job_id}] LightGBM script written to {script_path}")
    return script_path


def _write_distilbert_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    max_trials: int = 20,
) -> str:
    task_type = mission_brief["task_type"]
    target = mission_brief.get("target_column", "target")
    file_path = mission_brief["dataset"]["file_path"]
    data_filename = os.path.basename(file_path)
    data_delimiter = mission_brief.get("dataset", {}).get("delimiter", ",")

    header_design = _design_header_block(design_summary)
    script = f'''#!/usr/bin/env python3
"""
Training script for job {job_id}
Architecture: distilbert
Task: {task_type}
Auto-generated by Forge agent.
Epochs from plan: {max_trials}
{header_design}"""

import os
import json
import pickle
import warnings
import numpy as np
import pandas as pd
import torch
from torch.utils.data import DataLoader, Dataset
from transformers import DistilBertTokenizer, DistilBertForSequenceClassification, AdamW
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder
warnings.filterwarnings("ignore")

DATA_PATH = os.path.join(os.getenv("DATA_DIR", "./data"), "{data_filename}")
TARGET_COL = "{target}"
_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
OUTPUT_DIR = os.path.join(_outputs_dir, "checkpoints")
os.makedirs(OUTPUT_DIR, exist_ok=True)

df = pd.read_csv(DATA_PATH, sep="{data_delimiter}")
text_col = [c for c in df.columns if c != TARGET_COL and df[c].dtype == "object"][0]
texts = df[text_col].astype(str).tolist()
labels = df[TARGET_COL].values

le = LabelEncoder()
labels = le.fit_transform(labels)
num_labels = len(le.classes_)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
tokenizer = DistilBertTokenizer.from_pretrained("distilbert-base-uncased")
model = DistilBertForSequenceClassification.from_pretrained("distilbert-base-uncased", num_labels=num_labels)
model.to(device)


class TextDataset(Dataset):
    def __init__(self, texts, labels):
        self.encodings = tokenizer(texts, truncation=True, padding=True, max_length=128, return_tensors="pt")
        self.labels = torch.tensor(labels)
    def __len__(self): return len(self.labels)
    def __getitem__(self, idx):
        item = {{k: v[idx] for k, v in self.encodings.items()}}
        item["labels"] = self.labels[idx]
        return item

train_texts, val_texts, train_labels, val_labels = train_test_split(texts, labels, test_size=0.2, random_state=42)
train_dataset = TextDataset(train_texts, train_labels)
val_dataset = TextDataset(val_texts, val_labels)
train_loader = DataLoader(train_dataset, batch_size=16, shuffle=True)
val_loader = DataLoader(val_dataset, batch_size=16)

optimizer = AdamW(model.parameters(), lr=2e-5)

for epoch in range(3):
    model.train()
    total_loss = 0
    for batch in train_loader:
        batch = {{k: v.to(device) for k, v in batch.items()}}
        outputs = model(**batch)
        loss = outputs.loss
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        total_loss += loss.item()
    avg_loss = total_loss / len(train_loader)
    print(f"Epoch {{epoch+1}}/3 | Train loss: {{avg_loss:.4f}}")

    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch in val_loader:
            batch = {{k: v.to(device) for k, v in batch.items()}}
            outputs = model(**batch)
            preds = torch.argmax(outputs.logits, dim=-1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(batch["labels"].cpu().numpy())
    val_acc = accuracy_score(all_labels, all_preds)
    print(f"Accuracy: {{val_acc:.4f}}")

checkpoint_path = os.path.join(OUTPUT_DIR, "best.ckpt")
with open(checkpoint_path, "wb") as f:
    pickle.dump({{"model_state": model.state_dict(), "label_encoder": le}}, f)
print(f"Model saved to {{checkpoint_path}}")
np.save(os.path.join(OUTPUT_DIR, "y_test.npy"), np.array(val_labels))
np.save(os.path.join(OUTPUT_DIR, "y_pred.npy"), np.array(all_preds))

result = {{"checkpoint_path": checkpoint_path, "val_score": float(val_acc), "metric": "accuracy"}}
with open(os.path.join(_outputs_dir, "result.json"), "w") as f:
    json.dump(result, f)
print("TRAINING_COMPLETE")
'''

    script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    logger.info(f"[job={job_id}] DistilBERT script written to {script_path}")
    return script_path


def _write_efficientnet_script(
    mission_brief: dict,
    job_id: str,
    scripts_dir: str = "./scripts",
    design_summary: str | None = None,
    max_trials: int = 20,
) -> str:
    task_type = mission_brief["task_type"]
    file_path = mission_brief["dataset"]["file_path"]
    data_filename = os.path.basename(file_path)
    data_delimiter = mission_brief.get("dataset", {}).get("delimiter", ",")

    header_design = _design_header_block(design_summary)
    script = f'''#!/usr/bin/env python3
"""
Training script for job {job_id}
Architecture: efficientnet
Task: {task_type}
Auto-generated by Forge agent.
Epochs from plan: {max_trials}
{header_design}"""

import os
import json
import pickle
import warnings
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms, models
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import LabelEncoder
from PIL import Image
warnings.filterwarnings("ignore")

DATA_PATH = os.path.join(os.getenv("DATA_DIR", "./data"), "{data_filename}")
_outputs_dir = os.getenv("OUTPUTS_DIR", "./outputs")
OUTPUT_DIR = os.path.join(_outputs_dir, "checkpoints")
os.makedirs(OUTPUT_DIR, exist_ok=True)

df = pd.read_csv(DATA_PATH, sep="{data_delimiter}")
img_col = [c for c in df.columns if "path" in c.lower() or "file" in c.lower() or "image" in c.lower()]
label_col = [c for c in df.columns if c != img_col[0]][0] if img_col else df.columns[-1]
img_col = img_col[0] if img_col else df.columns[0]

le = LabelEncoder()
labels = le.fit_transform(df[label_col])
num_classes = len(le.classes_)

transform = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

class ImageDataset(Dataset):
    def __init__(self, paths, labels, transform):
        self.paths = paths.tolist()
        self.labels = torch.tensor(labels)
        self.transform = transform
    def __len__(self): return len(self.paths)
    def __getitem__(self, idx):
        img = Image.open(self.paths[idx]).convert("RGB")
        img = self.transform(img)
        return {{"pixel_values": img, "labels": self.labels[idx]}}

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
model = models.efficientnet_b0(pretrained=True)
model.classifier[1] = nn.Linear(model.classifier[1].in_features, num_classes)
model.to(device)

criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=0.001)

train_idx, val_idx = train_test_split(range(len(df)), test_size=0.2, random_state=42)
train_ds = ImageDataset(df[img_col].values[train_idx], labels[train_idx], transform)
val_ds = ImageDataset(df[img_col].values[val_idx], labels[val_idx], transform)
train_loader = DataLoader(train_ds, batch_size=32, shuffle=True)
val_loader = DataLoader(val_ds, batch_size=32)

for epoch in range(10):
    model.train()
    total_loss = 0
    for batch in train_loader:
        batch = {{k: v.to(device) for k, v in batch.items()}}
        outputs = model(**batch)
        logits = outputs.logits if hasattr(outputs, 'logits') else outputs
        loss = criterion(logits, batch["labels"])
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        total_loss += loss.item()
    avg_loss = total_loss / len(train_loader)
    print(f"Epoch {{epoch+1}}/10 | Train loss: {{avg_loss:.4f}}")

    model.eval()
    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch in val_loader:
            batch = {{k: v.to(device) for k, v in batch.items()}}
            outputs = model(**batch)
            logits = outputs.logits if hasattr(outputs, 'logits') else outputs
            preds = torch.argmax(logits, dim=-1)
            all_preds.extend(preds.cpu().numpy())
            all_labels.extend(batch["labels"].cpu().numpy())
    val_acc = accuracy_score(all_labels, all_preds)
    print(f"Accuracy: {{val_acc:.4f}}")

checkpoint_path = os.path.join(OUTPUT_DIR, "best.ckpt")
torch.save({{"model_state": model.state_dict(), "label_encoder": le}}, checkpoint_path)
print(f"Model saved to {{checkpoint_path}}")
np.save(os.path.join(OUTPUT_DIR, "y_test.npy"), np.array(all_labels))
np.save(os.path.join(OUTPUT_DIR, "y_pred.npy"), np.array(all_preds))

result = {{"checkpoint_path": checkpoint_path, "val_score": float(val_acc), "metric": "accuracy"}}
with open(os.path.join(_outputs_dir, "result.json"), "w") as f:
    json.dump(result, f)
print("TRAINING_COMPLETE")
'''

    script_path = os.path.join(scripts_dir, f"training_script_{job_id}.py")
    os.makedirs(scripts_dir, exist_ok=True)
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(script)

    logger.info(f"[job={job_id}] EfficientNet script written to {script_path}")
    return script_path


def _lookup_fingerprint(
    redis_client: Any,
    architecture: str,
    job_id: str,
) -> str | None:
    """Pre-generation fingerprint lookup.

    Checks if an existing script with a matching fingerprint already
    produced a successful training run. If so, returns its path so the
    caller can skip re-generation entirely.

    Returns:
        Cached script path if a matching successful fingerprint is found,
        None otherwise.
    """
    if redis_client is None:
        return None
    try:
        from agents.forge.script_fingerprint import (
            query_fingerprint_by_architecture,
        )

        import asyncio

        loop = asyncio.get_event_loop()
        coro = _query_recent_successful_fingerprint(redis_client, architecture)
        if loop.is_running():
            import concurrent.futures

            future = asyncio.run_coroutine_threadsafe(coro, loop)
            cached = future.result(timeout=5)
        else:
            cached = loop.run_until_complete(coro)

        if cached and cached.get("outcome") == "success":
            return cached.get("script_path")
    except Exception as e:
        logger.debug(f"[job={job_id}] Fingerprint lookup skipped: {e}")
    return None


async def _query_recent_successful_fingerprint(
    redis_client: Any,
    architecture: str,
) -> dict | None:
    """Query Redis for a recent successful fingerprint for this architecture."""
    try:
        pattern = "fingerprint:*:meta"
        keys = await redis_client.scan_keys(pattern)
        for key in keys:
            meta = await redis_client.get_json(key)
            if (
                meta
                and meta.get("architecture") == architecture
                and meta.get("outcome") == "success"
            ):
                return meta
    except Exception:
        pass
    return None


def _check_and_record_fingerprint(
    redis_client: Any,
    script_path: str,
    architecture: str,
    job_id: str,
) -> str | None:
    """Check fingerprint cache and record. Returns cached script_path if hit."""
    if redis_client is None:
        return None
    try:
        import asyncio

        with open(script_path, encoding="utf-8") as f:
            content = f.read()

        fp = compute_fingerprint(content)
        cached = None

        # Run fingerprint check synchronously
        loop = asyncio.get_event_loop()
        coro_check = check_fingerprint(redis_client, fp)
        if loop.is_running():
            import concurrent.futures

            future = asyncio.run_coroutine_threadsafe(coro_check, loop)
            cached = future.result(timeout=5)
        else:
            cached = loop.run_until_complete(coro_check)

        if cached and cached.get("outcome") == "success":
            logger.info(
                f"[job={job_id}] Fingerprint cache HIT | fp={fp[:8]}... "
                f"arch={architecture} val_metric={cached.get('val_metric', 'N/A')} "
                f"usage={cached.get('usage_count', 0)}"
            )
            # Store cache hit info for the orchestrator
            cache_key = f"job:{job_id}:fingerprint_cache_hit"
            import json

            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    redis_client.setex(cache_key, 86400, json.dumps(cached)),
                    loop,
                )
            else:
                loop.run_until_complete(redis_client.setex(cache_key, 86400, json.dumps(cached)))
            return cached.get("script_path", script_path)

        # Record as pending
        coro_record = record_fingerprint_pending(
            redis_client,
            fp,
            architecture,
            job_id,
            script_path,
            content,
        )
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(coro_record, loop)
        else:
            loop.run_until_complete(coro_record)

    except Exception as e:
        logger.debug(f"Fingerprint check skipped: {e}")

    return None


def _increment_script_count(redis_client: Any, architecture: str) -> None:
    """Increment the total script counter for an architecture in Redis.

    Called after every successful script generation (template or f-string).
    This feeds error-rate calculations in quality_feedback.py.
    """
    if redis_client is None:
        return
    try:
        from agents.forge.quality_feedback import increment_script_count

        import asyncio

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(increment_script_count(redis_client, architecture))
        else:
            loop.run_until_complete(increment_script_count(redis_client, architecture))
    except Exception as e:
        logger.debug(f"Failed to increment script count: {e}")

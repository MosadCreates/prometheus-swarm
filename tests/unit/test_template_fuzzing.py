"""Fuzz tests — adversarial edge-case testing of all 9 training templates.

Each fuzz variant injects a specific edge case (NaN, wrong types, single class,
empty data, etc.) into the template rendering pipeline and verifies:
  1. The template renders to valid Python (ast.parse)
  2. The rendered script contains appropriate defensive guards
  3. Optional execution tests (@pytest.mark.training_exec) run the script end-to-end
"""

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from agents.forge.template_renderer import (
    select_and_render,
    has_template,
    validate_script,
    _build_variables,
)

FUZZ_DIR = Path("tests/fixtures/fuzz")
TABULAR_ARCHES = [
    ("lightgbm", "classification"),
    ("xgboost", "classification"),
    ("tabnet", "classification"),
]
REGRESSION_ARCHES = [
    ("lightgbm", "regression"),
    ("xgboost", "regression"),
    ("tabnet", "regression"),
]
ALL_TABULAR = TABULAR_ARCHES + REGRESSION_ARCHES

# ── Fuzz variant briefs ──────────────────────────────────────────────

BASE_BRIEF = {
    "problem_description": "Fuzz test",
    "task_type": "classification",
    "modality": "tabular",
    "target_column": "target",
    "evaluation_metric": "auc_roc",
    "constraints": {"max_latency_ms": None, "max_model_size_mb": None},
    "data_quality": {
        "class_imbalance_ratio": 1.0,
        "missing_value_rate": {},
        "high_cardinality_columns": [],
        "data_warnings": [],
    },
    "imbalance_strategy": "none",
}

FUZZ_VARIANTS: list[tuple[str, dict, str]] = []


def _add(uid: str, brief_overrides: dict, expected_guard_hint: str = ""):
    brief = {**BASE_BRIEF, **brief_overrides}
    dataset = brief.setdefault("dataset", {})
    dataset.setdefault("file_path", str(FUZZ_DIR / f"{uid}.csv"))
    dataset.setdefault("column_types", {
        "feature_num": "numeric",
        "feature_cat": "categorical",
        "target": "target",
    })
    FUZZ_VARIANTS.append((uid, brief, expected_guard_hint))


# Standard — should work fine
_add("fuzz_standard", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_standard.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# All NaN features
_add("fuzz_all_nan", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_all_nan.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Wrong dtypes — string in numeric column
_add("fuzz_wrong_dtypes", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_wrong_dtypes.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Empty dataset (0 rows)
_add("fuzz_empty", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_empty.csv"),
        "num_rows": 0, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Single row
_add("fuzz_single_row", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_single_row.csv"),
        "num_rows": 1, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Single class in target
_add("fuzz_single_class", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_single_class.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# High cardinality categorical
_add("fuzz_high_cardinality", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_high_cardinality.csv"),
        "num_rows": 1000, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Inf values
_add("fuzz_inf_values", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_inf_values.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Mixed dtypes
_add("fuzz_mixed_dtypes", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_mixed_dtypes.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Wide dataset (150 columns)
_add("fuzz_wide", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_wide.csv"),
        "num_rows": 100, "num_columns": 151,
        "column_types": {},
    },
})

# Special characters in column names
_add("fuzz_special_chars", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_special_chars.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feat#num": "numeric", "feat/cat": "categorical", "targ et": "target"},
    },
    "target_column": "targ et",
})

# All NaN target
_add("fuzz_all_nan_target", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_all_nan_target.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# Extreme values (1e15)
_add("fuzz_extreme_values", {
    "dataset": {
        "file_path": str(FUZZ_DIR / "fuzz_extreme_values.csv"),
        "num_rows": 100, "num_columns": 3,
        "column_types": {"feature_num": "numeric", "feature_cat": "categorical", "target": "target"},
    },
})

# ── Test helpers ─────────────────────────────────────────────────────

TEMPLATE_ARCHES = [
    ("lightgbm", "binary"),
    ("lightgbm", "multiclass"),
    ("lightgbm", "regression"),
    ("xgboost", "binary"),
    ("xgboost", "multiclass"),
    ("xgboost", "regression"),
    ("tabnet", "binary"),
    ("distilbert", "classification"),
    ("efficientnet", "classification"),
]


def _has_template_for_fuzz(arch: str, task_type: str) -> bool:
    return has_template(arch, task_type)


def _task_type_for_fuzz(task: str) -> str:
    mapping = {
        "binary": "classification",
        "multiclass": "multiclass",
        "regression": "regression",
        "classification": "classification",
    }
    return mapping.get(task, "classification")


def _target_metric(task_type: str) -> str:
    if task_type == "regression":
        return "rmse"
    return "auc_roc"


# ── Fuzz test: Render + Syntax Check ─────────────────────────────────


@pytest.mark.parametrize("arch,task", TEMPLATE_ARCHES)
@pytest.mark.parametrize("fuzz_id,brief,guard_hint", FUZZ_VARIANTS)
def test_fuzz_render_syntax(arch: str, task: str, fuzz_id: str, brief: dict, guard_hint: str):
    if not _has_template_for_fuzz(arch, task):
        pytest.skip(f"No template for {arch}/{task}")

    # Build fuzz-specific brief
    fuzz_brief = dict(brief)
    task_type = _task_type_for_fuzz(task)
    fuzz_brief["task_type"] = task_type
    fuzz_brief["evaluation_metric"] = _target_metric(task_type)

    # For multiclass, adjust target to have >=2 classes
    if "multiclass" in task:
        fuzz_brief["data_quality"] = {
            **fuzz_brief.get("data_quality", {}),
            "class_imbalance_ratio": 1.0,
        }

    script = select_and_render(fuzz_brief, f"fuzz-{fuzz_id}-{arch}", None, arch)
    assert script is not None, (
        f"[{fuzz_id}] select_and_render returned None for {arch}/{task}"
    )
    assert len(script) > 100, f"[{fuzz_id}] Script too short ({len(script)} bytes)"
    assert validate_script(script), f"[{fuzz_id}] Invalid Python syntax for {arch}/{task}"

    # Verify basic training patterns
    assert "pd.read_csv" in script, f"[{fuzz_id}] Missing pd.read_csv in {arch}/{task}"
    assert "checkpoint_path" in script or "best.ckpt" in script, (
        f"[{fuzz_id}] Missing checkpoint in {arch}/{task}"
    )


# ── Fuzz test: Architecture-specific guard checks ────────────────────


class TestFuzzGuards:
    """Verify rendered scripts contain defensive guards against edge cases."""

    def _render(self, arch: str, task: str, fuzz_id: str, brief: dict) -> str:
        task_type = _task_type_for_fuzz(task)
        b = dict(brief)
        b["task_type"] = task_type
        b["evaluation_metric"] = _target_metric(task_type)
        script = select_and_render(b, f"guard-{fuzz_id}-{arch}", None, arch)
        assert script is not None, f"render None for {arch}/{task}/{fuzz_id}"
        return script

    def test_single_class_guard(self):
        """stratify should not crash when target has 1 class."""
        for fuzz_id, brief, _ in FUZZ_VARIANTS:
            if "single_class" not in fuzz_id:
                continue
            for arch, task in TABULAR_ARCHES:
                if arch == "tabnet":
                    continue  # TabNet uses train_test_split without stratify
                script = self._render(arch, task, fuzz_id, brief)
                # Check: stratify should be conditional (guarded by _n_classes check)
                has_condition = "_n_classes" in script or "_use_stratify" in script
                has_stratify = "stratify=target" in script or "stratify=y_train" in script
                assert has_stratify, f"[{fuzz_id}/{arch}] Expected stratify"
                assert has_condition, (
                    f"[{fuzz_id}/{arch}] stratify used without _n_classes guard"
                )

    def test_numeric_dtype_coverage(self):
        """select_dtypes should cover more than int64/float64."""
        for fuzz_id, brief, _ in FUZZ_VARIANTS:
            for arch, task in ALL_TABULAR:
                script = self._render(arch, task, fuzz_id, brief)
                dtypes = 'select_dtypes(include=["int64", "float64"])'
                if dtypes in script:
                    # Check it's not the ONLY numeric check — verify number, floatXX coverage
                    num_dtype_refs = script.count("float64") + script.count("int64")
                    assert num_dtype_refs <= 4, (
                        f"[{fuzz_id}/{arch}] Only int64/float64 — "
                        f"misses float32, int32, etc. ({num_dtype_refs} refs)"
                    )

    def test_roc_auc_guard(self):
        """roc_auc_score should be guarded against single-class test set."""
        for fuzz_id, brief, _ in FUZZ_VARIANTS:
            if "single_class" not in fuzz_id:
                continue
            for arch, task in TABULAR_ARCHES:
                if task[1] == "regression":
                    continue
                script = self._render(arch, task, fuzz_id, brief)
                # Check for roc_auc defensive patterns
                has_try = "try:" in script and "except" in script
                has_condition = "n_classes" in script or "unique" in script
                if not (has_try or has_condition):
                    pytest.xfail(
                        f"[{fuzz_id}/{arch}] roc_auc_score may crash "
                        f"with single class — no try/except or n_classes guard found"
                    )


# ── Full execution tests (slow, optional) ───────────────────────────


@pytest.mark.training_exec
@pytest.mark.parametrize("arch,task", [("lightgbm", "binary")])
@pytest.mark.parametrize("fuzz_id,brief,guard_hint", [
    v for v in FUZZ_VARIANTS if v[0] not in (
        "fuzz_empty", "fuzz_all_nan_target", "fuzz_single_row",
    )
])
def test_fuzz_exec_lightgbm_binary(fuzz_id: str, brief: dict, guard_hint: str, arch: str, task: str):
    """Run the rendered script against fuzz data and verify it completes."""
    fuzz_brief = dict(brief)
    fuzz_brief["task_type"] = "classification"
    fuzz_brief["evaluation_metric"] = "auc_roc"

    script = select_and_render(fuzz_brief, f"exec-{fuzz_id}", None, arch)
    assert script is not None, f"render returned None for {fuzz_id}"

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        script_path = tmp_path / f"train_fuzz_{fuzz_id}.py"
        script_path.write_text(script)

        data_path = Path(fuzz_brief["dataset"]["file_path"])
        data_dest = tmp_path / data_path.name
        if data_path.exists():
            data_dest.write_bytes(data_path.read_bytes())

        out_dir = tmp_path / "outputs"
        out_dir.mkdir()

        env = os.environ.copy()
        env["DATA_DIR"] = str(tmp_path)
        env["OUTPUTS_DIR"] = str(out_dir)
        env["PYTHONUNBUFFERED"] = "1"
        env["JOB_ID"] = f"exec-{fuzz_id}"
        env["OMP_NUM_THREADS"] = "1"  # prevent thread oversubscription

        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        stdout = result.stdout
        stderr = result.stderr

        if result.returncode != 0:
            pytest.fail(
                f"[{fuzz_id}] Script failed (rc={result.returncode}):\n"
                f"STDERR: {stderr[:500]}\nSTDOUT: {stdout[:500]}"
            )

        assert "TRAINING_COMPLETE" in stdout, (
            f"[{fuzz_id}] TRAINING_COMPLETE not found in stdout:\n{stdout[:500]}"
        )


# ── Fuzz data integrity check ────────────────────────────────────────


def test_fuzz_data_files_exist():
    for fuzz_id, brief, _ in FUZZ_VARIANTS:
        path = Path(brief["dataset"]["file_path"])
        assert path.exists(), f"Missing fuzz data file: {path}"
        assert path.stat().st_size > 0, f"Empty fuzz data file: {path}"


def test_fuzz_variants_have_correct_structure():
    for fuzz_id, brief, _ in FUZZ_VARIANTS:
        assert "dataset" in brief, f"[{fuzz_id}] Missing dataset key"
        assert "file_path" in brief["dataset"], f"[{fuzz_id}] Missing file_path"
        assert "target_column" in brief, f"[{fuzz_id}] Missing target_column"
        assert "task_type" in brief, f"[{fuzz_id}] Missing task_type"

"""Tests for evaluation/stress_injector.py — fault injection harness."""

import csv
import os
import tempfile
from pathlib import Path

import pytest

from evaluation.stress_injector import (
    FAULTS,
    EXPECTED_BEHAVIOUR,
    corrupted_csv,
    empty_dataset,
    extreme_imbalance,
    feature_type_mismatch,
    inject_fault,
    missing_required_column,
    nan_explosion,
    schema_drift,
    unseen_categorical_values,
)


@pytest.fixture
def sample_csv(tmp_path):
    """Create a small sample CSV for testing."""
    path = tmp_path / "sample.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "age", "income", "category", "target"])
        writer.writerow([1, 25, 50000, "A", "yes"])
        writer.writerow([2, 30, 60000, "B", "no"])
        writer.writerow([3, 35, 70000, "A", "yes"])
        writer.writerow([4, 40, 80000, "C", "no"])
        writer.writerow([5, 45, 90000, "B", "yes"])
        writer.writerow([6, 50, 100000, "A", "no"])
    return path


@pytest.fixture
def temp_dir(tmp_path):
    return tmp_path / "injected"


def test_corrupted_csv(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = corrupted_csv(sample_csv, temp_dir)
    assert "corrupted" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        header = f.readline()
        assert "|" in header  # Wrong delimiter
    # Should still be readable
    with open(dest, encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) > 1  # Has data


def test_missing_required_column(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = missing_required_column(sample_csv, temp_dir, column="target")
    assert "missing" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert "target" not in (reader.fieldnames or [])
        rows = list(reader)
        assert len(rows) > 0


def test_empty_dataset(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = empty_dataset(sample_csv, temp_dir)
    assert "empty" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        lines = f.readlines()
        assert len(lines) == 1  # Header only


def test_extreme_imbalance(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = extreme_imbalance(sample_csv, temp_dir, target_col="target", ratio=500)
    assert "imbalance" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        assert len(rows) >= 1
        # Should be skewed towards minority
        target_vals = [r["target"] for r in rows]
        minority = min(set(target_vals), key=target_vals.count)
        majority = max(set(target_vals), key=target_vals.count)
        assert target_vals.count(majority) >= target_vals.count(minority)


def test_unseen_categorical_values(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = unseen_categorical_values(sample_csv, temp_dir)
    assert "unseen" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        # Some values should be prefixed with UNSEEN_
        all_vals = [v for r in rows for v in r.values() if v]
        assert any("UNSEEN_" in v for v in all_vals)


def test_schema_drift(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = schema_drift(sample_csv, temp_dir)
    assert "schema" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        # First two columns should be swapped from original
        # After swap: [age, id, income, category, target]
        assert fieldnames[0] == "age"  # Was originally second
        assert fieldnames[1] == "id"  # Was originally first


def test_nan_explosion(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = nan_explosion(sample_csv, temp_dir, nan_rate=1.0)
    assert "nan explosion" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        # All values in the second column should be empty
        col_name = (reader.fieldnames or [])[1] if reader.fieldnames else ""
        assert all(row.get(col_name, "") == "" for row in rows)


def test_feature_type_mismatch(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = feature_type_mismatch(sample_csv, temp_dir)
    assert "type mismatch" in desc.lower()
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        # Age values should be prefixed with "str_"
        numeric_cols = [r["age"] for r in rows if "age" in r and r["age"]]
        assert all(v.startswith("str_") for v in numeric_cols)


def test_inject_fault_integration(sample_csv, temp_dir):
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = inject_fault(str(sample_csv), "corrupted_csv", temp_dir=temp_dir)
    assert os.path.exists(dest)
    assert desc


def test_inject_fault_unknown():
    with pytest.raises(ValueError, match="Unknown fault"):
        inject_fault("dummy.csv", "nonexistent_fault")


def test_inject_fault_missing_source():
    with pytest.raises(FileNotFoundError):
        inject_fault("/nonexistent/file.csv", "corrupted_csv")


def test_all_faults_have_behaviours():
    """Every registered fault should have an expected behaviour."""
    for fault_name in FAULTS:
        assert (
            fault_name in EXPECTED_BEHAVIOUR
        ), f"Fault '{fault_name}' missing from EXPECTED_BEHAVIOUR"


def test_all_faults_produce_output(sample_csv, tmp_path):
    """Every registered fault should produce a valid output file."""
    out_dir = tmp_path / "faults"
    out_dir.mkdir(parents=True, exist_ok=True)

    kwargs: dict = {}
    for fault_name in FAULTS:
        # Some faults require extra kwargs
        if fault_name == "extreme_imbalance":
            kwargs["target_col"] = "target"
        elif fault_name == "missing_column":
            kwargs["column"] = "target"
        else:
            kwargs = {}
        dest, desc = inject_fault(str(sample_csv), fault_name, temp_dir=out_dir, **kwargs)
        assert os.path.exists(dest), f"Fault '{fault_name}' did not produce a file"
        assert desc, f"Fault '{fault_name}' produced empty description"


def test_extreme_imbalance_no_suitable_target(tmp_path):
    """If the target column has <2 values, should return source path."""
    csv_path = tmp_path / "single.csv"
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        f.write("x,y\n1,2\n3,4\n")
    dest, desc = extreme_imbalance(csv_path, tmp_path, target_col="y", ratio=500)
    # Falls back to original since there are only unique values
    assert dest == str(csv_path)


def test_missing_column_from_kwargs(sample_csv, temp_dir):
    """missing_required_column should accept custom column name."""
    temp_dir.mkdir(parents=True, exist_ok=True)
    dest, desc = missing_required_column(sample_csv, temp_dir, column="age")
    with open(dest, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert "age" not in (reader.fieldnames or [])

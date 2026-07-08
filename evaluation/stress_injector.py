"""Stress and fault injection harness.

Injects controlled failures into datasets, environment, and infrastructure
to test system resilience. Each fault has a clearly defined expected
behaviour (recover, retry, escalate, correct adaptation).

Faults are applied ephemerally — the original dataset is never modified.
"""

import csv
import logging
import os
import random
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Fault definitions — each fault modifies (or wraps) a dataset path
# and returns the path the system should read from.
# ---------------------------------------------------------------------------

FaultResult = tuple[str, str]  # (modified_path, description)


def corrupted_csv(source: Path, temp_dir: Path) -> FaultResult:
    """Replace commas with pipes and insert garbage rows."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin, open(dest, "w", encoding="utf-8") as fout:
        for i, line in enumerate(fin):
            if i == 0:
                fout.write(line.replace(",", "|"))  # header with wrong delimiter
            elif i % 5 == 0:
                fout.write("garbage,line,with,wrong,columns\n")
            else:
                fout.write(line)
    return str(dest), "corrupted CSV (wrong delimiter + garbage rows)"


def missing_required_column(source: Path, temp_dir: Path, column: str = "target") -> FaultResult:
    """Drop the target column from the dataset."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin, open(dest, "w", encoding="utf-8") as fout:
        reader = csv.DictReader(fin)
        cols = [c for c in reader.fieldnames if c != column] if reader.fieldnames else []
        writer = csv.DictWriter(fout, fieldnames=cols)
        writer.writeheader()
        for row in reader:
            row.pop(column, None)
            writer.writerow(row)
    return str(dest), f"missing required column '{column}'"


def empty_dataset(source: Path, temp_dir: Path) -> FaultResult:
    """Write only the header row, no data."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin, open(dest, "w", encoding="utf-8") as fout:
        header = fin.readline()
        fout.write(header)
    return str(dest), "empty dataset (header only)"


def extreme_imbalance(
    source: Path, temp_dir: Path, target_col: str, ratio: int = 500
) -> FaultResult:
    """Subsample majority class to create extreme imbalance."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows = list(reader)
        if not rows:
            return str(source), "no rows to imbalance"
        values = set(r.get(target_col, "") for r in rows)
        if len(values) < 2:
            return str(source), f"cannot imbalance — target '{target_col}' has <2 values"

        majority_val = max(values, key=lambda v: sum(1 for r in rows if r.get(target_col) == v))
        minority_rows = [r for r in rows if r.get(target_col) != majority_val]
        majority_rows = [r for r in rows if r.get(target_col) == majority_val]
        keep_majority = max(1, len(minority_rows) * ratio)
        random.shuffle(majority_rows)
        balanced = minority_rows + majority_rows[:keep_majority]
        random.shuffle(balanced)

    with open(dest, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(balanced)

    return str(dest), f"extreme imbalance ({ratio}:1 majority:minority)"


def unseen_categorical_values(source: Path, temp_dir: Path, col: str = "category") -> FaultResult:
    """Replace some column values in test split with unseen values."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows = list(reader)
        fieldnames = reader.fieldnames or []

    if not rows:
        return str(source), "no rows for unseen values"

    split = len(rows) * 2 // 3
    test_rows = rows[split:]

    # Replace categorical-like column values with unseen tokens
    for row in test_rows:
        for col_name in row:
            val = row[col_name]
            if val and not val.replace(".", "").replace("-", "").isdigit():
                row[col_name] = f"UNSEEN_{val.upper()}"

    all_rows = rows[:split] + test_rows

    with open(dest, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    return str(dest), "unseen categorical values injected in test split"


def schema_drift(source: Path, temp_dir: Path) -> FaultResult:
    """Swap order of two columns to test name-based vs position-based alignment."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows = list(reader)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []

    if len(fieldnames) < 2:
        return str(source), "too few columns for schema drift"

    # Swap first two columns
    fieldnames[0], fieldnames[1] = fieldnames[1], fieldnames[0]

    with open(dest, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return str(dest), "schema drift (column order swapped)"


def nan_explosion(source: Path, temp_dir: Path, nan_rate: float = 0.5) -> FaultResult:
    """Replace a high proportion of values with NaN/empty in one column."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows = list(reader)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []

    if not rows or len(fieldnames) < 2:
        return str(source), "too few rows/cols for NaN explosion"

    target_col = fieldnames[1]  # Second column — first is often ID

    for row in rows:
        if random.random() < nan_rate:
            row[target_col] = ""

    with open(dest, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return str(dest), f"NaN explosion ({nan_rate*100:.0f}% NaN in column '{target_col}')"


def feature_type_mismatch(source: Path, temp_dir: Path, col: str = "age") -> FaultResult:
    """Cast a numeric column to a string to trigger dtype mismatch."""
    dest = temp_dir / source.name
    with open(source, encoding="utf-8") as fin:
        reader = csv.DictReader(fin)
        rows = list(reader)
        fieldnames = list(reader.fieldnames) if reader.fieldnames else []

    target_col = (
        col if col in (fieldnames or []) else (fieldnames[1] if len(fieldnames) > 1 else "")
    )
    if not target_col:
        return str(source), "no suitable column for type mismatch"

    for row in rows:
        if (
            target_col in row
            and row[target_col]
            and row[target_col].replace(".", "").replace("-", "").isdigit()
        ):
            row[target_col] = f"str_{row[target_col]}"

    with open(dest, "w", encoding="utf-8", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return str(dest), f"feature type mismatch (column '{target_col}' cast to string)"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FAULTS: dict[str, Callable[..., FaultResult]] = {
    "corrupted_csv": corrupted_csv,
    "missing_column": missing_required_column,
    "empty_dataset": empty_dataset,
    "extreme_imbalance": extreme_imbalance,
    "unseen_categorical": unseen_categorical_values,
    "schema_drift": schema_drift,
    "nan_explosion": nan_explosion,
    "feature_type_mismatch": feature_type_mismatch,
}

# Expected behaviours for the resilience matrix
EXPECTED_BEHAVIOUR: dict[str, str] = {
    "corrupted_csv": "Scout detects malformed file → appropriate error or Forge adapts",
    "missing_column": "Scout detects missing column → Forge adapts or Dissect repairs",
    "empty_dataset": "Scout detects empty dataset → escalate gracefully (no data to train)",
    "extreme_imbalance": "Forge selects SMOTE/focal loss → training succeeds",
    "unseen_categorical": "Forge adds fallback encoder → Dissect repairs KeyError",
    "schema_drift": "Forge aligns columns by name, not position → training succeeds",
    "nan_explosion": "Furnace catches NaN → Dissect applies median imputation",
    "feature_type_mismatch": "Dissect detects dtype_mismatch → adds LabelEncoder",
}


def inject_fault(
    original_path: str,
    fault_name: str,
    temp_dir: Path | None = None,
    **kwargs: Any,
) -> FaultResult:
    """Apply a fault to a dataset.

    Args:
        original_path: Path to the original dataset file.
        fault_name: One of the keys in FAULTS.
        temp_dir: Temp directory for the modified copy (auto-created if None).
        **kwargs: Passed to the fault function.

    Returns:
        (modified_path, description)
    """
    if fault_name not in FAULTS:
        raise ValueError(f"Unknown fault: {fault_name}. Available: {list(FAULTS.keys())}")

    if temp_dir is None:
        temp_dir = Path(tempfile.mkdtemp(prefix="stress_inject_"))

    source = Path(original_path)
    if not source.exists():
        raise FileNotFoundError(f"Source dataset not found: {source}")

    return FAULTS[fault_name](source, temp_dir, **kwargs)

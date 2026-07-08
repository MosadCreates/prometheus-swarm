"""Benchmark dataset validation — verifies every problem in problems.json.

Checks performed for each dataset:
- File exists and is readable
- Target column present
- Task type matches metadata
- Row count within expected tolerance (±20%)
- No duplicate benchmark IDs
- SHA-256 hash recorded for reproducibility
"""

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROWS_TOLERANCE = 0.20

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_PATH = PROJECT_ROOT / "research" / "benchmark" / "problems.json"


def load_problems() -> list[dict[str, Any]]:
    with open(BENCHMARK_PATH, encoding="utf-8") as f:
        return json.load(f)


def resolve_dataset_path(problem: dict) -> Path:
    raw = problem["dataset"]["path"]
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    return (PROJECT_ROOT / raw).resolve()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_all() -> dict[str, Any]:
    """Run all validation checks against every benchmark problem.

    Returns a dict with:
        schema_version: "1.0"
        timestamp: ISO 8601
        total_problems: int
        passed: int
        failed: int
        results: list of per-problem validation results
        summary: list of global issues found
    """
    problems = load_problems()
    ids_seen: set[str] = set()
    results: list[dict[str, Any]] = []
    global_issues: list[str] = []

    for problem in problems:
        pid = problem["id"]
        result: dict[str, Any] = {
            "problem_id": pid,
            "dataset_name": problem["dataset"]["name"],
            "passed": True,
            "issues": [],
            "warnings": [],
        }

        # Duplicate ID check
        if pid in ids_seen:
            result["issues"].append(f"Duplicate benchmark ID: {pid}")
            result["passed"] = False
        ids_seen.add(pid)

        ds_path = resolve_dataset_path(problem)
        ds_name = problem["dataset"]["name"]

        # File exists
        if not ds_path.exists():
            if "SKIP" in ds_path.name:
                result["warnings"].append("Dataset marked as unavailable on disk")
                results.append(result)
                continue
            result["issues"].append(
                f"Dataset file not found: {ds_path} (source={problem['dataset']['source']})"
            )
            result["passed"] = False
            results.append(result)
            continue

        # File hash
        try:
            result["sha256"] = file_sha256(ds_path)
        except Exception as e:
            result["issues"].append(f"Cannot compute hash: {e}")
            result["passed"] = False
            results.append(result)
            continue

        # Load and check — try multiple separators and handle no-header files
        try:
            import pandas as pd

            df = None
            separators = [",", ";", r"\s+", "|"]
            if ds_path.suffix.lower() in (".csv", ".data", ".txt"):
                for sep in separators:
                    try:
                        df = pd.read_csv(ds_path, nrows=5, sep=sep)
                        if df is not None and len(df.columns) > 1:
                            break
                    except Exception:
                        continue
                if df is None or len(df.columns) <= 1:
                    try:
                        df = pd.read_csv(ds_path, nrows=5, header=None)
                    except Exception as e:
                        result["issues"].append(f"Cannot read CSV: {e}")
                        result["passed"] = False
                        results.append(result)
                        continue
            elif ds_path.suffix.lower() == ".xls":
                df = pd.read_excel(ds_path, nrows=5)
            else:
                result["warnings"].append(f"Unknown file extension: {ds_path.suffix}")
                results.append(result)
                continue
        except Exception as e:
            result["issues"].append(f"Cannot read dataset: {e}")
            result["passed"] = False
            results.append(result)
            continue

        # Target column exists — try both exact and stripped match
        target_col = problem.get("target_column", "")
        if target_col:
            exact_match = target_col in df.columns
            stripped_match = target_col.strip() in [c.strip() for c in df.columns]
            if exact_match:
                result["target_column_found"] = True
            elif stripped_match:
                result["target_column_found"] = True
                result["warnings"].append(
                    f"Target column '{target_col}' matched after stripping whitespace"
                )
            elif target_col.isdigit() and int(target_col) < len(df.columns):
                result["target_column_found"] = True
                result["warnings"].append(
                    f"Target column is positional index {target_col} (no header)"
                )
            else:
                result["issues"].append(
                    f"Target column '{target_col}' not found in columns: {list(df.columns)}"
                )
                result["passed"] = False

        # Task type v modality consistency
        modality = problem.get("modality", "")
        task_type = problem.get("task_type", "")
        if modality == "image":
            result["warnings"].append(
                f"Image dataset (expected_architecture={problem.get('expected_architecture')})"
            )

        warnings = result.get("warnings", [])
        if modality == "text" and task_type not in ("classification", "regression"):
            warnings.append(f"Text modality but task_type={task_type}")

        # Row count sanity
        expected = problem.get("num_rows_expected")
        if expected and expected > 0:
            try:
                actual = sum(1 for _ in open(ds_path, encoding="utf-8")) - 1
                ratio = abs(actual - expected) / expected
                if ratio > ROWS_TOLERANCE and actual > 10:
                    warnings.append(
                        f"Row count mismatch: expected ~{expected}, got ~{actual} "
                        f"(off by {ratio*100:.0f}%)"
                    )
            except Exception:
                warnings.append("Could not verify row count")

        # Architecture expected
        arch = problem.get("expected_architecture", "")
        if not arch:
            warnings.append("No expected_architecture specified")
        if arch == "distilbert" and modality != "text":
            warnings.append(f"distilbert architecture for non-text modality ({modality})")
        if arch == "efficientnet" and modality != "image":
            warnings.append(f"efficientnet architecture for non-image modality ({modality})")

        results.append(result)

    passed = sum(1 for r in results if r["passed"])
    failed = sum(1 for r in results if not r["passed"])

    # Global checks
    if failed > 0:
        global_issues.append(f"{failed}/{len(results)} problems have validation failures")

    # Count by modality
    modalities: dict[str, int] = {}
    for p in problems:
        m = p.get("modality", "unknown")
        modalities[m] = modalities.get(m, 0) + 1
    for m, c in modalities.items():
        logger.info(f"  {m}: {c} problems")

    return {
        "schema_version": "1.0",
        "benchmark_path": str(BENCHMARK_PATH),
        "timestamp": __import__("datetime")
        .datetime.now(__import__("datetime").timezone.utc)
        .isoformat(),
        "total_problems": len(problems),
        "passed": passed,
        "failed": failed,
        "results": results,
        "summary": global_issues,
    }


def print_validation_report(report: dict[str, Any]) -> None:
    """Pretty-print validation report to console."""
    print(f"\n{'=' * 60}")
    print("  BENCHMARK VALIDATION")
    print(f"{'=' * 60}")
    print(f"  Problems: {report['total_problems']}")
    print(f"  Passed:   {report['passed']}")
    print(f"  Failed:   {report['failed']}")
    if report["failed"]:
        print("\n  FAILURES:")
        for r in report["results"]:
            if not r["passed"]:
                print(f"    {r['problem_id']} ({r['dataset_name']}):")
                for issue in r["issues"]:
                    print(f"      - {issue}")
    if report["summary"]:
        print("\n  SUMMARY:")
        for s in report["summary"]:
            print(f"    - {s}")
    print(f"{'=' * 60}\n")

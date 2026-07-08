"""Tests for evaluation/benchmark_validation.py."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

logging.disable(logging.CRITICAL)


FAKE_PROBLEMS = [
    {
        "id": "TC01",
        "dataset": {"name": "Titanic", "source": "kaggle", "path": "data/titanic.csv"},
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "Survived",
        "difficulty": "easy",
        "num_rows_expected": 891,
        "num_columns_expected": 12,
        "expected_architecture": "lightgbm",
        "evaluation_metric": "auc_roc",
    },
    {
        "id": "TC02",
        "dataset": {"name": "Iris", "source": "sklearn", "path": "data/iris.csv"},
        "task_type": "classification",
        "modality": "tabular",
        "target_column": "species",
        "difficulty": "easy",
        "num_rows_expected": 150,
        "num_columns_expected": 5,
        "expected_architecture": "lightgbm",
        "evaluation_metric": "f1",
    },
]


@pytest.fixture
def mock_problems(tmp_path):
    """Write fake problems.json to a temp dir and patch BENCHMARK_PATH."""
    problems_file = tmp_path / "problems.json"
    with open(problems_file, "w", encoding="utf-8") as f:
        json.dump(FAKE_PROBLEMS, f)

    # Create fake CSV files
    for prob in FAKE_PROBLEMS:
        ds_path = tmp_path / prob["dataset"]["path"]
        ds_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ds_path, "w", encoding="utf-8") as f:
            if prob["id"] == "TC01":
                f.write("PassengerId,Survived,Pclass,Name\n1,1,1,John\n2,0,2,Jane\n")
            else:
                f.write("sepal_length,sepal_width,species\n5.1,3.5,setosa\n4.9,3.0,versicolor\n")

    return problems_file


@patch("evaluation.benchmark_validation.BENCHMARK_PATH")
def test_validate_all_passes(mock_bp, mock_problems):
    mock_bp.__fspath__ = lambda self: str(mock_problems)
    mock_bp.resolve.return_value = mock_problems

    # We need to patch inside the module
    with patch("evaluation.benchmark_validation.BENCHMARK_PATH", mock_problems):
        from evaluation.benchmark_validation import validate_all

        report = validate_all()
        assert report["total_problems"] == 2
        assert report["passed"] == 2
        assert report["failed"] == 0


@patch("evaluation.benchmark_validation.BENCHMARK_PATH")
def test_validate_all_missing_file(mock_bp, tmp_path):
    """A problem referencing a non-existent file should fail."""
    bad_problems = [
        {
            "id": "TC99",
            "dataset": {"name": "Missing", "source": "custom", "path": "data/nonexistent.csv"},
            "task_type": "classification",
            "modality": "tabular",
            "target_column": "y",
            "expected_architecture": "lightgbm",
        }
    ]
    problems_file = tmp_path / "problems.json"
    with open(problems_file, "w", encoding="utf-8") as f:
        json.dump(bad_problems, f)

    with patch("evaluation.benchmark_validation.BENCHMARK_PATH", problems_file):
        from evaluation.benchmark_validation import validate_all

        report = validate_all()
        assert report["total_problems"] == 1
        assert report["failed"] == 1
        assert "not found" in report["results"][0]["issues"][0]


@patch("evaluation.benchmark_validation.BENCHMARK_PATH")
def test_validate_all_duplicate_ids(mock_bp, tmp_path):
    """Duplicate problem IDs should be flagged."""
    dup_problems = [
        {
            "id": "TC01",
            "dataset": {"name": "A", "source": "custom", "path": "data/a.csv"},
            "task_type": "classification",
            "modality": "tabular",
            "target_column": "y",
            "expected_architecture": "lightgbm",
        },
        {
            "id": "TC01",
            "dataset": {"name": "B", "source": "custom", "path": "data/b.csv"},
            "task_type": "classification",
            "modality": "tabular",
            "target_column": "y",
            "expected_architecture": "lightgbm",
        },
    ]
    problems_file = tmp_path / "problems.json"
    with open(problems_file, "w", encoding="utf-8") as f:
        json.dump(dup_problems, f)

    # Create both files
    for prob in dup_problems:
        ds_path = tmp_path / prob["dataset"]["path"]
        ds_path.parent.mkdir(parents=True, exist_ok=True)
        with open(ds_path, "w", encoding="utf-8") as f:
            f.write("y\n1\n2\n")

    with patch("evaluation.benchmark_validation.BENCHMARK_PATH", problems_file):
        from evaluation.benchmark_validation import validate_all

        report = validate_all()
        assert report["failed"] >= 1
        dup_issues = [r for r in report["results"] if not r["passed"]]
        assert any("Duplicate" in issue for r in dup_issues for issue in r["issues"])


@patch("evaluation.benchmark_validation.BENCHMARK_PATH")
def test_validate_all_target_column_missing(mock_bp, tmp_path):
    """A problem with a missing target column should fail."""
    no_target_file = tmp_path / "data" / "no_target.csv"
    no_target_file.parent.mkdir(parents=True, exist_ok=True)
    with open(no_target_file, "w", encoding="utf-8") as f:
        f.write("feat1,feat2\n1,2\n3,4\n")

    no_target_problem = [
        {
            "id": "TC99",
            "dataset": {"name": "NoTarget", "source": "custom", "path": str(no_target_file)},
            "task_type": "classification",
            "modality": "tabular",
            "target_column": "y",
            "expected_architecture": "lightgbm",
        }
    ]
    problems_file = tmp_path / "problems.json"
    with open(problems_file, "w", encoding="utf-8") as f:
        json.dump(no_target_problem, f)

    with patch("evaluation.benchmark_validation.BENCHMARK_PATH", problems_file):
        from evaluation.benchmark_validation import validate_all

        report = validate_all()
        assert report["failed"] == 1
        assert "target column 'y' not found" in report["results"][0]["issues"][0].lower()


def test_print_validation_report(capsys):
    from evaluation.benchmark_validation import print_validation_report

    report = {
        "total_problems": 2,
        "passed": 1,
        "failed": 1,
        "results": [
            {
                "problem_id": "TC01",
                "dataset_name": "Test",
                "passed": True,
                "issues": [],
                "warnings": [],
            },
            {
                "problem_id": "TC02",
                "dataset_name": "Bad",
                "passed": False,
                "issues": ["File not found"],
                "warnings": [],
            },
        ],
        "summary": ["1/2 problems have failures"],
    }
    print_validation_report(report)
    captured = capsys.readouterr()
    assert "BENCHMARK VALIDATION" in captured.out
    assert "TC02" in captured.out
    assert "File not found" in captured.out

"""Unit tests for Arbiter error-subset analysis — pure functions, no I/O."""

import numpy as np
import pandas as pd

from agents.arbiter.tools import (
    _error_mask,
    analyze_error_subset,
)


class TestErrorMask:
    def test_classification_mismatch(self):
        mask = _error_mask([0, 1, 0, 1], [0, 1, 1, 0], "classification")
        assert mask.tolist() == [False, False, True, True]

    def test_regression_relative_tolerance(self):
        # 0.5 off from 5.0 = 10% → boundary; 1.0 off from 5.0 = 20% → error
        mask = _error_mask([5.0, 5.0], [5.5, 4.0], "regression", tol=0.10)
        assert mask.tolist() == [False, True]

    def test_mismatched_lengths(self):
        mask = _error_mask([0, 1], [0], "classification")
        assert mask.tolist() == [False, False]


class TestAnalyzeErrorSubset:
    def test_label_analysis_without_features(self):
        y_true = [0, 0, 0, 1, 1, 1]
        y_pred = [0, 0, 1, 1, 0, 0]
        result = analyze_error_subset(None, y_true, y_pred, task_type="classification")
        assert result["has_features"] is False
        assert result["segments"] == []
        assert len(result["labels"]) == 2
        worst = result["labels"][0]  # sorted by error_rate desc
        assert worst["label"] == "1"
        assert abs(worst["error_rate"] - 2 / 3) < 0.001
        assert "label '1'" in result["summary"]

    def test_feature_segments_surface_high_error_region(self):
        # Feature 'age': rows 0-2 are young (high error), rows 3-9 old (correct).
        n = 100
        age = np.linspace(18, 80, n)
        y_true = np.where(age < 30, 1, 0)
        # Model gets everyone under 30 wrong, everyone over 30 right.
        y_pred = np.where(age < 30, 0, 0)
        X = pd.DataFrame({"age": age})

        result = analyze_error_subset(X, y_true, y_pred, task_type="classification", n_segments=5)
        assert result["has_features"] is True
        assert result["segments"]
        # The worst segment must be the low-age bin where all samples are errors.
        worst = result["segments"][0]
        assert worst["feature"] == "age"
        assert worst["error_rate"] == 1.0
        assert "age" in result["summary"]

    def test_categorical_feature_segmentation(self):
        # Category 'rare' is always wrong; others right.
        y_true = np.array([0, 1, 0, 1, 0, 1, 0, 1])
        y_pred = np.array([0, 1, 0, 1, 0, 1, 0, 1])
        y_pred[2] = 1  # row 2 is 'rare' (y_true=0) → error
        X = pd.DataFrame({"cat": ["a", "b", "rare", "a", "b", "a", "b", "a"]})

        result = analyze_error_subset(X, y_true, y_pred, task_type="classification", n_segments=5)
        segments = {s["segment"]: s for s in result["segments"]}
        assert "rare" in segments
        assert segments["rare"]["error_rate"] == 1.0
        assert segments["rare"]["n_samples"] == 1

    def test_ndarray_input_with_feature_names(self):
        X = np.array([[1.0], [2.0], [3.0], [4.0], [5.0], [6.0]])
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_pred = np.array([0, 0, 0, 1, 1, 1])
        result = analyze_error_subset(
            X,
            y_true,
            y_pred,
            feature_names=["value"],
            task_type="classification",
        )
        assert result["has_features"] is True
        # Perfect predictions → all segments zero error → "no error subset"
        assert "no error subset" in result["summary"].lower()

    def test_regression_error_subset(self):
        X = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0]})
        y_true = np.array([10.0, 10.0, 10.0, 10.0, 10.0])
        y_pred = np.array([50.0, 12.0, 11.0, 10.5, 10.1])
        result = analyze_error_subset(X, y_true, y_pred, task_type="regression", n_segments=5)
        assert result["has_features"] is True
        assert result["segments"]
        # Worst segment is the low-x bin containing the 50.0 prediction.
        worst = result["segments"][0]
        assert worst["error_rate"] == 1.0
        assert worst["mean_error"] > 5.0

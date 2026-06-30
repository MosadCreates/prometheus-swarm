"""Unit tests for Dissect error taxonomy. Tests each of the 11 error categories."""

from agents.dissect.taxonomy import classify_error, get_repair_strategy


def test_shape_mismatch():
    cat, conf, method = classify_error("ValueError", "X has 45 features, model expects 40")
    assert cat == "shape_mismatch"
    assert method == "regex"


def test_sparse_matrix():
    cat, conf, method = classify_error("TypeError", "SMOTE does not support sparse matrices")
    assert cat == "sparse_matrix"
    assert method == "regex"


def test_oom():
    cat, conf, method = classify_error("MemoryError", "cannot allocate array of size 5GB")
    assert cat == "oom"
    assert method == "regex"


def test_cuda_oom():
    cat, conf, method = classify_error("RuntimeError", "CUDA out of memory. Tried to allocate 2GB")
    assert cat == "cuda_oom"
    assert method == "regex"


def test_missing_column():
    cat, conf, method = classify_error("KeyError", "income_log not found in DataFrame")
    assert cat == "missing_column"
    assert method == "regex"


def test_dtype_mismatch():
    cat, conf, method = classify_error("ValueError", "could not convert string to float: 'Male'")
    assert cat == "dtype_mismatch"
    assert method == "regex"


def test_convergence_failure():
    cat, conf, method = classify_error("ConvergenceWarning", "lbfgs failed to converge")
    assert cat == "convergence_failure"
    assert method == "regex"


def test_import_error():
    cat, conf, method = classify_error("ModuleNotFoundError", "No module named 'lightgbm'")
    assert cat == "import_error"
    assert method == "regex"


def test_nan_propagation():
    cat, conf, method = classify_error("ValueError", "Input contains NaN, infinity or a value too large")
    assert cat == "nan_propagation"
    assert method == "regex"


def test_checkpoint_corruption():
    cat, conf, method = classify_error("UnpicklingError", "invalid load key, 'v'.")
    assert cat == "checkpoint_corruption"
    assert method == "regex"


def test_novel_error_fallback():
    cat, conf, method = classify_error("SomeStrangeError", "something completely unexpected")
    assert cat == "novel_error"
    assert method == "llm_classification"


def test_get_repair_strategy():
    strategy = get_repair_strategy("shape_mismatch")
    assert "feature" in strategy.lower()

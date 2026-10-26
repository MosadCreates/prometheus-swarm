"""Hermetic tests for Harbor serving-template extras: confidence field, model-type dispatch.

The serving template is a ``.format()`` string with escaped braces, so we render it
first, then compile / extract functions. No FastAPI, no ONNX, no Docker required.
"""

import ast
import logging

import numpy as np

from agents.harbor.serving_template import SERVING_TEMPLATE

logger = logging.getLogger("test-harbor")


def _render_template() -> str:
    return SERVING_TEMPLATE.format(
        model_path="model.onnx",
        model_format="onnx",
        model_name="test-model",
        contract_path="",
    )


def _extract_function(name: str):
    """Render the template, then exec just ``name``'s def into a fresh namespace."""
    code = _render_template()
    tree = ast.parse(code)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            ns: dict = {"np": np, "logger": logger}
            exec(compile(ast.Module([node], []), "<serving-gen>", "exec"), ns)  # noqa: S102
            return ns[name]
    raise AssertionError(f"Function '{name}' not found in rendered serving template")


def test_rendered_template_compiles():
    """Escaped braces must survive .format() and yield valid Python."""
    code = _render_template()
    tree = ast.parse(code)  # raises SyntaxError if escaping is broken
    defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert "_classifier_confidences" in defs
    assert "_apply_preprocessing" in defs


class TestClassifierConfidences:
    def setup_method(self):
        self.fn = _extract_function("_classifier_confidences")

    def test_list_of_dicts(self):
        proba = [{"0": 0.9, "1": 0.1}, {"0": 0.2, "1": 0.8}]
        assert self.fn(proba) == [0.9, 0.8]

    def test_2d_array_max_axis1(self):
        proba = np.array([[0.9, 0.1], [0.3, 0.7]])
        assert self.fn(proba) == [0.9, 0.7]

    def test_1d_array_symmetric(self):
        # Binary sigmoid-style single-probability output
        assert self.fn(np.array([0.9, 0.4])) == [0.9, 0.6]

    def test_garbage_returns_empty(self):
        assert self.fn("not probabilities") == []


def test_predict_onnx_path_contains_confidence():
    """The ONNX predict branch must emit result['confidence']."""
    code = _render_template()
    assert 'result["confidence"] = confidences' in code
    assert "_classifier_confidences(proba_value)" in code


def test_predict_pickle_path_contains_confidence():
    code = _render_template()
    assert 'result["confidence"] = confidences' in code
    assert "_classifier_confidences(proba)" in code

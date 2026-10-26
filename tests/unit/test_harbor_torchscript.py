"""Unit tests for Harbor TorchScript / PyTorch serialization.

Hermetic by design: model-type detection and the serialize_to_onnx dispatch
need no torch installed. The torch-dependent trace/save tests are guarded by
``pytest.importorskip("torch")`` so the suite stays green on venvs without it.
"""

import pickle
import sys

import pytest

from agents.forge.template_renderer import select_and_render, validate_script
from agents.harbor.serving_template import SERVING_TEMPLATE
from agents.harbor.tools import (
    _detect_model_type,
    _get_n_features,
    serialize_pytorch,
    serialize_to_onnx,
)


# ── _detect_model_type ───────────────────────────────────────────────────────


class _FakeModule:
    """Real ``__module__`` (picklable); detected as pytorch via the class name."""


class _FakeTabNet:
    __module__ = "pytorch_tabnet.tab_model"


class _FakeSklearn:
    __module__ = "sklearn.tree"


class _FakeLightGBM:
    __module__ = "lightgbm.sklearn"


def test_detect_torch_module():
    # Class name contains "Module" → detected as pytorch without torch installed.
    assert _detect_model_type(_FakeModule()) == "pytorch"


def test_detect_tabnet_module():
    assert _detect_model_type(_FakeTabNet()) == "pytorch"


def test_detect_non_torch_unchanged():
    assert _detect_model_type(_FakeSklearn()) == "sklearn_model"
    assert _detect_model_type(_FakeLightGBM()) == "lightgbm"


def test_get_n_features_input_dim():
    class _HasInputDim:
        input_dim = 17

    assert _get_n_features(_HasInputDim()) == 17


# ── serialize_to_onnx → pytorch routing (no torch needed) ────────────────────


def test_serialize_to_onnx_routes_pytorch(tmp_path, monkeypatch):
    ckpt = tmp_path / "best.ckpt"
    with open(ckpt, "wb") as f:
        pickle.dump({"model": _FakeModule()}, f)

    captured = {}

    def fake_serialize(model, path):
        captured["model"] = model
        return True, str(path).replace(".onnx", ".pt")

    monkeypatch.setattr("agents.harbor.tools.serialize_pytorch", fake_serialize)

    ok, msg = serialize_to_onnx(str(ckpt), str(tmp_path / "model.onnx"))
    assert ok
    assert msg.endswith(".pt")
    assert isinstance(captured["model"], _FakeModule)


# ── serialize_pytorch ────────────────────────────────────────────────────────


def test_serialize_pytorch_without_torch(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    ok, msg = serialize_pytorch(object(), str(tmp_path / "model.pt"))
    assert not ok
    assert "torch is not installed" in msg


def test_serialize_pytorch_traces_linear(tmp_path):
    torch = pytest.importorskip("torch")
    model = torch.nn.Linear(4, 2)
    model.eval()

    ok, msg = serialize_pytorch(model, str(tmp_path / "model.pt"))
    assert ok
    assert msg.endswith(".pt")

    loaded = torch.jit.load(msg, map_location="cpu")
    with torch.no_grad():
        pred = loaded(torch.zeros(1, 4))
    assert tuple(pred.shape) == (1, 2)


def test_serialize_pytorch_tabnet_wrapper_softmax(tmp_path):
    torch = pytest.importorskip("torch")

    class _Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = torch.nn.Linear(4, 2)

        def forward(self, x):
            return self.fc(x), None  # TabNet returns (logits, M_loss)

    class _TabnetLike:
        network = _Net()
        task = "classification"
        n_features_in_ = 4

    ok, msg = serialize_pytorch(_TabnetLike(), str(tmp_path / "model.pt"))
    assert ok

    loaded = torch.jit.load(msg, map_location="cpu")
    with torch.no_grad():
        out = loaded(torch.full((1, 4), 5.0))
    # classifier wrapper applies softmax → rows are valid probabilities
    assert torch.allclose(out.sum(dim=1), torch.ones(1), atol=1e-3)
    assert bool((out >= 0).all() and (out <= 1).all())


def test_serialize_pytorch_fallback_to_pth(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    model = torch.nn.Linear(4, 2)

    def boom(*args, **kwargs):
        raise RuntimeError("simulated trace failure")

    monkeypatch.setattr(torch.jit, "trace", boom)
    ok, msg = serialize_pytorch(model, str(tmp_path / "model.pt"))
    assert ok
    assert msg.endswith(".pth")

    loaded = torch.load(msg, map_location="cpu")
    assert isinstance(loaded, torch.nn.Linear)


# ── tabnet template emits the TorchScript artifact ───────────────────────────

_TABNET_BRIEF = {
    "job_id": "torch-job",
    "problem_description": "Tabular classification",
    "task_type": "classification",
    "modality": "tabular",
    "target_column": "y",
    "evaluation_metric": "auc_roc",
    "dataset": {
        "file_path": "./tests/fixtures/titanic.csv",
        "num_rows": 891,
        "num_columns": 6,
        "column_types": {
            "f1": "numeric",
            "f2": "numeric",
            "f3": "numeric",
            "f4": "numeric",
            "f5": "categorical",
            "y": "target",
        },
    },
}

_TABNET_REGRESSION_BRIEF = {**_TABNET_BRIEF, "task_type": "regression", "evaluation_metric": "rmse"}


def test_tabnet_template_renders_torchscript_block():
    script = select_and_render(_TABNET_BRIEF, "torch-job", None, "tabnet")
    assert "TorchScript artifact" in script
    assert "model.pt" in script
    assert "torch.jit.trace" in script
    assert "torch.jit.save" in script
    assert "model.network, True" in script  # binary → classify=True
    assert validate_script(script)


def test_tabnet_template_regression_not_classified():
    script = select_and_render(_TABNET_REGRESSION_BRIEF, "torch-job", None, "tabnet")
    assert "model.network, False" in script
    assert validate_script(script)


# ── serving template supports torchscript/torch formats ──────────────────────


def test_serving_template_has_torch_loader():
    assert 'torch.jit.load(_model_path, map_location="cpu")' in SERVING_TEMPLATE
    assert 'torch.load(_model_path, map_location="cpu")' in SERVING_TEMPLATE
    assert '_model_format in ("torchscript", "torch")' in SERVING_TEMPLATE


def test_serving_template_torch_predict_branch():
    assert "input_array = _apply_preprocessing(df).astype(np.float32)" in SERVING_TEMPLATE
    assert "torch.from_numpy(input_array)" in SERVING_TEMPLATE
    assert 'result["confidence"] = confidences' in SERVING_TEMPLATE

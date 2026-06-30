"""ONNX model loading and inference runtime for Harbor deployments."""

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class ONNXRuntime:
    """Wrapper around ONNX Runtime inference session."""

    def __init__(self, model_path: str):
        import onnxruntime as ort

        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")

        self.session = ort.InferenceSession(str(self.model_path))
        self.input_name = self.session.get_inputs()[0].name
        self.input_shape = self.session.get_inputs()[0].shape
        self.output_names = [o.name for o in self.session.get_outputs()]

        logger.info(f"ONNX model loaded: {self.model_path.name} | inputs={self.input_name} shape={self.input_shape}")

    def predict(self, data: np.ndarray) -> list[Any]:
        """Run inference on input data.

        Args:
            data: Numpy array of shape (batch_size, n_features)

        Returns:
            List of predictions
        """
        ort_inputs = {self.input_name: data.astype(np.float32)}
        outputs = self.session.run(self.output_names, ort_inputs)
        return outputs[0].tolist()

    def predict_batch(self, batch: list[list[float]]) -> list[Any]:
        """Run inference on a batch of samples."""
        arr = np.array(batch, dtype=np.float32)
        return self.predict(arr)

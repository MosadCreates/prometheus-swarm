"""Checkpoint management: save, restore, integrity check."""

import logging
import os
import pickle

logger = logging.getLogger(__name__)


class CheckpointManager:
    def __init__(self, base_dir: str = "./outputs"):
        self.base_dir = base_dir

    def get_checkpoint_path(self, job_id: str) -> str:
        return os.path.join(self.base_dir, job_id, "checkpoints", "best.ckpt")

    def checkpoint_exists(self, job_id: str) -> bool:
        return os.path.exists(self.get_checkpoint_path(job_id))

    def save_checkpoint(self, job_id: str, model) -> str:
        path = self.get_checkpoint_path(job_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(model, f)
        logger.info(f"[job={job_id}] Checkpoint saved to {path}")
        return path

    def load_checkpoint(self, job_id: str):
        path = self.get_checkpoint_path(job_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Checkpoint not found: {path}")
        with open(path, "rb") as f:
            return pickle.load(f)

    def verify_integrity(self, job_id: str) -> bool:
        path = self.get_checkpoint_path(job_id)
        if not os.path.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                pickle.load(f)
            return True
        except Exception:
            return False

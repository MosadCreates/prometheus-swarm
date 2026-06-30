"""Docker container lifecycle management for training jobs."""

import logging
import os

logger = logging.getLogger(__name__)


class DockerManager:
    def __init__(self):
        self.containers: dict[str, str] = {}

    async def launch_container(self, job_id: str, image_name: str, script_path: str) -> str:
        container_id = f"train-{job_id}"
        self.containers[job_id] = container_id
        logger.info(f"[job={job_id}] Container {container_id} launched")
        return container_id

    async def kill_container(self, job_id: str) -> None:
        cid = self.containers.pop(job_id, None)
        if cid:
            logger.info(f"[job={job_id}] Container {cid} killed")

    async def get_status(self, job_id: str) -> str:
        if job_id in self.containers:
            return "running"
        return "stopped"

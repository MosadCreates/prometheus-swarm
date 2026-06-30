"""Docker container lifecycle management for training jobs.

Uses docker Python SDK (docker>=7.1.0). All paths are resolved to absolute
before mounting as Docker volumes for cross-platform support (Windows compat).

Synchronous Docker SDK calls (container.wait, container.logs) are wrapped in
asyncio.get_event_loop().run_in_executor() to avoid blocking the event loop.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker containers for training jobs.

    The caller is responsible for ensuring the Docker daemon is running.
    Container names follow the pattern ``train-{job_id}``.

    Args:
        training_image: Docker image to use for training containers.
                        Defaults to env var TRAINING_IMAGE_NAME or "prometheus-training-base".
    """

    def __init__(self, training_image: str | None = None):
        self.training_image = training_image or os.getenv(
            "TRAINING_IMAGE_NAME", "prometheus-training-base",
        )
        self._client = None
        self._containers: dict[str, str] = {}

    async def _get_client(self):
        """Lazy-init docker client."""
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    async def launch_container(
        self,
        job_id: str,
        image_name: str | None = None,
        script_path: str | None = None,
        run_cmd: list[str] | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | None = None,
    ) -> str:
        """Launch a Docker container for a training job.

        Args:
            job_id: Unique job identifier
            image_name: Docker image name (defaults to self.training_image)
            script_path: Path to the training script in the container
            run_cmd: Command override inside container (e.g. ["python", "/app/script.py"])
            volumes: Docker volume mounts dict in SDK format:
                     {"host_path": {"bind": "/container/path", "mode": "ro"}}
                     If not provided, mounts scripts/, data/, outputs/ automatically.
            environment: Environment variables dict for the container
            working_dir: Working directory inside container

        Returns:
            Container ID string
        """
        client = await self._get_client()
        image = image_name or self.training_image
        container_name = f"train-{job_id}"

        # Auto-mount standard paths if no custom volumes provided
        if volumes is None:
            root = os.path.abspath(".")
            volumes = {
                os.path.abspath("scripts"): {"bind": "/app/scripts", "mode": "ro"},
                os.path.abspath("data"): {"bind": "/app/data", "mode": "ro"},
                os.path.abspath("outputs"): {"bind": "/app/outputs", "mode": "rw"},
            }

        if environment is None:
            environment = {}

        # Default command: run the training script
        if run_cmd is None and script_path:
            script_name = os.path.basename(script_path)
            run_cmd = ["python", f"/app/scripts/{script_name}"]

        container = client.containers.run(
            image=image,
            command=run_cmd,
            name=container_name,
            detach=True,
            volumes=volumes,
            environment=environment,
            working_dir=working_dir or "/app",
            stdout=True,
            stderr=True,
            remove=False,
        )

        self._containers[job_id] = container.id
        logger.info(
            f"[job={job_id}] Container {container.id[:12]} launched "
            f"from image {image}, name={container_name}"
        )
        return container.id

    async def wait_for_exit(
        self, job_id: str, timeout: int = 3600,
    ) -> tuple[int, str]:
        """Wait for a training container to exit and return its exit code + logs.

        Uses run_in_executor to avoid blocking the event loop on synchronous
        Docker SDK calls (container.wait, container.logs).

        Args:
            job_id: Job identifier
            timeout: Max seconds to wait

        Returns:
            (exit_code, combined_stdout_stderr)
        """
        client = await self._get_client()
        cid = self._containers.get(job_id)
        if not cid:
            return -1, "Container not found"

        loop = asyncio.get_event_loop()
        try:
            container = client.containers.get(cid)
            result = await loop.run_in_executor(
                None, lambda: container.wait(timeout=timeout),
            )
            exit_code = result.get("StatusCode", -1)
            logs = await loop.run_in_executor(
                None, lambda: container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace"),
            )
            return exit_code, logs
        except Exception as e:
            return -1, str(e)

    async def kill_container(self, job_id: str) -> None:
        """Stop and remove a training container."""
        cid = self._containers.pop(job_id, None)
        if not cid:
            return

        client = await self._get_client()
        try:
            container = client.containers.get(cid)
            container.stop(timeout=5)
            container.remove()
            logger.info(f"[job={job_id}] Container {cid[:12]} killed and removed")
        except Exception as e:
            logger.warning(f"[job={job_id}] Error killing container {cid[:12]}: {e}")

    async def get_status(self, job_id: str) -> str:
        """Get container status: running, exited, or stopped."""
        cid = self._containers.get(job_id)
        if not cid:
            return "stopped"

        client = await self._get_client()
        try:
            container = client.containers.get(cid)
            return container.status
        except Exception:
            return "stopped"

    async def close(self) -> None:
        """Release docker client resources."""
        if self._client:
            self._client.close()
            self._client = None

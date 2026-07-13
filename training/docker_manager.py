"""Docker container lifecycle management for training jobs.

Uses docker Python SDK (docker>=7.1.0). All paths are resolved to absolute
before mounting as Docker volumes for cross-platform support (Windows compat).

Synchronous Docker SDK calls (container.wait, container.logs) are wrapped in
asyncio.get_event_loop().run_in_executor() to avoid blocking the event loop.
"""

import asyncio
import logging
import os
import shutil
from typing import Any
from runtime.paths import get_paths

logger = logging.getLogger(__name__)


class DockerManager:
    """Manages Docker containers for training jobs.

    Args:
        training_image: Docker image to use for training containers.
                        Defaults to env var TRAINING_IMAGE_NAME or "prometheus-training-base".
    """

    def __init__(self, training_image: str | None = None):
        self.training_image = training_image or os.getenv(
            "TRAINING_IMAGE_NAME",
            "prometheus-training-base",
        )
        self._client = None
        self._containers: dict[str, str] = {}

    async def _get_client(self):
        if self._client is None:
            import docker

            self._client = docker.from_env()
        return self._client

    async def check_docker_available(self) -> tuple[bool, str]:
        """Check if Docker is installed and the daemon is running.

        Returns:
            (available, message) — message is empty on success, contains
            actionable error text on failure.
        """
        if not shutil.which("docker"):
            return False, (
                "Docker is not installed or not found in PATH.\n"
                "  Install Docker Desktop from https://www.docker.com/products/docker-desktop/\n"
                "  Then restart this mission."
            )

        try:
            import docker

            client = docker.from_env()
            client.ping()
            client.close()
        except docker.errors.DockerException as e:
            msg = str(e).lower()
            if "connection" in msg or "daemon" in msg:
                return False, (
                    "Docker daemon is not running.\n" "  Start Docker Desktop and retry."
                )
            return False, f"Docker error: {e}"
        except Exception as e:
            return False, f"Docker check failed: {e}"

        return True, ""

    async def check_image_exists(self, image_name: str | None = None) -> tuple[bool, str]:
        """Check if the training Docker image exists locally.

        Args:
            image_name: Image to check (defaults to self.training_image)

        Returns:
            (exists, message)
        """
        image = image_name or self.training_image
        try:
            import docker

            client = docker.from_env()
            client.images.get(image)
            client.close()
            return True, ""
        except docker.errors.ImageNotFound:
            return False, (
                f"Training image '{image}' not found.\n"
                f"  Build it with: docker build -t {image} "
                f"-f training/base_training_image/Dockerfile ."
            )
        except Exception as e:
            return False, f"Image check failed: {e}"

    async def launch_container(
        self,
        job_id: str,
        image_name: str | None = None,
        script_path: str | None = None,
        run_cmd: list[str] | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | None = None,
        container_name_prefix: str = "train",
        auto_remove: bool = False,
    ) -> str:
        """Launch a Docker container for a training job.

        Args:
            job_id: Unique job identifier
            image_name: Docker image name (defaults to self.training_image)
            script_path: Path to the training script in the container
            run_cmd: Command override inside container
            volumes: Docker volume mounts dict in SDK format
            environment: Environment variables dict for the container
            working_dir: Working directory inside container
            container_name_prefix: Prefix for container name (default "train",
                                   use "prometheus-train" for CLI mode)
            auto_remove: Remove container automatically after exit

        Returns:
            Container ID string
        """
        client = await self._get_client()
        image = image_name or self.training_image
        container_name = f"{container_name_prefix}-{job_id}"

        if volumes is None:
            _p = get_paths()
            volumes = {
                str(_p.scripts.resolve()): {"bind": str(_p.container_scripts), "mode": "ro"},
                str(_p.data.resolve()): {"bind": str(_p.container_data), "mode": "ro"},
                str(_p.outputs.resolve()): {"bind": str(_p.container_outputs), "mode": "rw"},
            }

        if environment is None:
            environment = {}

        if run_cmd is None and script_path:
            script_name = os.path.basename(script_path)
            run_cmd = [f"/app/scripts/{script_name}"]

        container = client.containers.run(
            image=image,
            command=run_cmd,
            entrypoint=["python"],
            name=container_name,
            detach=True,
            volumes=volumes,
            environment=environment,
            working_dir=working_dir or "/app",
            stdout=True,
            stderr=True,
            remove=auto_remove,
        )

        self._containers[job_id] = container.id
        logger.info(
            f"[job={job_id}] Container {container.id[:12]} launched "
            f"from image {image}, name={container_name}"
        )
        return container.id

    async def stream_logs(
        self,
        job_id: str,
        callback: Any = None,
    ) -> tuple[int, str, str, str]:
        """Stream container logs line-by-line via callback, then return exit code + logs.

        Args:
            job_id: Job identifier
            callback: Optional callable receiving each decoded log line

        Returns:
            (exit_code, full_combined_log, stdout_log, stderr_log)
        """
        client = await self._get_client()
        cid = self._containers.get(job_id)
        if not cid:
            return -1, "Container not found", "", ""

        loop = asyncio.get_event_loop()
        try:
            container = client.containers.get(cid)
        except Exception as ex:
            import docker as _docker

            if not isinstance(ex, _docker.errors.NotFound):
                raise
            logger.warning(
                f"[job={job_id}] Container {cid[:12]} not found (removed before log read)"
            )
            return -1, f"Container {cid[:12]} not found", "", ""

        all_lines: list[str] = []
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        try:
            try:
                log_stream = container.logs(stdout=True, stderr=True, stream=True, follow=True)
                for chunk in log_stream:
                    line = chunk.decode("utf-8", errors="replace").rstrip()
                    all_lines.append(line)
                    if callback:
                        callback(line)
            except Exception:
                pass

            result = await loop.run_in_executor(
                None,
                lambda: container.wait(timeout=30),
            )
            exit_code = result.get("StatusCode", -1)
        finally:
            try:
                container.remove()
            except Exception:
                pass

        full_log = "\n".join(all_lines)

        return exit_code, full_log, "\n".join(stdout_lines), "\n".join(stderr_lines)

    async def wait_for_exit(
        self,
        job_id: str,
        timeout: int = 3600,
    ) -> tuple[int, str]:
        """Wait for a training container to exit and return its exit code + logs."""
        client = await self._get_client()
        cid = self._containers.get(job_id)
        if not cid:
            return -1, "Container not found"

        loop = asyncio.get_event_loop()
        try:
            container = client.containers.get(cid)
            result = await loop.run_in_executor(
                None,
                lambda: container.wait(timeout=timeout),
            )
            exit_code = result.get("StatusCode", -1)
            logs = await loop.run_in_executor(
                None,
                lambda: container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace"),
            )
            return exit_code, logs
        except Exception as e:
            return -1, str(e)

    async def kill_container(self, job_id: str, container_name_prefix: str = "train") -> None:
        """Stop and remove a training container.

        Args:
            job_id: Job identifier
            container_name_prefix: Prefix used when launching (default "train")
        """
        cid = self._containers.pop(job_id, None)
        client = await self._get_client()

        container = None
        if cid:
            try:
                container = client.containers.get(cid)
            except Exception:
                pass

        if not container:
            for prefix in ("prometheus-train", "train"):
                try:
                    container = client.containers.get(f"{prefix}-{job_id}")
                    break
                except Exception:
                    pass

        if container:
            try:
                container.stop(timeout=5)
                container.remove()
                logger.info(f"[job={job_id}] Container killed and removed")
            except Exception as e:
                logger.warning(f"[job={job_id}] Error killing container: {e}")

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

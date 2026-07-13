import subprocess

import docker


def get_client():
    return docker.from_env()


def _get_host_port(ports: dict) -> int | None:
    """Extract the host port from a Docker container's port mapping."""
    for container_port, bindings in ports.items():
        if bindings:
            try:
                return int(bindings[0]["HostPort"])
            except (KeyError, ValueError, IndexError):
                pass
    return None


def _check_health(host_port: int) -> str:
    """Check /health on the serving container."""
    import httpx

    try:
        r = httpx.get(f"http://localhost:{host_port}/health", timeout=3)
        if r.status_code == 200:
            data = r.json()
            return "healthy" if data.get("status") == "healthy" else data.get("status", "unknown")
        return f"HTTP {r.status_code}"
    except Exception:
        return "unreachable"


def list_serving_containers() -> list[dict]:
    client = get_client()
    containers = client.containers.list(filters={"name": "prometheus-serving-"})
    result = []
    for c in containers:
        try:
            img = c.image.tags[0] if c.image.tags else c.image.short_id
        except Exception:
            img = "unknown"
        host_port = _get_host_port(c.ports)
        health = _check_health(host_port) if host_port else "n/a"
        # Extract job_id prefix: prometheus-serving-{job_id_prefix}
        job_id_prefix = c.name.replace("prometheus-serving-", "") if c.name else "?"
        result.append(
            {
                "name": c.name,
                "job_id": job_id_prefix,
                "status": c.status,
                "image": img,
                "ports": c.ports,
                "host_port": host_port,
                "health": health,
            }
        )
    # Sort by host_port for stable display
    result.sort(key=lambda r: r["host_port"] or 9999)
    return result


def get_container_logs(name: str, tail: int = 100) -> str:
    client = get_client()
    container = client.containers.get(name)
    return container.logs(tail=tail).decode("utf-8", errors="replace")


def stop_and_remove(name: str) -> None:
    client = get_client()
    container = client.containers.get(name)
    container.stop()
    container.remove()

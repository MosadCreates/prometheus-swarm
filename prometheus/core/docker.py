import docker


def get_client():
    return docker.from_env()


def list_serving_containers() -> list[dict]:
    client = get_client()
    containers = client.containers.list(all=True, filters={"name": "prometheus-serving-"})
    result = []
    for c in containers:
        try:
            img = c.image.tags[0] if c.image.tags else c.image.short_id
        except Exception:
            img = "unknown"
        result.append({"name": c.name, "status": c.status, "image": img, "ports": c.ports})
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

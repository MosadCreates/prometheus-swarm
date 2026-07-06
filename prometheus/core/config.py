import os
from pathlib import Path


REQUIRED_KEYS = ["ANTHROPIC_API_KEY", "REDIS_HOST", "REDIS_PORT"]


def read_env_file(project_root: Path) -> dict[str, str]:
    env_path = project_root / ".env"
    if not env_path.exists():
        return {}
    values = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def check_prerequisites(project_root: Path) -> list[dict]:
    results = []
    env = read_env_file(project_root)

    for key in REQUIRED_KEYS:
        val = env.get(key)
        results.append(
            {
                "name": f"env:{key}",
                "ok": bool(val) and "YOUR_KEY_HERE" not in val,
                "detail": "set" if val and "YOUR_KEY_HERE" not in val else "missing or placeholder",
            }
        )

    try:
        import docker

        docker.from_env().ping()
        results.append({"name": "docker", "ok": True, "detail": "daemon reachable"})
    except Exception as e:
        results.append({"name": "docker", "ok": False, "detail": str(e)})

    try:
        import redis as sync_redis

        host = env.get("REDIS_HOST", "localhost")
        port = int(env.get("REDIS_PORT", 6379))
        r = sync_redis.Redis(host=host, port=port, socket_connect_timeout=3)
        r.ping()
        r.close()
        results.append({"name": "redis", "ok": True, "detail": f"reachable at {host}:{port}"})
    except Exception as e:
        results.append({"name": "redis", "ok": False, "detail": str(e)})

    return results

import httpx


async def predict(endpoint_url: str, instances: list[dict] | dict) -> dict:
    payload = {"instances": instances} if isinstance(instances, list) else instances
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{endpoint_url}/predict", json=payload)
        resp.raise_for_status()
        return resp.json()

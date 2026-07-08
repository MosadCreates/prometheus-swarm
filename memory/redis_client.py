"""
Redis client singleton. All agents import this.
"""

import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class RedisClient:
    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._client = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        await self._client.ping()
        logger.info("Redis connected")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        serialized = json.dumps(value)
        if ttl_seconds:
            await self._client.setex(key, ttl_seconds, serialized)
        else:
            await self._client.set(key, serialized)

    async def get_json(self, key: str) -> Any | None:
        raw = await self._client.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set_str(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        if ttl_seconds:
            await self._client.setex(key, ttl_seconds, value)
        else:
            await self._client.set(key, value)

    async def get_str(self, key: str) -> str | None:
        return await self._client.get(key)

    async def incr(self, key: str) -> int:
        return await self._client.incr(key)

    async def rpush(self, list_key: str, value: str) -> None:
        await self._client.rpush(list_key, value)

    async def blpop(self, list_key: str, timeout: int = 0) -> str | None:
        result = await self._client.blpop(list_key, timeout=timeout)
        if result:
            return result[1]
        return None

    async def lindex(self, list_key: str, index: int) -> str | None:
        return await self._client.lindex(list_key, index)

    async def scan_keys(self, pattern: str, count: int = 100) -> list[str]:
        """Safe replacement for KEYS using SCAN.

        Iterates the keyspace with SCAN instead of blocking with KEYS.
        Returns all matching key names.
        """
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = await self._client.scan(
                cursor=cursor, match=pattern, count=count
            )
            keys.extend(batch)
            if cursor == 0:
                break
        return keys

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

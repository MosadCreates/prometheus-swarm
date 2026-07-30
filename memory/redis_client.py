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

    async def ensure_connected(self) -> bool:
        """Ping Redis and reconnect if stale."""
        try:
            if self._client is not None:
                await self._client.ping()
                return True
        except Exception:
            logger.warning("Redis connection stale — reconnecting...")
        try:
            await self.connect()
            return True
        except Exception as e:
            logger.error(f"Redis reconnection failed: {e}")
            return False

    async def close(self) -> None:
        if self._client:
            try:
                await self._client.aclose()
            except RuntimeError:
                pass  # Event loop already closed
            self._client = None

    def __del__(self) -> None:
        """Safeguard: suppress redis-py's __del__ error if event loop is gone.

        redis.asyncio's AbstractConnection.__del__ tries to close the
        underlying transport via the event loop, which raises
        ``RuntimeError: Event loop is closed`` when the connection is
        garbage-collected after shutdown.  We close the transport
        directly to prevent the error.
        """
        if self._client is None:
            return
        try:
            conn = self._client.connection
            if conn is not None:
                transport = getattr(conn, "_transport", None)
                if transport is not None:
                    transport.close()
        except Exception:
            pass

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
            cursor, batch = await self._client.scan(cursor=cursor, match=pattern, count=count)
            keys.extend(batch)
            if cursor == 0:
                break
        return keys

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    # ── List operations ────────────────────────────────────────────────

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        return await self._client.lrange(key, start, stop)

    async def lset(self, key: str, index: int, value: str) -> None:
        await self._client.lset(key, index, value)

    async def lpush(self, key: str, value: str) -> int:
        return await self._client.lpush(key, value)

    # ── Hash operations ────────────────────────────────────────────────

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        return await self._client.hincrby(key, field, amount)

    async def hset(self, key: str, field: str, value: str | int | float) -> int:
        return await self._client.hset(key, field, value)

    async def hget(self, key: str, field: str) -> str | None:
        return await self._client.hget(key, field)

    async def hgetall(self, key: str) -> dict[str, str]:
        return await self._client.hgetall(key)

    async def hdel(self, key: str, field: str) -> int:
        return await self._client.hdel(key, field)

    async def hexists(self, key: str, field: str) -> bool:
        return await self._client.hexists(key, field)

    # ── Set operations ─────────────────────────────────────────────────

    async def sadd(self, key: str, member: str) -> int:
        return await self._client.sadd(key, member)

    async def sismember(self, key: str, member: str) -> bool:
        return await self._client.sismember(key, member)

    async def smembers(self, key: str) -> set[str]:
        return await self._client.smembers(key)

    # ── Key operations ─────────────────────────────────────────────────

    async def expire(self, key: str, seconds: int) -> bool:
        return await self._client.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        return await self._client.ttl(key)

    async def exists(self, key: str) -> bool:
        return await self._client.exists(key)

    # ── Pipeline ───────────────────────────────────────────────────────

    def pipeline(self):
        return self._client.pipeline()

"""
Consumer ? reads events from Redis Streams via XREADGROUP.
"""

import json
import logging
from typing import Callable, Awaitable

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def ensure_consumer_group(
    redis_client: aioredis.Redis,
    stream_name: str,
    group_name: str,
) -> None:
    try:
        await redis_client.xgroup_create(
            stream_name, group_name, id="0", mkstream=True
        )
        logger.info(f"Created consumer group {group_name} on stream {stream_name}")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass
        else:
            raise


async def consume_one(
    redis_client: aioredis.Redis,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    handler: Callable[[dict], Awaitable[None]],
    block_ms: int = 0,
) -> None:
    results = await redis_client.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams={stream_name: ">"},
        count=1,
        block=block_ms,
    )

    if not results:
        return

    stream, messages = results[0]
    for msg_id, raw_fields in messages:
        message = {}
        for k, v in raw_fields.items():
            try:
                message[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                message[k] = v

        try:
            await handler(message)
            await redis_client.xack(stream_name, group_name, msg_id)
            logger.debug(f"ACK {msg_id} on {stream_name}/{group_name}")
        except Exception as e:
            logger.error(
                f"Handler failed for {msg_id} on {stream_name}/{group_name}: {e}"
            )
            raise


async def consume_loop(
    redis_client: aioredis.Redis,
    stream_name: str,
    group_name: str,
    consumer_name: str,
    handler: Callable[[dict], Awaitable[None]],
    stop_event_types: list[str] | None = None,
) -> None:
    while True:
        results = await redis_client.xreadgroup(
            groupname=group_name,
            consumername=consumer_name,
            streams={stream_name: ">"},
            count=1,
            block=0,
        )

        if not results:
            continue

        stream, messages = results[0]
        for msg_id, raw_fields in messages:
            message = {}
            for k, v in raw_fields.items():
                try:
                    message[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    message[k] = v

            await handler(message)
            await redis_client.xack(stream_name, group_name, msg_id)

            if stop_event_types and message.get("event_type") in stop_event_types:
                return

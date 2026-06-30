"""
Publisher ? sends events to Redis Streams via XADD.
All agents call publish() to send events. Never call XADD directly.
"""

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


async def publish(
    redis_client: aioredis.Redis,
    stream_name: str,
    event_type: str,
    payload: dict,
) -> str:
    full_payload = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }

    flat = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in full_payload.items()}

    msg_id = await redis_client.xadd(stream_name, flat)
    logger.debug(f"Published {event_type} to {stream_name} [{msg_id}]")
    return msg_id

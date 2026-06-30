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

    flat = {}
    for k, v in full_payload.items():
        if v is None:
            flat[k] = ""
        elif isinstance(v, (dict, list)):
            flat[k] = json.dumps(v)
        else:
            flat[k] = str(v)

    msg_id = await redis_client.xadd(stream_name, flat)
    logger.debug(f"Published {event_type} to {stream_name} [{msg_id}]")
    return msg_id

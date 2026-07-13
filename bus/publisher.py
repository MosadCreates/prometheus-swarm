"""
Publisher — sends events to Redis Streams via XADD.
All agents call publish() to send events. Never call XADD directly.

Accepts both typed EventPayload models and raw dicts for backward compatibility.
When a typed model is passed, it's automatically serialized via .to_redis_dict().
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from shared.metrics import REDIS_STREAM_MESSAGES

logger = logging.getLogger(__name__)


async def publish(
    redis_client: aioredis.Redis,
    stream_name: str,
    event_type: str,
    payload: dict | Any,
) -> str:
    if hasattr(payload, "to_redis_dict"):
        flat = payload.to_redis_dict()
    elif isinstance(payload, dict):
        flat = {
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        for k, v in list(flat.items()):
            if v is None:
                flat[k] = ""
            elif isinstance(v, (dict, list)):
                flat[k] = json.dumps(v)
            else:
                flat[k] = str(v)
    else:
        raise TypeError(
            f"publish() payload must be a dict or EventPayload model, "
            f"got {type(payload).__name__}"
        )

    msg_id = await redis_client.xadd(stream_name, flat)
    REDIS_STREAM_MESSAGES.labels(stream=stream_name, event_type=event_type).inc()
    logger.debug(f"Published {event_type} to {stream_name} [{msg_id}]")
    return msg_id

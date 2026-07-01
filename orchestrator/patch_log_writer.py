"""
Patch log writer ? single background process that reads from Redis patch_log_queue
and appends to research/patch_log.jsonl. This is the ONLY process that writes to
patch_log.jsonl.
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from filelock import FileLock

from dotenv import load_dotenv
import redis.asyncio as aioredis

load_dotenv()
logger = logging.getLogger(__name__)

PATCH_LOG_PATH = os.getenv("PATCH_LOG_PATH", "./research/patch_log.jsonl")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))


async def run_writer() -> None:
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    log_path = Path(PATCH_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Patch log writer started. Writing to {log_path}")

    while True:
        try:
            result = await r.blpop("patch_log_queue", timeout=5)
            if result is None:
                continue

            _, raw_entry = result
            entry = json.loads(raw_entry)

            lock_path = str(log_path) + ".lock"
            with FileLock(lock_path):
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")

            logger.debug(f"Wrote patch log entry: patch_id={entry.get('patch_id')}")

        except Exception as e:
            logger.error(f"Patch log writer error: {e}")
            await asyncio.sleep(1)

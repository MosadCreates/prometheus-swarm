# PLAN.md — Prometheus Swarm Build Plan
# Solo Build | Claude Sonnet API from Phase 0 | RTX GPU Available
# Owner: Mohamed Mosad Ghonaim | Nexora Lab
# Read CLAUDE.md first. This file answers HOW to build. CLAUDE.md answers WHAT to build.

---

## HOW TO READ THIS PLAN

Every step in this plan is written so an AI agent can execute it without asking you
anything. Every file has its full content described. Every command is copy-paste ready.
Every external resource you need to bring in is listed with exact download steps.

When a step says "YOU DO THIS" — that is something only you can do (download a file,
create an account, get a key). Everything else is handled by Claude Code.

LLM strategy:
- All phases (0–4): Claude Sonnet via Anthropic API (ANTHROPIC_MODEL env var)
- No local LLM. Claude Sonnet is used from day one for all agent LLM calls.
- API cost during dev is ~$5–15/day with moderate usage. Budget accordingly.

---

## BEFORE YOU START — EXTERNAL RESOURCES YOU NEED TO BRING

Do these once, before Phase 0. They take ~30 minutes total.

### A. Install Required Software

**Step 1 — Python 3.11**
Open terminal and run:
```bash
python3 --version
```
If it says 3.11.x or higher, skip this. If not:
- Windows: go to python.org/downloads → download Python 3.11.x → install with "Add to PATH" checked
- Mac: run `brew install python@3.11`
- Linux (Ubuntu): run `sudo apt install python3.11 python3.11-venv python3.11-pip`

**Step 2 — Docker Desktop**
Go to: https://www.docker.com/products/docker-desktop
Download for your OS. Install it. Open it. Wait until the whale icon in your taskbar is
green/running. You need Docker running for every session of this build.

**Step 3 — Git**
Run: `git --version`
If not installed:
- Windows: https://git-scm.com/download/win → download → install with defaults
- Mac: run `xcode-select --install`
- Linux: run `sudo apt install git`

**Step 4 — Anthropic API Key**
1. Go to: https://console.anthropic.com
2. Sign up or log in
3. Go to "API Keys" in the left menu
4. Click "Create Key"
5. Copy the key (starts with `sk-ant-...`)
6. You will paste this into `.env` during Phase 0 Day 1

**Step 5 — Node.js (for frontend, Phase 3 only)**
You don't need this until Phase 3. Skip for now.

### B. Get Your Datasets

**YOU DO THIS — 3 datasets needed:**

Dataset 1 — Titanic (used from Phase 1 gate onward):
1. Go to: https://www.kaggle.com/competitions/titanic/data
2. Create a free Kaggle account if you don't have one
3. Click "Download All"
4. Unzip the file
5. Copy `train.csv` to `data/titanic.csv` in your repo (do this after Phase 0 Day 1)

Dataset 2 — House Prices (used in Phase 3 E2E test):
1. Go to: https://www.kaggle.com/competitions/house-prices-advanced-regression-techniques/data
2. Click "Download All"
3. Copy `train.csv` to `data/house_prices.csv`

Dataset 3 — SMS Spam (used in Phase 3 E2E test):
1. Go to: https://www.kaggle.com/datasets/uciml/sms-spam-collection-dataset
2. Click "Download"
3. Unzip and copy `spam.csv` to `data/sms_spam.csv`

### C. GPU Setup (Optional but Recommended)

You have an RTX 5060 8GB. To use it for training:
Run:
```bash
nvidia-smi
```
If you see your GPU listed, Docker can use it. If you get "nvidia-smi not found":
- Go to: https://developer.nvidia.com/cuda-downloads
- Select your OS → download and install CUDA Toolkit 12.x
- Then install NVIDIA Container Toolkit:
  ```bash
  # Linux only:
  sudo apt install nvidia-container-toolkit
  sudo systemctl restart docker
  ```
- Windows: Docker Desktop handles GPU automatically after CUDA is installed



---

## PHASE 0 — FOUNDATION
**Duration: 5 days | Goal: All infrastructure running, bus layer proven end-to-end**

---

### DAY 0-1: Repository + Python Environment

**Morning — repo and venv:**
```bash
mkdir prometheus-swarm
cd prometheus-swarm
git init
python3.11 -m venv .venv
.venv\Scripts\Activate.ps1            # Windows PowerShell
# source .venv/bin/activate           # Mac/Linux
```

**Create every directory and __init__.py in one shot:**
```bash
mkdir -p agents/scout agents/forge agents/furnace agents/dissect agents/arbiter agents/harbor
mkdir -p memory/collections
mkdir -p training/base_training_image
mkdir -p serving/docker
mkdir -p scripts outputs data
mkdir -p bus orchestrator
mkdir -p tests/unit tests/integration tests/fixtures/injected_errors
mkdir -p research/benchmark/results research/paper
mkdir -p frontend/src/app/feed
mkdir -p infra/kubernetes infra/helm infra/monitoring

# Create all __init__.py files
touch agents/__init__.py
touch agents/scout/__init__.py agents/forge/__init__.py agents/furnace/__init__.py
touch agents/dissect/__init__.py agents/arbiter/__init__.py agents/harbor/__init__.py
touch memory/__init__.py memory/collections/__init__.py
touch training/__init__.py serving/__init__.py
touch bus/__init__.py orchestrator/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py

# Create placeholder files so git tracks empty dirs
touch scripts/.gitkeep outputs/.gitkeep data/.gitkeep
touch research/patch_log.jsonl

# CI/CD scaffolding
mkdir -p .github/workflows
touch .github/workflows/ci.yml
```

**Create `.gitignore`:**
```
__pycache__/
*.pyc
*.pyo
.env
*.egg-info/
dist/
build/
.venv/
venv/
outputs/
data/*.csv
data/*.zip
data/*.parquet
*.ckpt
*.pt
*.onnx
*.pkl
*.log
.DS_Store
node_modules/
```

**Create `pyproject.toml`:**
```toml
[project]
name = "prometheus-swarm"
version = "0.1.0"
requires-python = ">=3.11"
description = "Autonomous multi-agent ML pipeline system"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Create `requirements.txt` — exact pinned versions:**
```
# LLM
anthropic==0.25.0

# ML Training
lightgbm==4.3.0
xgboost==2.0.3
scikit-learn==1.4.2
torch==2.3.0
transformers==4.41.0
optuna==3.6.1
imbalanced-learn==0.12.3
pandas==2.2.2
numpy==1.26.4

# Infrastructure
redis==5.0.4
chromadb==0.5.0
sentence-transformers==3.0.1
fastapi==0.111.0
uvicorn==0.30.0
onnx==1.16.0
onnxruntime==1.18.0
onnxmltools==1.12.0
docker==7.1.0
prometheus-client==0.20.0
filelock==3.15.0
scipy==1.13.0

# Dev + Testing
pytest==8.2.0
pytest-asyncio==0.23.7
python-dotenv==1.0.1
pydantic==2.7.1
httpx==0.27.0
```

**Install:**
```bash
pip install -r requirements.txt
```
This takes 5-10 minutes. Let it run.

**Create `.env.example`:**
```bash
# LLM — Claude Sonnet for all phases
ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
ANTHROPIC_MODEL=claude-sonnet-4-6

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=

# ChromaDB
CHROMA_HOST=localhost
CHROMA_PORT=8000
CHROMA_COLLECTION_PATCH_MEMORY=patch_memory
CHROMA_COLLECTION_ARCH_MEMORY=architecture_memory
CHROMA_COLLECTION_TOOL_MEMORY=tool_memory

# Embedding model — sentence-transformers model for ChromaDB
EMBEDDING_MODEL=all-MiniLM-L6-v2

# Docker
TRAINING_IMAGE_NAME=prometheus-training-base
SERVING_IMAGE_NAME=prometheus-serving
DOCKER_REGISTRY=

# Paths
SCRIPTS_DIR=./scripts
OUTPUTS_DIR=./outputs
DATA_DIR=./data
PATCH_LOG_PATH=./research/patch_log.jsonl

# Serving
SERVING_PORT=8080
PSI_CHECK_INTERVAL_SECONDS=3600
PSI_WINDOW_SIZE=1000
PSI_THRESHOLD=0.2

# Research
BENCHMARK_PROBLEMS_PATH=./research/benchmark/problems.json

# Phase gates
PHASE_0_COMPLETE=false
PHASE_1_COMPLETE=false
PHASE_2_COMPLETE=false
PHASE_3_COMPLETE=false
```

```bash
cp .env.example .env
```

**Create `README.md`:**
```markdown
# Prometheus Swarm

Autonomous multi-agent ML pipeline. You describe the problem. The swarm trains, debugs,
evaluates, and serves a model — without human intervention.

See [CLAUDE.md](./CLAUDE.md) for architecture. See [PLAN.md](./PLAN.md) for build steps.

**Status:** Phase 0 — Infrastructure
```

**Git commit:**
```bash
git add -A
git commit -m "[Infra] Initialize project structure"
```

**Phase 0 Day 1 gate:** `ls agents/` shows 6 directories. `python -c "import redis"` shows no error.

---

### DAY 0-2: Docker Compose + Infrastructure Verification

**Create `docker-compose.yml`:**
```yaml
version: "3.9"

services:
  redis:
    image: redis:7.2-alpine
    container_name: prometheus-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  chromadb:
    image: chromadb/chroma:0.5.0
    container_name: prometheus-chroma
    ports:
      - "8000:8000"
    volumes:
      - chroma_data:/chroma/chroma
    environment:
      - ALLOW_RESET=true
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/heartbeat"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

volumes:
  redis_data:
  chroma_data:
```

**Start infrastructure:**
```bash
docker compose up -d
```

**Verify everything is healthy (run these one by one):**
```bash
# Wait 10 seconds after starting
sleep 10

# Redis check
docker exec prometheus-redis redis-cli ping
# Expected output: PONG

# ChromaDB check
curl http://localhost:8000/api/v1/heartbeat
# Expected output: {"nanosecond heartbeat": <number>}

# Docker status
docker compose ps
# Expected: both services show "Up" and "healthy"
```

If any check fails:
- ChromaDB fail: `docker compose logs chromadb` → read the error

**Git commit:**
```bash
git add docker-compose.yml
git commit -m "[Infra] Add Docker Compose for Redis + ChromaDB"
```

---

### DAY 0-3: LLM Client Abstraction

This is the most important infrastructure piece. All agents call LLM through ONE module.
All agents call Claude Sonnet via the Anthropic API from day one. Zero code changes needed when adding new agents.

**Create `agents/llm_client.py`:**

```python
"""
LLM Client — Anthropic Claude Sonnet interface for all agents.
All agents import get_llm_response from here. Never call Anthropic directly.
"""

import os
import asyncio
import logging
from typing import Any
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


async def get_llm_response(
    system_prompt: str,
    user_message: str,
    tools: list[dict] | None = None,
    job_id: str = "unknown",
    agent_name: str = "unknown",
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Call Claude Sonnet via Anthropic API and return a standardized response dict.

    Returns:
        {
            "text": str,           # The text content of the response
            "tool_calls": list,    # List of tool call dicts (empty if none)
            "input_tokens": int,   # For cost tracking (CLAUDE.md §21.3)
            "output_tokens": int,  # For cost tracking
            "raw": dict            # Full raw response from the backend
        }

    Raises:
        RuntimeError: if all retries fail
    """
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")

    client = anthropic.AsyncAnthropic(api_key=api_key)

    for attempt in range(max_retries):
        try:
            kwargs: dict[str, Any] = {
                "model": ANTHROPIC_MODEL,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_message}],
            }
            if tools:
                kwargs["tools"] = tools

            response = await client.messages.create(**kwargs)

            text = ""
            tool_calls = []

            for block in response.content:
                if block.type == "text":
                    text += block.text
                elif block.type == "tool_use":
                    tool_calls.append({"name": block.name, "arguments": block.input})

            return {
                "text": text,
                "tool_calls": tool_calls,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "raw": response.model_dump(),
            }

        except anthropic.NotFoundError as e:
            raise RuntimeError(
                f"CRITICAL: Model {ANTHROPIC_MODEL} not found. "
                f"Update ANTHROPIC_MODEL in .env to a valid model. Error: {e}"
            ) from e
        except Exception as e:
            wait = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(
                f"[{agent_name}][job={job_id}] LLM call failed attempt {attempt+1}: "
                f"{e}. Retrying in {wait}s."
            )
            if attempt == max_retries - 1:
                raise RuntimeError(
                    f"[{agent_name}][job={job_id}] LLM failed after {max_retries} attempts: {e}"
                ) from e
            await asyncio.sleep(wait)


async def get_embedding(text: str) -> list[float]:
    """
    Get embedding vector for text using sentence-transformers.
    Used for ChromaDB vector storage in patch_memory and architecture_memory.
    Returns a list of floats.
    """
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    return model.encode(text).tolist()
```

**Create `agents/base.py`:**
```python
"""
BaseAgent — common pattern inherited by all six agents.
Provides: LLM calling, Redis I/O, structured logging, retry logic.
"""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

from agents.llm_client import get_llm_response
from memory.redis_client import RedisClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


class BaseAgent(ABC):
    """
    All six agents inherit from this class.
    Subclasses must implement: agent_name, system_prompt, run()
    """

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.redis = RedisClient()
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Return the agent's name: Scout, Forge, Furnace, Dissect, Arbiter, Harbor"""

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the agent's system prompt string."""

    @abstractmethod
    async def run(self) -> None:
        """Main agent loop. Called by the orchestrator."""

    async def call_llm(
        self,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Call LLM through the unified client. Logs the call."""
        self.logger.info(
            f"[job={self.job_id}] LLM call | tools={[t['name'] for t in tools] if tools else []}"
        )
        response = await get_llm_response(
            system_prompt=self.system_prompt,
            user_message=user_message,
            tools=tools,
            job_id=self.job_id,
            agent_name=self.agent_name,
        )
        self.logger.info(
            f"[job={self.job_id}] LLM response | text_len={len(response['text'])} "
            f"tool_calls={[tc['name'] for tc in response['tool_calls']]}"
        )
        return response
```

**Smoke test — verify Claude Sonnet is callable:**
```bash
python3 -c "
import asyncio
from agents.llm_client import get_llm_response

async def test():
    result = await get_llm_response(
        system_prompt='You are a helpful assistant. Reply in JSON only.',
        user_message='Return this JSON: {\"status\": \"ok\", \"message\": \"hello\"}',
        job_id='test-001',
        agent_name='SmokeTest'
    )
    print('Text:', result['text'][:200])
    print('Tool calls:', result['tool_calls'])
    print('SUCCESS')

asyncio.run(test())
"
```
Expected: prints some text and "SUCCESS". If the API call fails, check your ANTHROPIC_API_KEY in .env.

---

### DAY 0-4: Bus Layer + Redis Client

**Create `memory/redis_client.py`:**
```python
"""
Redis client singleton. All agents import this.
Provides: key-value get/set with JSON, Streams publish/consume helpers.
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
    """Singleton async Redis client. Create one per agent instance."""

    def __init__(self):
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Initialize connection. Call this before any other method."""
        self._client = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=os.getenv("REDIS_PASSWORD") or None,
            decode_responses=True,
        )
        # Verify connection
        await self._client.ping()
        logger.info("Redis connected")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def set_json(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store any JSON-serializable value at key."""
        serialized = json.dumps(value)
        if ttl_seconds:
            await self._client.setex(key, ttl_seconds, serialized)
        else:
            await self._client.set(key, serialized)

    async def get_json(self, key: str) -> Any | None:
        """Retrieve and deserialize a JSON value. Returns None if key missing."""
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
        """Append to a Redis list. Used by Dissect for patch_log_queue."""
        await self._client.rpush(list_key, value)

    async def blpop(self, list_key: str, timeout: int = 0) -> str | None:
        """Blocking pop from a Redis list. Used by patch_log_writer."""
        result = await self._client.blpop(list_key, timeout=timeout)
        if result:
            return result[1]  # (key, value) tuple → return value
        return None
```

**Create `bus/events.py`:**
```python
"""
Event type constants. The ONLY place event type strings are defined.
Import from here. Never use raw strings for event types anywhere.
"""

MISSION_BRIEF_READY   = "MISSION_BRIEF_READY"
TRAINING_SCRIPT_READY = "TRAINING_SCRIPT_READY"
EPOCH_COMPLETE        = "EPOCH_COMPLETE"
TRAINING_COMPLETE     = "TRAINING_COMPLETE"
CRASH_EVENT           = "CRASH_EVENT"
RESUME_TRAINING       = "RESUME_TRAINING"
EVALUATION_PASS       = "EVALUATION_PASS"
EVALUATION_RETRY      = "EVALUATION_RETRY"
ESCALATE              = "ESCALATE"
JOB_FAILED            = "JOB_FAILED"
ENDPOINT_LIVE         = "ENDPOINT_LIVE"
DRIFT_ALERT           = "DRIFT_ALERT"

# Stream names — one per producing agent
STREAM_SCOUT_OUTPUT      = "scout_output"
STREAM_FORGE_OUTPUT      = "forge_output"
STREAM_FURNACE_FEED      = "furnace_feed"
STREAM_FURNACE_OUTPUT    = "furnace_output"
STREAM_FURNACE_CRASH     = "furnace_crash"
STREAM_DISSECT_OUTPUT    = "dissect_output"
STREAM_ARBITER_OUTPUT    = "arbiter_output"
STREAM_HARBOR_OUTPUT     = "harbor_output"
STREAM_ORCHESTRATOR_OUT  = "orchestrator_output"

# Consumer group names
GROUP_FORGE       = "forge_consumers"
GROUP_FURNACE     = "furnace_consumers"
GROUP_DISSECT     = "dissect_consumers"
GROUP_ARBITER     = "arbiter_consumers"
GROUP_HARBOR      = "harbor_consumers"
GROUP_FRONTEND    = "frontend_consumers"
GROUP_ORCHESTRATOR = "orchestrator_consumers"
GROUP_SCOUT       = "scout_consumers"
```

**Create `bus/publisher.py`:**
```python
"""
Publisher — sends events to Redis Streams via XADD.
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
    """
    Publish an event to a Redis Stream.

    Args:
        redis_client: Connected aioredis.Redis instance
        stream_name: Which stream to publish to (use constants from bus/events.py)
        event_type: Event type string (use constants from bus/events.py)
        payload: Dict of event data. Will be merged with event_type and timestamp.

    Returns:
        The Redis message ID (e.g., "1716000000000-0")
    """
    full_payload = {
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }

    # Redis Streams require string values — serialize nested dicts
    flat = {k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in full_payload.items()}

    msg_id = await redis_client.xadd(stream_name, flat)
    logger.debug(f"Published {event_type} to {stream_name} [{msg_id}]")
    return msg_id
```

**Create `bus/consumer.py`:**
```python
"""
Consumer — reads events from Redis Streams via XREADGROUP.
Handles consumer group creation, blocking reads, and ACK.
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
    """
    Create a consumer group if it doesn't exist.
    Called by the orchestrator at job start for every stream+group pair.
    """
    try:
        await redis_client.xgroup_create(
            stream_name, group_name, id="0", mkstream=True
        )
        logger.info(f"Created consumer group {group_name} on stream {stream_name}")
    except aioredis.ResponseError as e:
        if "BUSYGROUP" in str(e):
            pass  # Group already exists — not an error
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
    """
    Block-read ONE message from a stream, call handler, then ACK.
    Uses XREADGROUP with BLOCK. block_ms=0 means block forever until a message arrives.

    Args:
        redis_client: Connected aioredis.Redis instance
        stream_name: Stream to read from
        group_name: Consumer group name
        consumer_name: This consumer's name (e.g., "dissect-worker-{job_id}")
        handler: Async function called with the deserialized message dict
        block_ms: How long to block waiting (0 = forever)
    """
    results = await redis_client.xreadgroup(
        groupname=group_name,
        consumername=consumer_name,
        streams={stream_name: ">"},
        count=1,
        block=block_ms,
    )

    if not results:
        return  # Timeout with no message

    stream, messages = results[0]
    for msg_id, raw_fields in messages:
        # Deserialize — JSON fields back to Python objects
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
                f"Handler failed for {msg_id} on {stream_name}/{group_name}: {e}. "
                f"Message NOT ACK'd — will be reclaimed by health monitor."
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
    """
    Continuously consume messages from a stream until stopped.
    If stop_event_types is set, returns after handling any of those event types.

    Use this for agents that process an ongoing stream (e.g., Furnace reading metrics).
    Use consume_one for agents that wait for a single trigger event.
    """
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
```

**Create `memory/schemas.py`:**
```python
"""
Pydantic models for all data structures that cross agent boundaries.
All agents import and use these — never use raw dicts for cross-agent data.
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
import uuid


def new_id() -> str:
    return str(uuid.uuid4())


class DatasetInfo(BaseModel):
    file_path: str
    num_rows: int
    num_columns: int
    column_types: dict[str, str]  # column_name → "numeric|categorical|text|datetime|target"


class DataQuality(BaseModel):
    class_imbalance_ratio: float | None = None
    missing_value_rate: dict[str, float] = {}
    high_cardinality_columns: list[str] = []
    data_warnings: list[str] = []


class Constraints(BaseModel):
    max_latency_ms: int | None = None
    max_model_size_mb: int | None = None


class MissionBrief(BaseModel):
    schema_version: str = "1.0"
    job_id: str = Field(default_factory=new_id)
    problem_description: str
    task_type: str   # classification | regression | detection | generation
    modality: str    # tabular | text | image
    target_column: str | None = None
    evaluation_metric: str | None = None  # auc_roc | f1 | rmse | mae | map
    constraints: Constraints = Field(default_factory=Constraints)
    dataset: DatasetInfo
    data_quality: DataQuality = Field(default_factory=DataQuality)
    imbalance_strategy: str = "none"  # none | class_weight | smote | focal_loss
    recommended_architecture_family: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


class PatchLogEntry(BaseModel):
    patch_id: str = Field(default_factory=new_id)
    job_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    exception_type: str
    exception_message: str
    error_taxonomy_category: str
    taxonomy_match_method: str  # regex | llm_classification
    repair_strategy_used: str
    retrieved_similar_patches: list[dict] = []
    diff_applied: str
    lines_changed: int
    sandbox_test_result: str  # pass | fail
    patch_outcome: str        # success | rollback | escalated
    confidence_score: float
    attempt_number: int
    resume_from_checkpoint: str | None = None


class EvalReport(BaseModel):
    job_id: str
    checkpoint_path: str
    task_type: str
    primary_metric: str
    primary_metric_value: float
    all_metrics: dict[str, float]
    failure_analysis: str
    decision: str  # pass | retry | escalate
    decision_reason: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
```

**Write and run the bus end-to-end test:**

Create `tests/integration/test_bus_e2e.py`:
```python
"""
Tests that all event types can be published and consumed end-to-end through Redis Streams.
Phase 0 gate test.
"""

import asyncio
import json
import pytest
import redis.asyncio as aioredis

from bus.events import (
    MISSION_BRIEF_READY, TRAINING_SCRIPT_READY, EPOCH_COMPLETE,
    TRAINING_COMPLETE, CRASH_EVENT, RESUME_TRAINING,
    EVALUATION_PASS, EVALUATION_RETRY, ESCALATE, ENDPOINT_LIVE, DRIFT_ALERT,
    STREAM_SCOUT_OUTPUT, GROUP_FORGE,
)
from bus.publisher import publish
from bus.consumer import ensure_consumer_group, consume_one


@pytest.fixture
async def redis():
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    yield r
    # Cleanup test streams
    for stream in ["test_stream_e2e"]:
        await r.delete(stream)
    await r.aclose()


@pytest.mark.asyncio
async def test_publish_and_consume_roundtrip(redis):
    """Publish a MISSION_BRIEF_READY event and consume it."""
    stream = "test_stream_e2e"
    group = "test_group"

    await ensure_consumer_group(redis, stream, group)

    # Publish
    payload = {
        "job_id": "test-job-001",
        "mission_brief_redis_key": "job:test-job-001:mission_brief",
    }
    msg_id = await publish(redis, stream, MISSION_BRIEF_READY, payload)
    assert msg_id is not None

    # Consume
    received = {}

    async def handler(message):
        received.update(message)

    await consume_one(redis, stream, group, "test-consumer", handler, block_ms=1000)

    assert received["event_type"] == MISSION_BRIEF_READY
    assert received["job_id"] == "test-job-001"
    assert "timestamp" in received


@pytest.mark.asyncio
async def test_all_event_types_are_publishable(redis):
    """Verify all 11 event type constants can be published without error."""
    stream = "test_stream_all_events"
    await redis.delete(stream)

    events = [
        (MISSION_BRIEF_READY, {"job_id": "j1", "mission_brief_redis_key": "k"}),
        (TRAINING_SCRIPT_READY, {"job_id": "j1", "script_path": "s.py", "search_space_redis_key": "k"}),
        (EPOCH_COMPLETE, {"job_id": "j1", "epoch": 1, "train_loss": 0.5, "val_loss": 0.6, "eta_seconds": 100}),
        (TRAINING_COMPLETE, {"job_id": "j1", "checkpoint_path": "/c", "best_val_metric": 0.9, "total_epochs": 10, "total_crashes_recovered": 0}),
        (CRASH_EVENT, {"job_id": "j1", "exception_type": "ValueError", "exception_message": "test", "traceback": "tb", "script_path": "s.py", "last_checkpoint_path": None, "epoch_at_crash": 2, "crash_attempt_number": 1}),
        (RESUME_TRAINING, {"job_id": "j1", "patched_script_path": "s.py", "resume_from_checkpoint": None, "patch_id": "pid"}),
        (EVALUATION_PASS, {"job_id": "j1", "eval_report_path": "/r", "primary_metric": "auc_roc", "primary_metric_value": 0.91}),
        (EVALUATION_RETRY, {"job_id": "j1", "eval_report_path": "/r", "reason": "below threshold"}),
        (ESCALATE, {"job_id": "j1", "source_agent": "Dissect", "reason": "3 failures", "diagnostic_report_path": "/d"}),
        (ENDPOINT_LIVE, {"job_id": "j1", "endpoint_url": "http://x", "val_metric": 0.9, "p95_latency_ms": 12.0, "model_format": "onnx"}),
        (DRIFT_ALERT, {"job_id": "j1", "psi_score": 0.25, "psi_threshold": 0.2, "window_size": 1000}),
    ]

    for event_type, payload in events:
        msg_id = await publish(redis, stream, event_type, payload)
        assert msg_id is not None, f"Failed to publish {event_type}"

    # Verify 11 messages in stream
    messages = await redis.xrange(stream)
    assert len(messages) == 11

    await redis.delete(stream)
```

**Run the test:**
```bash
pytest tests/integration/test_bus_e2e.py -v
```
Expected: 2 tests pass. If they fail, check that Redis is running: `docker compose ps`

**Git commit:**
```bash
git add -A
git commit -m "[Bus] Implement Redis Streams publisher, consumer, and event taxonomy"
```

---

### DAY 0-5: Patch Log Writer + Phase 0 Gate

**Create `orchestrator/patch_log_writer.py`:**
```python
"""
Patch log writer — single background process that reads from Redis patch_log_queue
and appends to research/patch_log.jsonl. Never write to patch_log.jsonl directly.
This is the ONLY process that writes to patch_log.jsonl.
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
    """
    Main loop: BLPOP from patch_log_queue, write to JSONL file.
    Runs indefinitely. Start this as a background asyncio task in the orchestrator.
    """
    r = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    log_path = Path(PATCH_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"Patch log writer started. Writing to {log_path}")

    while True:
        try:
            result = await r.blpop("patch_log_queue", timeout=5)
            if result is None:
                continue  # Timeout, loop again

            _, raw_entry = result
            entry = json.loads(raw_entry)

            # Write one JSON line — atomic with file lock
            lock_path = str(log_path) + ".lock"
            with FileLock(lock_path):
                with open(log_path, "a") as f:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")

            logger.debug(f"Wrote patch log entry: patch_id={entry.get('patch_id')}")

        except Exception as e:
            logger.error(f"Patch log writer error: {e}")
            await asyncio.sleep(1)
```

**Create `serving/metrics.py`** (all Prometheus metrics per CLAUDE.md Section 9):
```python
"""All Prometheus metrics. The ONLY place metric objects are created."""
from prometheus_client import Counter, Gauge, Histogram

furnace_epochs_total = Counter(
    "prometheus_furnace_epochs_total", "Total training epochs", ["job_id", "model_type"])
furnace_train_loss = Gauge(
    "prometheus_furnace_train_loss", "Current training loss", ["job_id"])
furnace_val_loss = Gauge(
    "prometheus_furnace_val_loss", "Current validation loss", ["job_id"])
furnace_crashes_total = Counter(
    "prometheus_furnace_crashes_total", "Total crashes", ["job_id", "exception_type"])
furnace_training_duration_seconds = Histogram(
    "prometheus_furnace_training_duration_seconds", "Training duration",
    ["job_id", "model_type"], buckets=[60,300,600,1200,1800,3600])
dissect_patches_attempted_total = Counter(
    "prometheus_dissect_patches_attempted_total", "Patch attempts",
    ["error_category", "attempt_number"])
dissect_patches_successful_total = Counter(
    "prometheus_dissect_patches_successful_total", "Successful patches", ["error_category"])
dissect_patches_escalated_total = Counter(
    "prometheus_dissect_patches_escalated_total", "Escalated jobs", [])
dissect_patch_confidence = Histogram(
    "prometheus_dissect_patch_confidence", "Patch confidence",
    ["error_category"], buckets=[.1,.2,.3,.4,.5,.6,.7,.8,.9,1.0])
dissect_patch_duration_seconds = Histogram(
    "prometheus_dissect_patch_duration_seconds", "Time to patch",
    [], buckets=[1,5,10,30,60,120])
arbiter_decisions_total = Counter(
    "prometheus_arbiter_decisions_total", "Evaluation decisions", ["decision"])
arbiter_primary_metric_value = Gauge(
    "prometheus_arbiter_primary_metric_value", "Primary metric", ["job_id", "metric_name"])
harbor_prediction_requests_total = Counter(
    "prometheus_harbor_prediction_requests_total", "Prediction requests",
    ["job_id", "status_code"])
harbor_prediction_latency_seconds = Histogram(
    "prometheus_harbor_prediction_latency_seconds", "Prediction latency",
    ["job_id"], buckets=[.001,.005,.01,.025,.05,.1,.25,.5,1.0])
harbor_psi_score = Gauge(
    "prometheus_harbor_psi_score", "Current PSI score", ["job_id"])
harbor_drift_alerts_total = Counter(
    "prometheus_harbor_drift_alerts_total", "Drift alerts", ["job_id"])
orchestrator_jobs_submitted_total = Counter(
    "prometheus_orchestrator_jobs_submitted_total", "Jobs submitted", [])
orchestrator_jobs_completed_total = Counter(
    "prometheus_orchestrator_jobs_completed_total", "Jobs completed", [])
orchestrator_jobs_failed_total = Counter(
    "prometheus_orchestrator_jobs_failed_total", "Jobs failed", ["source_agent"])
orchestrator_job_e2e_duration_seconds = Histogram(
    "prometheus_orchestrator_job_e2e_duration_seconds", "E2E job duration",
    [], buckets=[60,300,600,900,1200,1800,3600])
```

**Verify Phase 0 gate:**
```bash
# All 3 infrastructure checks using Python (cross-platform, works on Windows/Mac/Linux)
echo "=== Redis ===" && docker exec prometheus-redis redis-cli ping
echo "=== ChromaDB ===" && python3 -c "import urllib.request, json; d=json.loads(urllib.request.urlopen('http://localhost:8000/api/v1/heartbeat').read().decode()); print('OK' if d.get('nanosecond heartbeat') else 'FAIL')"
echo "=== Bus test ===" && pytest tests/integration/test_bus_e2e.py -v --tb=short 2>&1 | tail -5
```

```bash
git add -A
git commit -m "[Phase0] Gate passed — all infrastructure verified"
```

Update `.env`:
```bash
# Change this line in .env:
PHASE_0_COMPLETE=true
```
---

## PHASE 1 — SCOUT + FORGE + FURNACE
**Duration: 6 days | Goal: Titanic CSV → trained LightGBM → val AUC > 0.82, zero human intervention**

---

### DAY 1-1: Scout Prompts + Tools

**Create `agents/scout/prompts.py`:**
```python
SCOUT_SYSTEM_PROMPT = """You are Scout, the Perceiver agent in the Prometheus Swarm system.

Your ONLY job is to analyze a machine learning problem and dataset, then produce a
structured Mission Brief in JSON format.

RULES YOU MUST FOLLOW:
1. You ALWAYS output valid JSON. Never output prose. Never add markdown code fences.
2. When you need to call a tool, output ONLY the tool_call JSON, nothing else.
3. You NEVER guess data types — you always inspect the actual data first.
4. You NEVER invent column names — you only use columns that actually exist.
5. If you cannot determine a field with confidence, set it to null.

OUTPUT FORMAT (after all tool calls complete):
You must output a single JSON object that matches the MissionBrief schema exactly.
All string enum values must be one of the specified options — no others are valid.

task_type options: classification, regression, detection, generation
modality options: tabular, text, image
imbalance_strategy options: none, class_weight, smote, focal_loss
evaluation_metric options: auc_roc, f1, rmse, mae, map, null
recommended_architecture_family options: lightgbm, xgboost, tabnet, distilbert, efficientnet, null
"""
```

**Create `agents/scout/tools.py`:**
```python
"""
Scout tools. Each function is independently unit-testable.
All functions are pure — no side effects except Redis writes (marked explicitly).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


def detect_modality(file_path: str) -> str:
    """
    Detect data modality from file extension and content sampling.
    Returns: "tabular" | "text" | "image"
    """
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext in {".csv", ".parquet", ".tsv", ".xlsx"}:
        return "tabular"
    elif ext in {".txt", ".jsonl", ".json"}:
        return "text"
    elif ext in {".jpg", ".jpeg", ".png", ".zip"}:
        # Zip might be image dataset — check contents
        return "image"
    else:
        # Try to load as CSV as a fallback
        try:
            pd.read_csv(file_path, nrows=5)
            return "tabular"
        except Exception:
            return "tabular"  # Default


def run_eda(file_path: str, target_column: str | None = None) -> dict[str, Any]:
    """
    Run full exploratory data analysis on a CSV/tabular dataset.
    Returns a dict with all fields needed to populate MissionBrief.dataset
    and MissionBrief.data_quality.

    Does NOT write to Redis — returns a plain dict.
    """
    try:
        df = pd.read_csv(file_path)
    except Exception as e:
        return {"error": str(e)}

    num_rows, num_cols = df.shape
    warnings = []

    # Classify columns
    column_types = {}
    for col in df.columns:
        if col == target_column:
            column_types[col] = "target"
        elif pd.api.types.is_numeric_dtype(df[col]):
            column_types[col] = "numeric"
        elif df[col].dtype == object:
            # Check if it looks like text (long strings)
            avg_len = df[col].dropna().astype(str).str.len().mean()
            column_types[col] = "text" if avg_len > 50 else "categorical"
        else:
            column_types[col] = "categorical"

    # Missing value rates
    missing_rate = {col: float(df[col].isna().mean()) for col in df.columns}
    high_missing = [col for col, rate in missing_rate.items() if rate > 0.3]
    if high_missing:
        warnings.append(f"High missing rate (>30%) in columns: {high_missing}")

    # High cardinality
    categorical_cols = [c for c, t in column_types.items() if t == "categorical"]
    high_cardinality = [c for c in categorical_cols if df[c].nunique() > 50]
    if high_cardinality:
        warnings.append(f"High cardinality (>50 unique values) in: {high_cardinality}")

    # Class imbalance (classification only)
    imbalance_ratio = None
    if target_column and target_column in df.columns:
        counts = df[target_column].value_counts()
        if len(counts) == 2:  # Binary classification
            minority = counts.min()
            majority = counts.max()
            imbalance_ratio = float(majority / minority)
            if imbalance_ratio > 5:
                warnings.append(
                    f"Class imbalance: majority/minority ratio = {imbalance_ratio:.1f}"
                )

    return {
        "num_rows": num_rows,
        "num_columns": num_cols,
        "column_types": column_types,
        "missing_value_rate": missing_rate,
        "high_cardinality_columns": high_cardinality,
        "class_imbalance_ratio": imbalance_ratio,
        "data_warnings": warnings,
    }


def infer_task_type(
    target_column: str | None,
    column_types: dict[str, str],
    file_path: str,
) -> str:
    """
    Infer task type from target column statistics.
    Returns: "classification" | "regression"
    """
    if target_column is None:
        return "classification"  # Default

    try:
        df = pd.read_csv(file_path)
        if target_column not in df.columns:
            return "classification"
        target = df[target_column].dropna()
        n_unique = target.nunique()
        if pd.api.types.is_numeric_dtype(target) and n_unique > 20:
            return "regression"
        return "classification"
    except Exception:
        return "classification"


def select_evaluation_metric(task_type: str, imbalance_ratio: float | None) -> str:
    """
    Select the best evaluation metric for the task.
    Returns metric name string.
    """
    if task_type == "regression":
        return "rmse"
    elif task_type == "classification":
        if imbalance_ratio and imbalance_ratio > 5:
            return "auc_roc"  # Better for imbalanced
        return "auc_roc"
    return "auc_roc"


def select_imbalance_strategy(imbalance_ratio: float | None) -> str:
    """
    Select imbalance handling strategy based on ratio.
    Returns strategy string per CLAUDE.md Section 11.
    """
    if imbalance_ratio is None:
        return "none"
    if imbalance_ratio > 20:
        return "smote"
    elif imbalance_ratio > 5:
        return "class_weight"
    return "none"


def select_architecture_family(
    modality: str,
    task_type: str,
    num_rows: int,
) -> str:
    """
    Select architecture family per CLAUDE.md Section 11 decision tree.
    Returns architecture family string.
    """
    if modality == "tabular":
        if num_rows >= 1_000_000:
            return "tabnet"
        return "lightgbm"
    elif modality == "text":
        return "distilbert"
    elif modality == "image":
        return "efficientnet"
    return "lightgbm"


# Tool schema for LLM function calling
SCOUT_TOOLS = [
    {
        "name": "run_eda",
        "description": "Run exploratory data analysis on a dataset file. Call this first.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to the dataset file"},
                "target_column": {"type": "string", "description": "Name of the target/label column, or null"},
            },
            "required": ["file_path"],
        },
    },
]
```

**Create `agents/scout/agent.py`:**
```python
"""
Scout agent — The Perceiver.
Input: problem description + file path + constraints
Output: MissionBrief written to Redis + MISSION_BRIEF_READY event published
"""

import json
import logging
import os

from agents.base import BaseAgent
from agents.scout.prompts import SCOUT_SYSTEM_PROMPT
from agents.scout.tools import (
    detect_modality, run_eda, infer_task_type,
    select_evaluation_metric, select_imbalance_strategy,
    select_architecture_family, SCOUT_TOOLS,
)
from bus.events import MISSION_BRIEF_READY, STREAM_SCOUT_OUTPUT
from bus.publisher import publish
from memory.schemas import MissionBrief, DatasetInfo, DataQuality, Constraints
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class ScoutAgent(BaseAgent):

    def __init__(
        self,
        job_id: str,
        redis_client: aioredis.Redis,
        problem_description: str,
        file_path: str,
        target_column: str | None = None,
        max_latency_ms: int | None = None,
    ):
        super().__init__(job_id)
        self._redis = redis_client
        self.problem_description = problem_description
        self.file_path = os.path.abspath(file_path)
        self.target_column = target_column
        self.max_latency_ms = max_latency_ms

    @property
    def agent_name(self) -> str:
        return "Scout"

    @property
    def system_prompt(self) -> str:
        return SCOUT_SYSTEM_PROMPT

    async def run(self) -> MissionBrief:
        """
        Full Scout execution:
        1. Detect modality
        2. Run EDA
        3. Infer task type
        4. Select metric + imbalance strategy + architecture family
        5. Build MissionBrief
        6. Write to Redis
        7. Publish MISSION_BRIEF_READY
        """
        logger.info(f"[Scout][job={self.job_id}] Starting")

        # Step 1: Detect modality (deterministic — no LLM needed)
        modality = detect_modality(self.file_path)

        # Step 2: Run EDA (deterministic — pandas analysis)
        eda = run_eda(self.file_path, self.target_column)
        if "error" in eda:
            raise RuntimeError(f"Scout EDA failed: {eda['error']}")

        # Step 3: Use LLM to extract task_type from problem description
        # (deterministic fallback also available)
        task_type = infer_task_type(
            self.target_column, eda["column_types"], self.file_path
        )

        # Optionally ask LLM to refine task_type from problem description
        llm_response = await self.call_llm(
            user_message=f"""
Problem description: {self.problem_description}
Detected modality: {modality}
Target column: {self.target_column}
Number of unique target values: {eda.get('column_types', {}).get(self.target_column, 'unknown')}

Based on the problem description, confirm or correct:
- task_type: Is this classification or regression?
- Any special constraints mentioned in the problem?

Reply with JSON only: {{"task_type": "classification|regression", "notes": "..."}}
""",
        )

        # Parse LLM refinement (best effort — fall back to deterministic if LLM fails)
        try:
            llm_data = json.loads(llm_response["text"])
            task_type = llm_data.get("task_type", task_type)
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"[Scout][job={self.job_id}] LLM refinement parse failed, using deterministic task_type={task_type}")

        # Step 4: Derived decisions
        imbalance_ratio = eda.get("class_imbalance_ratio")
        metric = select_evaluation_metric(task_type, imbalance_ratio)
        imbalance_strategy = select_imbalance_strategy(imbalance_ratio)
        arch_family = select_architecture_family(modality, task_type, eda["num_rows"])

        # Step 5: Build MissionBrief
        brief = MissionBrief(
            job_id=self.job_id,
            problem_description=self.problem_description,
            task_type=task_type,
            modality=modality,
            target_column=self.target_column,
            evaluation_metric=metric,
            constraints=Constraints(max_latency_ms=self.max_latency_ms),
            dataset=DatasetInfo(
                file_path=self.file_path,
                num_rows=eda["num_rows"],
                num_columns=eda["num_columns"],
                column_types=eda["column_types"],
            ),
            data_quality=DataQuality(
                class_imbalance_ratio=imbalance_ratio,
                missing_value_rate=eda["missing_value_rate"],
                high_cardinality_columns=eda["high_cardinality_columns"],
                data_warnings=eda["data_warnings"],
            ),
            imbalance_strategy=imbalance_strategy,
            recommended_architecture_family=arch_family,
        )

        # Step 6: Write to Redis (TTL = 24 hours)
        redis_key = f"job:{self.job_id}:mission_brief"
        await self._redis.set(
            redis_key,
            brief.model_dump_json(),
            ex=86400,
        )
        logger.info(f"[Scout][job={self.job_id}] MissionBrief written to {redis_key}")

        # Step 7: Publish event
        await publish(
            self._redis,
            STREAM_SCOUT_OUTPUT,
            MISSION_BRIEF_READY,
            {
                "job_id": self.job_id,
                "mission_brief_redis_key": redis_key,
            },
        )
        logger.info(f"[Scout][job={self.job_id}] Published MISSION_BRIEF_READY")
        return brief
```

**Create `tests/unit/test_scout_tools.py`:**
```python
"""Unit tests for Scout tools. No Redis, no LLM — pure function tests."""
import pytest
import pandas as pd
import tempfile
import os

from agents.scout.tools import (
    detect_modality, run_eda, infer_task_type,
    select_evaluation_metric, select_imbalance_strategy, select_architecture_family,
)


def make_csv(data: dict, tmp_path) -> str:
    """Helper: write a dict of lists to a temp CSV and return its path."""
    path = os.path.join(tmp_path, "test.csv")
    pd.DataFrame(data).to_csv(path, index=False)
    return path


@pytest.fixture
def tmp_path(tmp_path_factory):
    return str(tmp_path_factory.mktemp("data"))


def test_detect_modality_csv(tmp_path):
    path = make_csv({"a": [1, 2], "b": [3, 4]}, tmp_path)
    assert detect_modality(path) == "tabular"


def test_run_eda_basic(tmp_path):
    path = make_csv({"age": [25, 30, 35], "income": [50000, 60000, 70000], "churned": [0, 1, 0]}, tmp_path)
    result = run_eda(path, target_column="churned")
    assert result["num_rows"] == 3
    assert result["num_columns"] == 3
    assert result["column_types"]["churned"] == "target"
    assert result["column_types"]["age"] == "numeric"


def test_run_eda_detects_imbalance(tmp_path):
    # 10 class 0, 1 class 1 → ratio 10:1
    data = {"label": [0]*10 + [1]*1, "feature": range(11)}
    path = make_csv(data, tmp_path)
    result = run_eda(path, target_column="label")
    assert result["class_imbalance_ratio"] == pytest.approx(10.0)


def test_run_eda_detects_missing(tmp_path):
    import numpy as np
    data = {"a": [1, None, None, None, 5], "b": [1, 2, 3, 4, 5]}
    path = make_csv(data, tmp_path)
    result = run_eda(path)
    assert result["missing_value_rate"]["a"] == pytest.approx(0.6)


def test_select_imbalance_strategy():
    assert select_imbalance_strategy(None) == "none"
    assert select_imbalance_strategy(3.0) == "none"
    assert select_imbalance_strategy(10.0) == "class_weight"
    assert select_imbalance_strategy(25.0) == "smote"


def test_select_architecture_family():
    assert select_architecture_family("tabular", "classification", 100_000) == "lightgbm"
    assert select_architecture_family("tabular", "classification", 2_000_000) == "tabnet"
    assert select_architecture_family("text", "classification", 50_000) == "distilbert"
    assert select_architecture_family("image", "classification", 10_000) == "efficientnet"


def test_select_evaluation_metric():
    assert select_evaluation_metric("regression", None) == "rmse"
    assert select_evaluation_metric("classification", 15.0) == "auc_roc"
```

```bash
pytest tests/unit/test_scout_tools.py -v
```
Expected: all 6 tests pass.

---

### DAY 1-2 to 1-3: Forge — Architecture Selection + Script Generation

**Create `agents/forge/decision_tree.py`:**
```python
"""
Architecture decision tree. Pure Python — no LLM, no I/O.
Implements CLAUDE.md Section 11 exactly.
"""

from dataclasses import dataclass


@dataclass
class ForgeDecision:
    architecture: str    # lightgbm | xgboost | tabnet | distilbert | efficientnet
    imbalance_strategy: str  # none | class_weight | smote | focal_loss
    optuna_trials: int   # How many HPO trials to run
    early_stopping_rounds: int


def select(
    modality: str,
    task_type: str,
    num_rows: int,
    class_imbalance_ratio: float | None,
) -> ForgeDecision:
    """
    Select architecture and training strategy.
    Implements CLAUDE.md Section 11 exactly. Do not add heuristics outside this function.
    """
    if modality == "tabular":
        if num_rows >= 1_000_000:
            arch = "tabnet"
            trials = 20
        else:
            arch = "lightgbm"
            trials = 30

        if class_imbalance_ratio is not None:
            if class_imbalance_ratio > 20:
                strategy = "smote"
            elif class_imbalance_ratio > 5:
                strategy = "class_weight"
            else:
                strategy = "none"
        else:
            strategy = "none"

    elif modality == "text":
        arch = "distilbert"
        strategy = "none"
        trials = 10

    elif modality == "image":
        arch = "efficientnet"
        strategy = "none"
        trials = 10

    else:
        # Unknown modality — default to LightGBM
        arch = "lightgbm"
        strategy = "none"
        trials = 20

    return ForgeDecision(
        architecture=arch,
        imbalance_strategy=strategy,
        optuna_trials=trials,
        early_stopping_rounds=50,
    )
```

**Create `agents/forge/tools.py`:**
```python
"""
Forge tools: reads mission brief, writes training script using LLM.
The LLM writes Python code. Forge validates it is syntactically correct before saving.
"""

import ast
import json
import logging
import os
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

SCRIPTS_DIR = os.getenv("SCRIPTS_DIR", "./scripts")


def validate_python(code: str) -> tuple[bool, str]:
    """
    Check if a string is valid Python syntax.
    Returns (is_valid, error_message).
    """
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, str(e)


def write_script(job_id: str, code: str) -> str:
    """
    Write training script to scripts/ directory.
    Returns absolute path to the saved script.
    Raises ValueError if code has syntax errors.
    """
    is_valid, error = validate_python(code)
    if not is_valid:
        raise ValueError(f"Forge generated invalid Python: {error}")

    Path(SCRIPTS_DIR).mkdir(parents=True, exist_ok=True)
    path = os.path.abspath(os.path.join(SCRIPTS_DIR, f"training_script_{job_id}.py"))

    with open(path, "w") as f:
        f.write(code)

    logger.info(f"Training script saved to {path}")
    return path


def build_forge_prompt(mission_brief: dict, decision) -> str:
    """
    Build the user message for Forge's LLM call.
    Includes the mission brief and decision, asks for a complete training script.
    """
    return f"""
Write a complete, self-contained Python training script for this ML problem.

MISSION BRIEF:
{json.dumps(mission_brief, indent=2)}

ARCHITECTURE DECISION:
- Architecture: {decision.architecture}
- Imbalance strategy: {decision.imbalance_strategy}
- Optuna trials: {decision.optuna_trials}
- Early stopping rounds: {decision.early_stopping_rounds}

REQUIREMENTS FOR THE SCRIPT:
1. The script must be completely self-contained — no imports outside standard library + installed packages
2. It must load data from the file path in the mission brief
3. It must use Optuna for hyperparameter search with the number of trials specified
4. It must save the best model checkpoint to: outputs/{{JOB_ID}}/checkpoints/best.ckpt
   where {{JOB_ID}} is read from the environment variable JOB_ID
5. After each epoch or Optuna trial, print a JSON line to stdout:
   {{"type": "epoch_complete", "epoch": <n>, "train_loss": <f>, "val_loss": <f>}}
6. If any exception occurs, print to stderr as JSON:
   {{"type": "crash", "exception_type": "<ExceptionClassName>", "message": "<str>", "traceback": "<str>"}}
7. At the end, print to stdout:
   {{"type": "training_complete", "best_val_metric": <f>, "total_epochs": <n>, "checkpoint_path": "<path>"}}
8. Apply the imbalance strategy specified
9. Use the evaluation metric from the mission brief

IMPORTANT: Output ONLY the Python code. No explanations. No markdown. No comments explaining the rules.
Start with: import ...
"""
```

**Create `agents/forge/agent.py`:**
```python
"""Forge agent — The Architect. Subscribes to MISSION_BRIEF_READY → writes training script."""

import json
import logging
import os

import redis.asyncio as aioredis

from agents.base import BaseAgent
from agents.forge.decision_tree import select as select_architecture
from agents.forge.tools import write_script, build_forge_prompt
from bus.events import (
    MISSION_BRIEF_READY, TRAINING_SCRIPT_READY,
    STREAM_SCOUT_OUTPUT, STREAM_FORGE_OUTPUT, GROUP_FORGE,
)
from bus.consumer import ensure_consumer_group, consume_one
from bus.publisher import publish
from memory.schemas import MissionBrief

logger = logging.getLogger(__name__)


FORGE_SYSTEM_PROMPT = """You are Forge, the Architect agent in the Prometheus Swarm system.

Your ONLY job is to write a complete, runnable Python training script.
Output ONLY valid Python code. No markdown. No explanations. No code fences.
The first character of your response must be 'i' (from 'import').
Every line must be valid Python.
"""


class ForgeAgent(BaseAgent):

    def __init__(self, job_id: str, redis_client: aioredis.Redis):
        super().__init__(job_id)
        self._redis = redis_client

    @property
    def agent_name(self) -> str:
        return "Forge"

    @property
    def system_prompt(self) -> str:
        return FORGE_SYSTEM_PROMPT

    async def run(self) -> str:
        """
        Wait for MISSION_BRIEF_READY → read brief → select architecture →
        generate script → validate → save → publish TRAINING_SCRIPT_READY.
        Returns path to saved script.
        """
        logger.info(f"[Forge][job={self.job_id}] Waiting for MISSION_BRIEF_READY")

        # Read mission brief from Redis (already written by Scout)
        brief_key = f"job:{self.job_id}:mission_brief"
        brief_raw = await self._redis.get(brief_key)
        if not brief_raw:
            raise RuntimeError(f"Mission brief not found at key {brief_key}")

        brief_data = json.loads(brief_raw)
        brief = MissionBrief(**brief_data)

        # Select architecture (deterministic)
        decision = select_architecture(
            modality=brief.modality,
            task_type=brief.task_type,
            num_rows=brief.dataset.num_rows,
            class_imbalance_ratio=brief.data_quality.class_imbalance_ratio,
        )
        logger.info(
            f"[Forge][job={self.job_id}] Decision: arch={decision.architecture} "
            f"strategy={decision.imbalance_strategy}"
        )

        # Generate training script via LLM
        prompt = build_forge_prompt(brief_data, decision)
        response = await self.call_llm(user_message=prompt)
        code = response["text"].strip()

        # Remove accidental markdown fences if LLM added them
        if code.startswith("```python"):
            code = code[9:]
        if code.startswith("```"):
            code = code[3:]
        if code.endswith("```"):
            code = code[:-3]
        code = code.strip()

        # Save script (validates syntax)
        script_path = write_script(self.job_id, code)

        # Write search space to Redis
        search_space = {
            "architecture": decision.architecture,
            "optuna_trials": decision.optuna_trials,
            "early_stopping_rounds": decision.early_stopping_rounds,
            "imbalance_strategy": decision.imbalance_strategy,
        }
        await self._redis.set(
            f"job:{self.job_id}:search_space",
            json.dumps(search_space),
            ex=86400,
        )

        # Publish event
        await publish(
            self._redis,
            STREAM_FORGE_OUTPUT,
            TRAINING_SCRIPT_READY,
            {
                "job_id": self.job_id,
                "script_path": script_path,
                "search_space_redis_key": f"job:{self.job_id}:search_space",
            },
        )
        logger.info(f"[Forge][job={self.job_id}] Published TRAINING_SCRIPT_READY → {script_path}")
        return script_path
```

---

### DAY 1-4 to 1-5: Furnace — Docker Training + Metrics Streaming

**Create `training/base_training_image/Dockerfile`:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install ML dependencies inside the container
RUN pip install --no-cache-dir \
    lightgbm==4.3.0 \
    xgboost==2.0.3 \
    scikit-learn==1.4.2 \
    torch==2.3.0 \
    transformers==4.41.0 \
    optuna==3.6.1 \
    imbalanced-learn==0.12.3 \
    pandas==2.2.2 \
    numpy==1.26.4 \
    onnx==1.16.0 \
    onnxruntime==1.18.0

# Scripts and data are mounted at runtime via volumes:
# /app/script.py   ← training script written by Forge
# /app/data/       ← dataset files
# /app/outputs/    ← model checkpoints written here

CMD ["python", "/app/script.py"]
```

**Build the image:**
```bash
docker build -t prometheus-training-base training/base_training_image/
```
This takes 15-25 minutes. Wait for it.

**Create `training/docker_manager.py`:**
```python
"""
Docker container lifecycle for training jobs.
Furnace uses this to launch, monitor, and kill training containers.
"""

import asyncio
import json
import logging
import os
from pathlib import Path

import docker
from docker.errors import DockerException

logger = logging.getLogger(__name__)

TRAINING_IMAGE = os.getenv("TRAINING_IMAGE_NAME", "prometheus-training-base")
OUTPUTS_DIR = os.path.abspath(os.getenv("OUTPUTS_DIR", "./outputs"))
DATA_DIR = os.path.abspath(os.getenv("DATA_DIR", "./data"))
SCRIPTS_DIR = os.path.abspath(os.getenv("SCRIPTS_DIR", "./scripts"))


class DockerTrainingManager:
    """Manages the lifecycle of a single training container per job."""

    def __init__(self, job_id: str):
        self.job_id = job_id
        self.client = docker.from_env()
        self.container = None
        self.checkpoint_dir = os.path.join(OUTPUTS_DIR, job_id, "checkpoints")
        Path(self.checkpoint_dir).mkdir(parents=True, exist_ok=True)

    def launch(self, script_path: str) -> None:
        """
        Launch the training container. Mounts script, data, and outputs directories.
        Container name: prometheus-train-{job_id}
        """
        container_name = f"prometheus-train-{self.job_id}"

        # Kill any existing container with this name
        try:
            existing = self.client.containers.get(container_name)
            existing.remove(force=True)
        except docker.errors.NotFound:
            pass

        volumes = {
            os.path.abspath(script_path): {"bind": "/app/script.py", "mode": "ro"},
            os.path.abspath(DATA_DIR): {"bind": "/app/data", "mode": "ro"},
            os.path.abspath(os.path.join(OUTPUTS_DIR, self.job_id)): {
                "bind": "/app/outputs",
                "mode": "rw",
            },
        }

        environment = {
            "JOB_ID": self.job_id,
            "PYTHONUNBUFFERED": "1",  # Ensures stdout/stderr are not buffered
        }

        # GPU support if available
        device_requests = []
        try:
            gpu_info = self.client.info().get("Runtimes", {})
            if "nvidia" in gpu_info:
                device_requests = [
                    docker.types.DeviceRequest(count=-1, capabilities=[["gpu"]])
                ]
        except Exception:
            pass  # No GPU available — use CPU

        self.container = self.client.containers.run(
            image=TRAINING_IMAGE,
            name=container_name,
            volumes=volumes,
            environment=environment,
            device_requests=device_requests,
            detach=True,
            stdout=True,
            stderr=True,
        )
        logger.info(f"[DockerManager][job={self.job_id}] Container started: {container_name}")

    def stream_output(self):
        """
        Generator that yields parsed output lines from the container.
        Each line is either a metrics dict (from stdout) or an error dict (from stderr).
        Blocks until container exits.
        """
        if self.container is None:
            raise RuntimeError("Container not launched. Call launch() first.")

        for line in self.container.logs(stream=True, follow=True):
            decoded = line.decode("utf-8").strip()
            if not decoded:
                continue
            try:
                parsed = json.loads(decoded)
                yield parsed
            except json.JSONDecodeError:
                # Non-JSON output — log it but don't crash
                logger.debug(f"[job={self.job_id}] Container non-JSON output: {decoded}")

    def get_exit_code(self) -> int:
        """Return container exit code. Call after stream_output() is exhausted."""
        if self.container is None:
            return -1
        self.container.reload()
        return self.container.attrs["State"]["ExitCode"]

    def kill(self) -> None:
        """Kill and remove the training container. Safe to call multiple times."""
        if self.container:
            try:
                self.container.remove(force=True)
                logger.info(f"[DockerManager][job={self.job_id}] Container killed and removed")
            except Exception as e:
                logger.warning(f"[DockerManager][job={self.job_id}] Kill failed: {e}")
            self.container = None
```

**Create `training/checkpoint_manager.py`:**
```python
"""Checkpoint save/restore/integrity-check for training jobs."""

import json
import logging
import os
import pickle
from pathlib import Path

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Manages model checkpoints for a single job."""

    def __init__(self, job_id: str, outputs_dir: str = "./outputs"):
        self.job_id = job_id
        self.checkpoint_dir = Path(outputs_dir) / job_id / "checkpoints"
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def checkpoint_path(self, epoch: int | None = None) -> str:
        """Return path for a checkpoint. If epoch is None, return best.ckpt path."""
        if epoch is None:
            return str(self.checkpoint_dir / "best.ckpt")
        return str(self.checkpoint_dir / f"epoch_{epoch:04d}.ckpt")

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def is_valid(self, path: str) -> bool:
        """Check if a checkpoint file is valid (not corrupted)."""
        if not self.exists(path):
            return False
        try:
            with open(path, "rb") as f:
                pickle.load(f)
            return True
        except Exception:
            return False

    def delete(self, path: str) -> None:
        """Delete a checkpoint file if it exists."""
        try:
            Path(path).unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Failed to delete checkpoint {path}: {e}")
```

**Create `agents/furnace/agent.py`:**
```python
"""
Furnace agent — The Trainer.
Launches training container, streams metrics, publishes events, handles crashes.
On CRASH: saves checkpoint, publishes CRASH_EVENT, enters WAIT state.
On RESUME_TRAINING: reloads patched script, resumes from checkpoint.
"""

import asyncio
import json
import logging
import os
import traceback
import uuid

import redis.asyncio as aioredis

from agents.base import BaseAgent
from bus.events import (
    EPOCH_COMPLETE, TRAINING_COMPLETE, CRASH_EVENT, RESUME_TRAINING, ESCALATE,
    STREAM_FURNACE_FEED, STREAM_FURNACE_OUTPUT, STREAM_FURNACE_CRASH,
    STREAM_DISSECT_OUTPUT, GROUP_FURNACE,
)
from bus.publisher import publish
from bus.consumer import ensure_consumer_group
from training.docker_manager import DockerTrainingManager
from training.checkpoint_manager import CheckpointManager
from serving.metrics import (
    furnace_epochs_total, furnace_train_loss, furnace_val_loss,
    furnace_crashes_total, furnace_training_duration_seconds,
)
import time

logger = logging.getLogger(__name__)

FURNACE_SYSTEM_PROMPT = "You are Furnace, the Trainer agent. You do not generate code."


class FurnaceAgent(BaseAgent):

    def __init__(self, job_id: str, redis_client: aioredis.Redis):
        super().__init__(job_id)
        self._redis = redis_client
        self.docker = DockerTrainingManager(job_id)
        self.checkpoints = CheckpointManager(job_id)
        self.crash_count = 0

    @property
    def agent_name(self) -> str:
        return "Furnace"

    @property
    def system_prompt(self) -> str:
        return FURNACE_SYSTEM_PROMPT

    async def run(self, script_path: str) -> dict:
        """
        Full training run with crash recovery loop.
        Returns dict with checkpoint_path, best_val_metric, total_epochs.
        """
        logger.info(f"[Furnace][job={self.job_id}] Starting training: {script_path}")
        start_time = time.time()
        total_epochs = 0
        best_val_metric = 0.0
        current_script = script_path
        last_checkpoint = None

        while True:
            result = await self._run_training_container(current_script, last_checkpoint)

            if result["status"] == "complete":
                total_epochs += result["epochs"]
                best_val_metric = result["best_val_metric"]
                last_checkpoint = result["checkpoint_path"]

                # Publish TRAINING_COMPLETE
                await publish(
                    self._redis, STREAM_FURNACE_OUTPUT, TRAINING_COMPLETE,
                    {
                        "job_id": self.job_id,
                        "checkpoint_path": last_checkpoint,
                        "best_val_metric": best_val_metric,
                        "total_epochs": total_epochs,
                        "total_crashes_recovered": self.crash_count,
                    }
                )

                duration = time.time() - start_time
                arch = "lightgbm"  # TODO: read from search_space
                furnace_training_duration_seconds.labels(
                    job_id=self.job_id, model_type=arch
                ).observe(duration)

                logger.info(f"[Furnace][job={self.job_id}] Training complete. AUC={best_val_metric:.4f}")
                return {
                    "checkpoint_path": last_checkpoint,
                    "best_val_metric": best_val_metric,
                    "total_epochs": total_epochs,
                }

            elif result["status"] == "crashed":
                self.crash_count += 1
                total_epochs += result.get("epochs_before_crash", 0)
                last_checkpoint = result.get("last_checkpoint")

                # Update crash count in Redis
                await self._redis.set(f"job:{self.job_id}:crash_count", str(self.crash_count))

                furnace_crashes_total.labels(
                    job_id=self.job_id,
                    exception_type=result["exception_type"],
                ).inc()

                # Publish CRASH_EVENT
                await publish(
                    self._redis, STREAM_FURNACE_CRASH, CRASH_EVENT,
                    {
                        "job_id": self.job_id,
                        "exception_type": result["exception_type"],
                        "exception_message": result["exception_message"],
                        "traceback": result["traceback"],
                        "script_path": current_script,
                        "last_checkpoint_path": last_checkpoint,
                        "epoch_at_crash": total_epochs,
                        "crash_attempt_number": self.crash_count,
                    }
                )

                logger.info(
                    f"[Furnace][job={self.job_id}] CRASH #{self.crash_count}. "
                    f"Entering WAIT state for Dissect."
                )

                # WAIT state — block until RESUME_TRAINING or ESCALATE
                resume = await self._wait_for_resume()

                if resume is None:
                    logger.info(f"[Furnace][job={self.job_id}] ESCALATE received. Killing container.")
                    self.docker.kill()
                    return {"status": "escalated"}

                current_script = resume["patched_script_path"]
                last_checkpoint = resume.get("resume_from_checkpoint")
                logger.info(
                    f"[Furnace][job={self.job_id}] Resuming with patched script: {current_script}"
                )

    async def _run_training_container(self, script_path: str, resume_checkpoint: str | None) -> dict:
        """
        Launch container and stream output until completion or crash.
        Returns dict with status, epochs, metrics, crash info.
        """
        # Pass resume checkpoint via environment variable written to a temp file
        # The training script checks for RESUME_CHECKPOINT env var
        environment_override = {}
        if resume_checkpoint:
            environment_override["RESUME_CHECKPOINT"] = resume_checkpoint

        self.docker.launch(script_path)

        epochs = 0
        best_val = 0.0
        last_checkpoint = None
        crash_info = None

        try:
            for output in self.docker.stream_output():
                output_type = output.get("type", "")

                if output_type == "epoch_complete":
                    epochs += 1
                    train_loss = float(output.get("train_loss", 0))
                    val_loss = float(output.get("val_loss", 0))

                    furnace_epochs_total.labels(
                        job_id=self.job_id, model_type="lightgbm"
                    ).inc()
                    furnace_train_loss.labels(job_id=self.job_id).set(train_loss)
                    furnace_val_loss.labels(job_id=self.job_id).set(val_loss)

                    # Publish epoch event for frontend
                    await publish(
                        self._redis, STREAM_FURNACE_FEED, EPOCH_COMPLETE,
                        {
                            "job_id": self.job_id,
                            "epoch": epochs,
                            "train_loss": train_loss,
                            "val_loss": val_loss,
                            "eta_seconds": output.get("eta_seconds", 0),
                        }
                    )

                elif output_type == "training_complete":
                    best_val = float(output.get("best_val_metric", 0))
                    last_checkpoint = output.get("checkpoint_path")

                elif output_type == "crash":
                    crash_info = output

        except Exception as e:
            logger.error(f"[Furnace][job={self.job_id}] Stream reading error: {e}")
            crash_info = {
                "exception_type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc(),
            }

        exit_code = self.docker.get_exit_code()

        if exit_code == 0 and crash_info is None:
            return {
                "status": "complete",
                "epochs": epochs,
                "best_val_metric": best_val,
                "checkpoint_path": last_checkpoint,
            }
        else:
            return {
                "status": "crashed",
                "epochs_before_crash": epochs,
                "last_checkpoint": last_checkpoint,
                "exception_type": crash_info.get("exception_type", "UnknownError") if crash_info else "ExitCodeError",
                "exception_message": crash_info.get("message", f"Exit code {exit_code}") if crash_info else f"Exit code {exit_code}",
                "traceback": crash_info.get("traceback", "") if crash_info else "",
            }

    async def _wait_for_resume(self) -> dict | None:
        """
        Block in WAIT state, reading from dissect_output stream.
        Returns RESUME_TRAINING payload or None if ESCALATE received.
        Times out after 10 minutes — returns None on timeout (treated as escalate).
        """
        await ensure_consumer_group(self._redis, STREAM_DISSECT_OUTPUT, GROUP_FURNACE)
        consumer_name = f"furnace-{self.job_id}"

        # Block for up to 10 minutes (600,000ms)
        results = await self._redis.xreadgroup(
            groupname=GROUP_FURNACE,
            consumername=consumer_name,
            streams={STREAM_DISSECT_OUTPUT: ">"},
            count=1,
            block=600_000,
        )

        if not results:
            logger.warning(f"[Furnace][job={self.job_id}] WAIT timed out after 10 min")
            return None

        _, messages = results[0]
        for msg_id, raw_fields in messages:
            message = {}
            for k, v in raw_fields.items():
                try:
                    import json as _json
                    message[k] = _json.loads(v)
                except Exception:
                    message[k] = v

            await self._redis.xack(STREAM_DISSECT_OUTPUT, GROUP_FURNACE, msg_id)

            if message.get("event_type") == RESUME_TRAINING:
                return message
            elif message.get("event_type") == ESCALATE:
                return None

        return None
```

---

### DAY 1-6: Orchestrator v1 + Phase 1 Gate Test

**Create `orchestrator/runtime.py`:**
```python
"""
Orchestrator v1 — sequential Scout → Forge → Furnace pipeline.
Phase 1 version: no Dissect, no Arbiter, no Harbor.
"""

import asyncio
import logging
import os
import uuid
from pathlib import Path

import redis.asyncio as aioredis
from dotenv import load_dotenv

from agents.scout.agent import ScoutAgent
from agents.forge.agent import ForgeAgent
from agents.furnace.agent import FurnaceAgent
from orchestrator.patch_log_writer import run_writer
from prometheus_client import start_http_server

load_dotenv()
logger = logging.getLogger(__name__)


class Orchestrator:
    """Manages a single job through the full pipeline."""

    def __init__(self, use_dissect: bool = True):
        self._redis: aioredis.Redis | None = None
        self.use_dissect = use_dissect

    async def connect(self) -> None:
        self._redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            decode_responses=True,
        )
        try:
            start_http_server(9090)
            logger.info("Prometheus metrics server started on port 9090")
        except OSError:
            logger.warning("Port 9090 already in use, assuming metrics server is already running.")
        await self._redis.ping()
        logger.info("Orchestrator connected to Redis")

    async def submit_job(
        self,
        problem_description: str,
        file_path: str,
        target_column: str | None = None,
    ) -> str:
        """Submit a job and return its job_id."""
        job_id = str(uuid.uuid4())
        await self._redis.set(f"job:{job_id}:status", "SUBMITTED")
        logger.info(f"Job submitted: {job_id}")
        return job_id

    async def run_job(
        self,
        job_id: str,
        problem_description: str,
        file_path: str,
        target_column: str | None = None,
    ) -> dict:
        """
        Run a full job sequentially: Scout → Forge → Furnace.
        Returns the final result dict.
        """
        await self._redis.set(f"job:{job_id}:status", "RUNNING")

        # Phase 1: Scout
        await self._redis.set(f"job:{job_id}:status", "SCOUT_RUNNING")
        scout = ScoutAgent(
            job_id=job_id,
            redis_client=self._redis,
            problem_description=problem_description,
            file_path=file_path,
            target_column=target_column,
        )
        brief = await scout.run()
        logger.info(f"[Orch][job={job_id}] Scout complete: modality={brief.modality} task={brief.task_type}")

        # Phase 2: Forge
        await self._redis.set(f"job:{job_id}:status", "FORGE_RUNNING")
        forge = ForgeAgent(job_id=job_id, redis_client=self._redis)
        script_path = await forge.run()
        logger.info(f"[Orch][job={job_id}] Forge complete: script={script_path}")

        # Phase 3: Furnace
        await self._redis.set(f"job:{job_id}:status", "FURNACE_RUNNING")
        furnace = FurnaceAgent(job_id=job_id, redis_client=self._redis)
        result = await furnace.run(script_path=script_path)

        await self._redis.set(f"job:{job_id}:status", "COMPLETE")
        logger.info(f"[Orch][job={job_id}] Job complete: {result}")
        return result
```

**Create `tests/integration/test_titanic_e2e.py`:**
```python
"""
Phase 1 gate test. This test must stay green for the rest of the project.
Run: pytest tests/integration/test_titanic_e2e.py -v
"""

import asyncio
import json
import os
import pytest
import redis.asyncio as aioredis

from orchestrator.runtime import Orchestrator

TITANIC_PATH = os.path.abspath("data/titanic.csv")


@pytest.fixture
def require_titanic():
    if not os.path.exists(TITANIC_PATH):
        pytest.skip(
            f"Titanic dataset not found at {TITANIC_PATH}. "
            "YOU DO THIS: Download from kaggle.com/competitions/titanic/data, "
            "copy train.csv to data/titanic.csv"
        )


@pytest.mark.asyncio
async def test_titanic_e2e(require_titanic):
    """
    Full pipeline: Titanic CSV → Scout → Forge → Furnace.
    Verifies:
    1. MissionBrief has correct schema (tabular, classification)
    2. Training script is generated and is valid Python
    3. Training runs and produces checkpoint
    4. val AUC-like metric is > 0.70 (AUC on Titanic should be 0.82+ with LightGBM)
    """
    orch = Orchestrator()
    await orch.connect()

    job_id = await orch.submit_job(
        problem_description="Predict which passengers survived the Titanic disaster.",
        file_path=TITANIC_PATH,
        target_column="Survived",
    )

    result = await orch.run_job(
        job_id=job_id,
        problem_description="Predict which passengers survived the Titanic disaster.",
        file_path=TITANIC_PATH,
        target_column="Survived",
    )

    # Verify mission brief
    r = aioredis.Redis(host="localhost", port=6379, decode_responses=True)
    brief_raw = await r.get(f"job:{job_id}:mission_brief")
    assert brief_raw is not None, "Mission brief not found in Redis"
    brief = json.loads(brief_raw)
    assert brief["modality"] == "tabular"
    assert brief["task_type"] == "classification"
    assert brief["target_column"] == "Survived"

    # Verify training script exists
    script_path = f"scripts/training_script_{job_id}.py"
    assert os.path.exists(script_path), f"Training script not found: {script_path}"

    # Verify checkpoint exists
    checkpoint_path = result.get("checkpoint_path")
    assert checkpoint_path is not None, "No checkpoint path in result"
    assert os.path.exists(checkpoint_path), f"Checkpoint not found: {checkpoint_path}"

    # Verify metric
    best_metric = result.get("best_val_metric", 0)
    assert best_metric > 0.70, (
        f"Val metric {best_metric:.4f} below 0.70. "
        "Forge may have generated a poor training script. Check scripts/ directory."
    )

    await r.aclose()
    print(f"\nPhase 1 Gate PASSED | job_id={job_id} | val_metric={best_metric:.4f}")
```

**Run Phase 1 gate:**
```bash
pytest tests/integration/test_titanic_e2e.py -v -s
```

If it fails because the training script is bad Python, open `scripts/training_script_{job_id}.py`
and look at what Forge generated. The most common issues:
- LLM added markdown fences despite instructions → already handled in forge/agent.py
- LLM hallucinated an import → fix by adding the package to the training image Dockerfile
- LLM didn't follow the JSON stdout format → adjust forge/tools.py prompt

After each fix: `pytest tests/integration/test_titanic_e2e.py -v`

Gate passes when: test is green AND `best_val_metric > 0.70`.

```bash
git add -A
git commit -m "[Phase1] Gate passed — Titanic E2E: Scout + Forge + Furnace"
```

Update `.env`: `PHASE_1_COMPLETE=true`

---

## PHASE 2 — DISSECT + ARBITER + HARBOR
**Duration: 5 days | Goal: Full pipeline with crash recovery on 3 datasets**
**⚠️ This is the most complex phase. The Furnace↔Dissect crash-recovery loop is the hardest part of the entire system. Budget 2-3 extra days if debugging takes longer than expected — this phase contains the core scientific contribution and getting it right matters more than hitting the day count.**

---

### DAY 2-1 to 2-2: Dissect Taxonomy + Tools

**Create `agents/dissect/taxonomy.py`:**
```python
"""
Dissect error taxonomy. AI Lead (Mohamed) owns this file.
Do not add categories without updating CLAUDE.md Section 8.
"""

import re
from dataclasses import dataclass
from typing import Callable


@dataclass
class TaxonomyEntry:
    category: str
    exception_types: list[str]          # Python exception class names
    message_patterns: list[str]         # Regex patterns to match exception message
    repair_strategy: str                # Human-readable strategy description
    confidence: float                   # How confident we are in regex match


# All 11 categories from CLAUDE.md Section 8
TAXONOMY: list[TaxonomyEntry] = [
    TaxonomyEntry(
        category="shape_mismatch",
        exception_types=["ValueError"],
        message_patterns=[
            r"X has \d+ features? but \w+ is expecting \d+ features?",
            r"has \d+ features, \w+ expects \d+",
            r"shapes? .* not aligned",
            r"operands could not be broadcast",
        ],
        repair_strategy=(
            "Detect dropped columns in preprocessing. "
            "Re-align feature list between fit and transform steps. "
            "Regenerate or reload the fitted encoder."
        ),
        confidence=0.95,
    ),
    TaxonomyEntry(
        category="sparse_matrix",
        exception_types=["TypeError"],
        message_patterns=[
            r"(SMOTE|ADASYN|RandomOverSampler).* (does not|cannot) support sparse",
            r"sparse (matrix|array|input) .* not supported",
            r"A sparse matrix was passed",
        ],
        repair_strategy=(
            "Convert sparse matrix to dense with .toarray() before resampling. "
            "Or replace SMOTE with class_weight parameter on the model."
        ),
        confidence=0.95,
    ),
    TaxonomyEntry(
        category="oom",
        exception_types=["MemoryError"],
        message_patterns=[
            r"cannot allocate",
            r"out of memory",
            r"MemoryError",
            r"Unable to allocate",
        ],
        repair_strategy=(
            "Reduce batch size by 50%. "
            "Switch to chunked data loading with pandas chunksize. "
            "If still OOM, flag to user."
        ),
        confidence=0.90,
    ),
    TaxonomyEntry(
        category="cuda_oom",
        exception_types=["RuntimeError"],
        message_patterns=[
            r"CUDA out of memory",
            r"CUDA error.*memory",
            r"device-side assert triggered",
        ],
        repair_strategy=(
            "Halve the batch size. "
            "Enable gradient checkpointing: model.gradient_checkpointing_enable(). "
            "Clear GPU cache: torch.cuda.empty_cache()."
        ),
        confidence=0.95,
    ),
    TaxonomyEntry(
        category="missing_column",
        exception_types=["KeyError"],
        message_patterns=[
            r"'[\w\s]+' not (found|in) (DataFrame|dataframe|columns?|keys?)",
            r"KeyError: '[\w\s]+'",
            r"column '[\w\s]+' does not exist",
        ],
        repair_strategy=(
            "Detect the missing column name from the KeyError. "
            "Check if it's a derived column (e.g., log transform). "
            "Add the missing derivation step before the line that needs it."
        ),
        confidence=0.90,
    ),
    TaxonomyEntry(
        category="dtype_mismatch",
        exception_types=["ValueError"],
        message_patterns=[
            r"could not convert string to float",
            r"invalid literal for (int|float)",
            r"cannot convert.*to (numeric|float|int)",
            r"object dtype .* not supported",
        ],
        repair_strategy=(
            "Detect which column has non-numeric dtype. "
            "Add LabelEncoder or OrdinalEncoder for that column before model fit. "
            "Place encoder in preprocessing pipeline before the offending step."
        ),
        confidence=0.90,
    ),
    TaxonomyEntry(
        category="convergence_failure",
        exception_types=["ConvergenceWarning", "RuntimeWarning"],
        message_patterns=[
            r"(lbfgs|sag|saga|liblinear) failed to converge",
            r"Maximum number of iteration reached",
            r"did not converge",
        ],
        repair_strategy=(
            "Increase max_iter to 1000 or higher. "
            "Switch solver from lbfgs to saga. "
            "Reduce regularisation strength (increase C for LogisticRegression)."
        ),
        confidence=0.85,
    ),
    TaxonomyEntry(
        category="import_error",
        exception_types=["ModuleNotFoundError", "ImportError"],
        message_patterns=[
            r"No module named '[\w.]+'",
            r"cannot import name '[\w]+' from '[\w.]+'",
        ],
        repair_strategy=(
            "Extract the module name from the error. "
            "Add pip install <module> to the Docker container setup, "
            "or replace the import with an equivalent available package."
        ),
        confidence=0.98,
    ),
    TaxonomyEntry(
        category="nan_propagation",
        exception_types=["ValueError"],
        message_patterns=[
            r"Input (contains|has) NaN",
            r"NaN (values?|encountered)",
            r"contains? NaN, infinity or a value too large",
        ],
        repair_strategy=(
            "Detect which columns have NaN values after preprocessing. "
            "Apply SimpleImputer: median for numeric, most_frequent for categorical. "
            "Place imputer before the step that raised the error."
        ),
        confidence=0.92,
    ),
    TaxonomyEntry(
        category="checkpoint_corruption",
        exception_types=["UnpicklingError", "EOFError", "OSError"],
        message_patterns=[
            r"invalid load key",
            r"(UnpicklingError|pickle.*error)",
            r"(EOF|end of file) (reached|marker)",
        ],
        repair_strategy=(
            "Delete the corrupted checkpoint file. "
            "Restart training from epoch 0. "
            "Increase checkpoint save frequency to every epoch."
        ),
        confidence=0.88,
    ),
    TaxonomyEntry(
        category="novel_error",
        exception_types=[],  # Catches everything that doesn't match above
        message_patterns=[],
        repair_strategy=(
            "Use LLM backbone with full error context. "
            "If LLM confidence < 0.6, escalate immediately."
        ),
        confidence=0.0,  # Set by LLM classification
    ),
]


def classify_error(
    exception_type: str,
    exception_message: str,
) -> tuple[str, float, str]:
    """
    Classify an error into a taxonomy category.

    Returns:
        (category, confidence, match_method)
        match_method is "regex" or "llm_classification"
    """
    for entry in TAXONOMY[:-1]:  # Skip "novel_error" entry (last)
        # Check exception type
        if entry.exception_types and exception_type not in entry.exception_types:
            continue

        # Check message patterns
        for pattern in entry.message_patterns:
            if re.search(pattern, exception_message, re.IGNORECASE):
                return entry.category, entry.confidence, "regex"

    # No match — will be classified by LLM
    return "novel_error", 0.0, "llm_classification"
```

**Create `agents/dissect/tools.py`:**
```python
"""
Dissect tools: parse trace, classify, generate patch, apply patch, sandbox test.
SWE Engineer 1 owns this file (except classify_error which calls taxonomy.py).
"""

import difflib
import json
import logging
import os
import re
import subprocess
import tempfile
import traceback as tb_module
import uuid
from pathlib import Path

from agents.dissect.taxonomy import classify_error as taxonomy_classify

logger = logging.getLogger(__name__)

OUTPUTS_DIR = os.getenv("OUTPUTS_DIR", "./outputs")
TRAINING_IMAGE = os.getenv("TRAINING_IMAGE_NAME", "prometheus-training-base")


def parse_stack_trace(
    exception_type: str,
    exception_message: str,
    traceback_str: str,
) -> dict:
    """
    Parse a stack trace into structured components.
    Returns dict with: exception_type, exception_message, failing_file,
    failing_line, failing_function, traceback_lines.
    """
    lines = traceback_str.strip().split("\n")
    failing_file = None
    failing_line = None
    failing_function = None

    for line in reversed(lines):
        # Look for: File "path/to/file.py", line N, in function_name
        match = re.match(r'\s*File "(.*?)", line (\d+), in (\w+)', line)
        if match:
            failing_file = match.group(1)
            failing_line = int(match.group(2))
            failing_function = match.group(3)
            break

    return {
        "exception_type": exception_type,
        "exception_message": exception_message,
        "failing_file": failing_file,
        "failing_line": failing_line,
        "failing_function": failing_function,
        "traceback_lines": lines,
    }


def apply_patch(script_path: str, patched_code: str) -> tuple[bool, str]:
    """
    Replace the content of script_path with patched_code.
    Keeps a backup. Returns (success, error_message).
    Atomic: if write fails, original is restored.
    """
    backup_path = script_path + ".bak"

    try:
        # Read original
        with open(script_path, "r") as f:
            original = f.read()

        # Write backup
        with open(backup_path, "w") as f:
            f.write(original)

        # Write patch
        with open(script_path, "w") as f:
            f.write(patched_code)

        return True, ""

    except Exception as e:
        # Restore from backup if it exists
        if os.path.exists(backup_path):
            try:
                with open(backup_path, "r") as f:
                    original = f.read()
                with open(script_path, "w") as f:
                    f.write(original)
            except Exception:
                pass
        return False, str(e)


def rollback_patch(script_path: str) -> bool:
    """Restore script from its .bak backup. Returns True if successful."""
    backup_path = script_path + ".bak"
    if not os.path.exists(backup_path):
        return False
    try:
        with open(backup_path, "r") as f:
            original = f.read()
        with open(script_path, "w") as f:
            f.write(original)
        return True
    except Exception:
        return False


def compute_diff(original: str, patched: str) -> str:
    """Compute unified diff between original and patched code strings."""
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    diff = difflib.unified_diff(
        original_lines, patched_lines,
        fromfile="original", tofile="patched"
    )
    return "".join(diff)


def run_sandbox_test(script_path: str, job_id: str, max_epochs: int = 3) -> tuple[bool, str]:
    """
    Run the patched script in a Docker container for max_epochs.
    Returns (passed, error_message).
    A pass means the script ran max_epochs without crashing.
    """
    import docker as docker_sdk

    container_name = f"prometheus-sandbox-{job_id}-{uuid.uuid4().hex[:8]}"

    try:
        client = docker_sdk.from_env()

        # Mount only the script and data — no outputs needed for sandbox
        data_dir = os.path.abspath(os.getenv("DATA_DIR", "./data"))
        volumes = {
            os.path.abspath(script_path): {"bind": "/app/script.py", "mode": "ro"},
            data_dir: {"bind": "/app/data", "mode": "ro"},
        }

        container = client.containers.run(
            image=TRAINING_IMAGE,
            name=container_name,
            volumes=volumes,
            environment={
                "JOB_ID": f"{job_id}-sandbox",
                "MAX_EPOCHS": str(max_epochs),
                "PYTHONUNBUFFERED": "1",
            },
            detach=True,
            stdout=True,
            stderr=True,
        )

        # Wait for container to finish (timeout: 5 minutes)
        result = container.wait(timeout=300)
        exit_code = result["StatusCode"]

        if exit_code == 0:
            container.remove()
            return True, ""
        else:
            stderr = container.logs(stderr=True, stdout=False).decode("utf-8")
            container.remove()
            return False, stderr[-2000:]  # Last 2000 chars of error

    except Exception as e:
        try:
            client.containers.get(container_name).remove(force=True)
        except Exception:
            pass
        return False, str(e)
```

**Create `agents/dissect/patch_log.py`:**
```python
"""
Patch log writer for Dissect. Pushes entries to Redis patch_log_queue.
NEVER writes directly to patch_log.jsonl — that's orchestrator/patch_log_writer.py's job.
"""

import json
import logging

import redis.asyncio as aioredis

from memory.schemas import PatchLogEntry

logger = logging.getLogger(__name__)


async def write_patch_log(redis_client: aioredis.Redis, entry: PatchLogEntry) -> None:
    """
    Serialize entry and push to Redis patch_log_queue.
    The patch_log_writer background process reads from this queue and writes to the file.
    """
    raw = entry.model_dump_json()
    await redis_client.rpush("patch_log_queue", raw)
    logger.debug(f"Patch log entry queued: patch_id={entry.patch_id}")
```

**Create `agents/dissect/prompts.py`:**
```python
DISSECT_SYSTEM_PROMPT = """You are Dissect, the Debugger agent in the Prometheus Swarm system.

Your ONLY job is to analyze a Python training script crash and produce a fixed version
of the script.

YOU MUST:
1. Output ONLY the complete fixed Python script. No explanations. No markdown.
2. The first line of your output must be a Python import statement.
3. Preserve ALL functionality of the original script — only fix the error.
4. Apply the MINIMUM change needed to fix the specific error. Do not refactor.
5. If you are less than 60% confident the fix is correct, output exactly:
   ESCALATE: <reason>
   (This tells the system to give up and alert the human.)

APPROACH:
1. Read the error: exception type + message + traceback
2. Find the EXACT line that caused the error (last "File" line in traceback)
3. Apply the repair strategy for this error category
4. Output the complete fixed script

DO NOT add imports that weren't in the original unless the repair requires it.
DO NOT change model hyperparameters, training logic, or evaluation code.
ONLY fix the specific error.
"""
```

**Create `agents/dissect/agent.py`:**
```python
"""
Dissect agent — The Debugger. Core scientific contribution.
Subscribes to CRASH_EVENT → classifies error → generates patch →
applies patch → sandbox test → RESUME_TRAINING or ESCALATE.
"""

import json
import logging
import uuid

import redis.asyncio as aioredis

from agents.base import BaseAgent
from agents.dissect.prompts import DISSECT_SYSTEM_PROMPT
from agents.dissect.taxonomy import classify_error
from agents.dissect.tools import (
    parse_stack_trace, apply_patch, rollback_patch, compute_diff, run_sandbox_test,
)
from agents.dissect.patch_log import write_patch_log
from bus.events import RESUME_TRAINING, ESCALATE, STREAM_DISSECT_OUTPUT
from bus.publisher import publish
from memory.schemas import PatchLogEntry
from serving.metrics import (
    dissect_patches_attempted_total, dissect_patches_successful_total,
    dissect_patches_escalated_total, dissect_patch_confidence,
    dissect_patch_duration_seconds,
)
import time

logger = logging.getLogger(__name__)


class DissectAgent(BaseAgent):

    def __init__(self, job_id: str, redis_client: aioredis.Redis):
        super().__init__(job_id)
        self._redis = redis_client

    @property
    def agent_name(self) -> str:
        return "Dissect"

    @property
    def system_prompt(self) -> str:
        return DISSECT_SYSTEM_PROMPT

    async def handle_crash(self, crash_event: dict) -> None:
        """
        Full Dissect repair cycle for one crash event.
        Publishes RESUME_TRAINING on success or ESCALATE after 3 failures.
        """
        start_time = time.time()

        exception_type = crash_event["exception_type"]
        exception_message = crash_event["exception_message"]
        traceback_str = crash_event["traceback"]
        script_path = crash_event["script_path"]
        last_checkpoint = crash_event.get("last_checkpoint_path")
        attempt_number = crash_event.get("crash_attempt_number", 1)

        logger.info(
            f"[Dissect][job={self.job_id}] Handling crash #{attempt_number}: "
            f"{exception_type}: {exception_message[:100]}"
        )

        # Step 1: Parse stack trace
        parsed = parse_stack_trace(exception_type, exception_message, traceback_str)

        # Step 2: Classify error
        category, confidence, match_method = classify_error(exception_type, exception_message)
        logger.info(f"[Dissect][job={self.job_id}] Classified as: {category} (confidence={confidence:.2f})")

        dissect_patches_attempted_total.labels(
            error_category=category, attempt_number=str(attempt_number)
        ).inc()

        # Step 3: Read original script
        try:
            with open(script_path, "r") as f:
                original_code = f.read()
        except Exception as e:
            await self._escalate(crash_event, f"Cannot read script: {e}", attempt_number, category)
            return

        # Step 4: Generate patch via LLM
        repair_prompt = f"""
ERROR TYPE: {exception_type}
ERROR MESSAGE: {exception_message}
ERROR CATEGORY: {category}
REPAIR STRATEGY: {self._get_strategy(category)}

STACK TRACE:
{traceback_str}

ORIGINAL SCRIPT:
{original_code}

Fix the error and output the complete corrected script.
Remember: output ONLY Python code, or ESCALATE: <reason> if unsure.
"""

        response = await self.call_llm(user_message=repair_prompt)
        patched_code = response["text"].strip()

        # Check for explicit escalation
        if patched_code.upper().startswith("ESCALATE:"):
            reason = patched_code[9:].strip()
            await self._escalate(crash_event, reason, attempt_number, category)
            return

        # Clean markdown fences if present
        if patched_code.startswith("```python"):
            patched_code = patched_code[9:]
        if patched_code.startswith("```"):
            patched_code = patched_code[3:]
        if patched_code.endswith("```"):
            patched_code = patched_code[:-3]
        patched_code = patched_code.strip()

        # Compute diff for logging
        diff = compute_diff(original_code, patched_code)
        lines_changed = sum(1 for line in diff.split("\n") if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))

        # Step 5: Apply patch
        success, error = apply_patch(script_path, patched_code)
        if not success:
            await self._escalate(crash_event, f"Failed to apply patch: {error}", attempt_number, category)
            return

        # Step 6: Sandbox test
        sandbox_passed, sandbox_error = run_sandbox_test(script_path, self.job_id)

        if not sandbox_passed:
            logger.warning(f"[Dissect][job={self.job_id}] Sandbox failed: {sandbox_error[:200]}")
            rollback_patch(script_path)

            # Write patch log (outcome=rollback)
            patch_id = str(uuid.uuid4())
            entry = PatchLogEntry(
                patch_id=patch_id,
                job_id=self.job_id,
                exception_type=exception_type,
                exception_message=exception_message,
                error_taxonomy_category=category,
                taxonomy_match_method=match_method,
                repair_strategy_used=self._get_strategy(category),
                diff_applied=diff,
                lines_changed=lines_changed,
                sandbox_test_result="fail",
                patch_outcome="rollback",
                confidence_score=confidence,
                attempt_number=attempt_number,
                resume_from_checkpoint=last_checkpoint,
            )
            await write_patch_log(self._redis, entry)

            if attempt_number >= 3:
                await self._escalate(crash_event, "All 3 patch attempts failed sandbox test", attempt_number, category)
            else:
                # Signal Furnace: crash again so it increments attempt_number and re-publishes
                await publish(
                    self._redis, STREAM_DISSECT_OUTPUT, ESCALATE,
                    {
                        "job_id": self.job_id,
                        "source_agent": "Dissect",
                        "reason": f"Attempt {attempt_number} sandbox failed: {sandbox_error[:200]}",
                        "diagnostic_report_path": f"outputs/{self.job_id}/diagnostic.json",
                    }
                )
            return

        # Step 7: Sandbox passed — write success log
        patch_id = str(uuid.uuid4())
        entry = PatchLogEntry(
            patch_id=patch_id,
            job_id=self.job_id,
            exception_type=exception_type,
            exception_message=exception_message,
            error_taxonomy_category=category,
            taxonomy_match_method=match_method,
            repair_strategy_used=self._get_strategy(category),
            diff_applied=diff,
            lines_changed=lines_changed,
            sandbox_test_result="pass",
            patch_outcome="success",
            confidence_score=confidence,
            attempt_number=attempt_number,
            resume_from_checkpoint=last_checkpoint,
        )
        await write_patch_log(self._redis, entry)

        dissect_patches_successful_total.labels(error_category=category).inc()
        dissect_patch_confidence.labels(error_category=category).observe(confidence)
        dissect_patch_duration_seconds.observe(time.time() - start_time)

        # Step 8: Publish RESUME_TRAINING
        await publish(
            self._redis, STREAM_DISSECT_OUTPUT, RESUME_TRAINING,
            {
                "job_id": self.job_id,
                "patched_script_path": script_path,
                "resume_from_checkpoint": last_checkpoint,
                "patch_id": patch_id,
            }
        )
        logger.info(f"[Dissect][job={self.job_id}] Published RESUME_TRAINING | patch_id={patch_id}")

    async def _escalate(self, crash_event: dict, reason: str, attempt_number: int, category: str) -> None:
        """Write escalated patch log entry and publish ESCALATE."""
        import uuid as _uuid
        patch_id = str(_uuid.uuid4())

        entry = PatchLogEntry(
            patch_id=patch_id,
            job_id=self.job_id,
            exception_type=crash_event.get("exception_type", "Unknown"),
            exception_message=crash_event.get("exception_message", ""),
            error_taxonomy_category=category,
            taxonomy_match_method="regex",
            repair_strategy_used="escalated",
            diff_applied="",
            lines_changed=0,
            sandbox_test_result="fail",
            patch_outcome="escalated",
            confidence_score=0.0,
            attempt_number=attempt_number,
        )
        await write_patch_log(self._redis, entry)

        dissect_patches_escalated_total.inc()

        await publish(
            self._redis, STREAM_DISSECT_OUTPUT, ESCALATE,
            {
                "job_id": self.job_id,
                "source_agent": "Dissect",
                "reason": reason,
                "diagnostic_report_path": f"outputs/{self.job_id}/diagnostic.json",
            }
        )
        logger.warning(f"[Dissect][job={self.job_id}] ESCALATED: {reason}")

    def _get_strategy(self, category: str) -> str:
        from agents.dissect.taxonomy import TAXONOMY
        for entry in TAXONOMY:
            if entry.category == category:
                return entry.repair_strategy
        return "Unknown category"

    async def run(self) -> None:
        """Not used directly — Dissect is called by Orchestrator via handle_crash()."""
        pass
```

**Create `tests/unit/test_dissect_taxonomy.py`:**
```python
"""Unit tests for Dissect taxonomy — one test per error category."""
import pytest
from agents.dissect.taxonomy import classify_error


def test_shape_mismatch():
    cat, conf, method = classify_error("ValueError", "X has 45 features but LightGBM is expecting 40 features")
    assert cat == "shape_mismatch"
    assert method == "regex"
    assert conf > 0.8

def test_sparse_matrix():
    cat, conf, method = classify_error("TypeError", "SMOTE does not support sparse matrices")
    assert cat == "sparse_matrix"

def test_oom():
    cat, conf, method = classify_error("MemoryError", "cannot allocate array")
    assert cat == "oom"

def test_cuda_oom():
    cat, conf, method = classify_error("RuntimeError", "CUDA out of memory. Tried to allocate 2 GiB")
    assert cat == "cuda_oom"

def test_missing_column():
    cat, conf, method = classify_error("KeyError", "'income_log' not found in DataFrame")
    assert cat == "missing_column"

def test_dtype_mismatch():
    cat, conf, method = classify_error("ValueError", "could not convert string to float: 'N/A'")
    assert cat == "dtype_mismatch"

def test_convergence_failure():
    cat, conf, method = classify_error("ConvergenceWarning", "lbfgs failed to converge after 100 iterations")
    assert cat == "convergence_failure"

def test_import_error():
    cat, conf, method = classify_error("ModuleNotFoundError", "No module named 'lightgbm'")
    assert cat == "import_error"

def test_nan_propagation():
    cat, conf, method = classify_error("ValueError", "Input contains NaN, infinity or a value too large")
    assert cat == "nan_propagation"

def test_novel_error_fallback():
    cat, conf, method = classify_error("SomeFakeError", "completely unknown error message xyz123")
    assert cat == "novel_error"
    assert method == "llm_classification"
```

```bash
pytest tests/unit/test_dissect_taxonomy.py -v
```
Expected: all 10 tests pass.

**Create injected error fixtures in `tests/fixtures/injected_errors/`:**

`01_shape_mismatch.py` — script with a deliberate shape mismatch:
```python
# Injected error: shape mismatch
# The encoder is fit on 5 features but transform is called on 4
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import GradientBoostingClassifier
import json, sys, os

df = pd.read_csv("/app/data/titanic.csv")
features = ["Pclass", "Age", "SibSp", "Parch", "Fare"]
target = "Survived"
df = df.dropna(subset=[target])
df[features] = df[features].fillna(df[features].median())

X = df[features].values
y = df[target].values

scaler = StandardScaler()
scaler.fit(X)  # fit on 5 features

# BUG: transform only 4 features
X_transformed = scaler.transform(X[:, :4])  # WRONG: drops last feature

clf = GradientBoostingClassifier(n_estimators=10)
clf.fit(X_transformed, y)
print(json.dumps({"type": "training_complete", "best_val_metric": 0.8, "total_epochs": 1, "checkpoint_path": "/app/outputs/best.ckpt"}))
```

`02_dtype_mismatch.py`:
```python
# Injected error: dtype mismatch — categorical column not encoded
import pandas as pd
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier
import json, sys, os

df = pd.read_csv("/app/data/titanic.csv")
target = "Survived"
df = df.dropna(subset=[target])

# BUG: include "Sex" (string) without encoding
features = ["Pclass", "Sex", "Age", "Fare"]
df[["Age", "Fare"]] = df[["Age", "Fare"]].fillna(0)

X = df[features].values  # This will include string "male"/"female"
y = df[target].values

clf = GradientBoostingClassifier(n_estimators=10)
clf.fit(X, y)  # CRASH: cannot fit on string values
print(json.dumps({"type": "training_complete", "best_val_metric": 0.8, "total_epochs": 1, "checkpoint_path": "/app/outputs/best.ckpt"}))
```

`03_missing_column.py`:
```python
# Injected error: derived column referenced but never created
import pandas as pd
import json, sys, os
from sklearn.ensemble import GradientBoostingClassifier

df = pd.read_csv("/app/data/titanic.csv")
target = "Survived"
df = df.dropna(subset=[target])

# BUG: "Age_log" never created, but referenced
features = ["Pclass", "Age_log", "Fare"]
X = df[features].values  # CRASH: KeyError on "Age_log"
y = df[target].values

clf = GradientBoostingClassifier(n_estimators=10)
clf.fit(X, y)
print(json.dumps({"type": "training_complete", "best_val_metric": 0.8, "total_epochs": 1, "checkpoint_path": "/app/outputs/best.ckpt"}))
```

`04_nan_propagation.py`:
```python
# Injected error: NaN passed to model without imputation
import pandas as pd
import json, sys, os
from sklearn.ensemble import GradientBoostingClassifier

df = pd.read_csv("/app/data/titanic.csv")
target = "Survived"
df = df.dropna(subset=[target])

# BUG: no fillna — Age has NaN values
features = ["Pclass", "Age", "Fare"]
X = df[features].values  # Contains NaN from Age column
y = df[target].values

clf = GradientBoostingClassifier(n_estimators=10)
clf.fit(X, y)  # CRASH: Input contains NaN
print(json.dumps({"type": "training_complete", "best_val_metric": 0.8, "total_epochs": 1, "checkpoint_path": "/app/outputs/best.ckpt"}))
```

`05_import_error.py`:
```python
# Injected error: import of non-existent module
import fake_ml_library_xyz  # CRASH: ModuleNotFoundError
import pandas as pd
import json

df = pd.read_csv("/app/data/titanic.csv")
print(json.dumps({"type": "training_complete", "best_val_metric": 0.8, "total_epochs": 1, "checkpoint_path": "/app/outputs/best.ckpt"}))
```

---

### DAY 2-3 to 2-4: Arbiter + Harbor

**Create `agents/arbiter/agent.py`:**
```python
"""
Arbiter agent — The Critic.
Subscribes to TRAINING_COMPLETE → loads checkpoint → evaluates → decides PASS/RETRY/ESCALATE.
"""

import json
import logging
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import redis.asyncio as aioredis
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score,
    mean_squared_error, mean_absolute_error, r2_score,
)

from agents.base import BaseAgent
from bus.events import (
    EVALUATION_PASS, EVALUATION_RETRY, ESCALATE,
    STREAM_ARBITER_OUTPUT,
)
from bus.publisher import publish
from memory.schemas import EvalReport, MissionBrief
from serving.metrics import arbiter_decisions_total, arbiter_primary_metric_value

logger = logging.getLogger(__name__)

ARBITER_SYSTEM_PROMPT = "You are Arbiter, the Critic agent. You evaluate ML models."

# Minimum acceptable metric thresholds (classification)
THRESHOLDS = {
    "auc_roc": 0.70,
    "f1": 0.65,
    "map": 0.50,
}
# Regression metrics (rmse, mae) use dynamic dataset-relative thresholds computed at runtime


class ArbiterAgent(BaseAgent):

    def __init__(self, job_id: str, redis_client: aioredis.Redis):
        super().__init__(job_id)
        self._redis = redis_client

    @property
    def agent_name(self) -> str:
        return "Arbiter"

    @property
    def system_prompt(self) -> str:
        return ARBITER_SYSTEM_PROMPT

    async def run(self, checkpoint_path: str) -> EvalReport:
        """Load checkpoint, evaluate, write report, publish decision."""
        logger.info(f"[Arbiter][job={self.job_id}] Evaluating: {checkpoint_path}")

        # Read mission brief for test data location + metric
        brief_raw = await self._redis.get(f"job:{self.job_id}:mission_brief")
        brief = MissionBrief(**json.loads(brief_raw))

        # Load test data (use 20% holdout)
        df = pd.read_csv(brief.dataset.file_path)
        if brief.target_column not in df.columns:
            raise ValueError(f"Target column '{brief.target_column}' not in dataset")

        df = df.dropna(subset=[brief.target_column])
        split_idx = int(len(df) * 0.8)
        test_df = df.iloc[split_idx:]

        feature_cols = [c for c, t in brief.dataset.column_types.items()
                        if t in ("numeric", "categorical") and c != brief.target_column]
        X_test = test_df[feature_cols]
        y_test = test_df[brief.target_column]

        # Load model
        with open(checkpoint_path, "rb") as f:
            model_bundle = pickle.load(f)

        model = model_bundle.get("model") if isinstance(model_bundle, dict) else model_bundle

        # Get predictions
        try:
            y_pred = model.predict(X_test)
            y_proba = model.predict_proba(X_test)[:, 1] if hasattr(model, "predict_proba") else None
        except Exception as e:
            logger.error(f"[Arbiter] Prediction failed: {e}")
            raise

        # Compute metrics
        all_metrics = {}
        primary_metric = brief.evaluation_metric or "auc_roc"

        if brief.task_type == "classification":
            if y_proba is not None:
                all_metrics["auc_roc"] = float(roc_auc_score(y_test, y_proba))
            all_metrics["f1"] = float(f1_score(y_test, y_pred, average="weighted", zero_division=0))
            all_metrics["precision"] = float(precision_score(y_test, y_pred, average="weighted", zero_division=0))
            all_metrics["recall"] = float(recall_score(y_test, y_pred, average="weighted", zero_division=0))
        else:
            all_metrics["rmse"] = float(np.sqrt(mean_squared_error(y_test, y_pred)))
            all_metrics["mae"] = float(mean_absolute_error(y_test, y_pred))
            all_metrics["r2"] = float(r2_score(y_test, y_pred))

        primary_value = all_metrics.get(primary_metric, 0.0)
        threshold = THRESHOLDS.get(primary_metric, 0.70)

        # Failure analysis: find worst-performing slice
        failure_analysis = self._analyze_failures(X_test, y_test, y_pred)

        # Decision logic (CLAUDE.md Section 3.5)
        crash_count = int(await self._redis.get(f"job:{self.job_id}:crash_count") or 0)

        if crash_count >= 3:
            decision = "escalate"
            reason = f"3+ training crashes. Primary metric: {primary_metric}={primary_value:.4f}"
        elif primary_metric in ("rmse", "mae"):
            # Dynamic regression threshold: must beat naive mean prediction by 15%
            baseline_std = np.std(y_test)
            threshold_val = baseline_std * 0.85
            if primary_value <= threshold_val:
                decision = "pass"
                reason = f"Beat std_dev threshold ({primary_value:.4f} <= {threshold_val:.4f})"
            elif primary_value <= baseline_std:
                decision = "retry"
                reason = f"Marginal performance ({primary_value:.4f} > {threshold_val:.4f})"
            else:
                decision = "escalate"
                reason = f"Worse than naive mean ({primary_value:.4f} > {baseline_std:.4f})"
        else:
            # Classification static threshold
            if primary_value >= threshold:
                decision = "pass"
                reason = f"Exceeded threshold ({primary_value:.4f} >= {threshold})"
            elif primary_value >= (threshold * 0.85):
                decision = "retry"
                reason = f"Within 15% of threshold ({primary_value:.4f} < {threshold})"
            else:
                decision = "escalate"
                reason = f"Failed threshold ({primary_value:.4f} < {threshold})"

        # Write eval report
        report = EvalReport(
            job_id=self.job_id,
            checkpoint_path=checkpoint_path,
            task_type=brief.task_type,
            primary_metric=primary_metric,
            primary_metric_value=primary_value,
            all_metrics=all_metrics,
            failure_analysis=failure_analysis,
            decision=decision,
            decision_reason=reason,
        )

        report_path = f"outputs/{self.job_id}/eval_report_{self.job_id}.json"
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w") as f:
            f.write(report.model_dump_json(indent=2))

        arbiter_decisions_total.labels(decision=decision).inc()
        arbiter_primary_metric_value.labels(
            job_id=self.job_id, metric_name=primary_metric
        ).set(primary_value)

        # Publish decision
        if decision == "pass":
            event_type = EVALUATION_PASS
        elif decision == "retry":
            event_type = EVALUATION_RETRY
        else:
            event_type = ESCALATE

        await publish(
            self._redis, STREAM_ARBITER_OUTPUT, event_type,
            {
                "job_id": self.job_id,
                "eval_report_path": report_path,
                "primary_metric": primary_metric,
                "primary_metric_value": primary_value,
                "reason": reason,
                "source_agent": "Arbiter",
                "diagnostic_report_path": report_path,
            }
        )

        logger.info(f"[Arbiter][job={self.job_id}] Decision: {decision} | {reason}")
        return report

    def _analyze_failures(self, X_test, y_test, y_pred) -> str:
        """Simple failure analysis: find the class or slice with highest error rate."""
        try:
            wrong_mask = y_pred != y_test.values
            error_rate = wrong_mask.mean()
            n_wrong = wrong_mask.sum()
            return (
                f"Overall error rate: {error_rate:.1%} ({n_wrong}/{len(y_test)} samples wrong). "
                f"Check outputs/{self.job_id}/eval_report_{self.job_id}.json for full metrics."
            )
        except Exception as e:
            return f"Failure analysis unavailable: {e}"
```

**Create `agents/harbor/serving_template.py`:**
```python
"""
FastAPI serving template. Harbor fills in JOB_ID, MODEL_PATH, FEATURE_NAMES
and generates a complete FastAPI app file for each deployed model.
"""

SERVING_APP_TEMPLATE = '''
"""Auto-generated serving API for job {JOB_ID}. Do not edit manually."""
import os
import json
import pickle
import time
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

app = FastAPI(title="Prometheus Swarm Model API", version="1.0")

# Load model at startup
MODEL_PATH = "{MODEL_PATH}"
JOB_ID = "{JOB_ID}"
FEATURE_NAMES = {FEATURE_NAMES}

with open(MODEL_PATH, "rb") as f:
    _bundle = pickle.load(f)
_model = _bundle.get("model") if isinstance(_bundle, dict) else _bundle

# Metrics
predict_requests = Counter("prometheus_harbor_prediction_requests_total",
                           "Total prediction requests", ["job_id", "status_code"])
predict_latency = Histogram("prometheus_harbor_prediction_latency_seconds",
                            "Prediction latency", ["job_id"])


class PredictRequest(BaseModel):
    features: dict  # {{feature_name: value, ...}}


class PredictResponse(BaseModel):
    job_id: str
    prediction: float | int | str
    confidence: float | None = None
    latency_ms: float


@app.post("/predict", response_model=PredictResponse)
async def predict(request: PredictRequest):
    start = time.time()
    try:
        X = np.array([[request.features.get(f, 0) for f in FEATURE_NAMES]])
        prediction = _model.predict(X)[0]
        confidence = None
        if hasattr(_model, "predict_proba"):
            proba = _model.predict_proba(X)[0]
            confidence = float(max(proba))
        latency_ms = (time.time() - start) * 1000
        predict_requests.labels(job_id=JOB_ID, status_code="200").inc()
        predict_latency.labels(job_id=JOB_ID).observe(time.time() - start)
        return PredictResponse(
            job_id=JOB_ID,
            prediction=prediction,
            confidence=confidence,
            latency_ms=latency_ms,
        )
    except Exception as e:
        predict_requests.labels(job_id=JOB_ID, status_code="500").inc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {{"job_id": JOB_ID, "model_path": MODEL_PATH, "status": "healthy"}}


@app.get("/metrics")
async def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
'''
```

**Create `agents/harbor/agent.py`:**
```python
"""
Harbor agent — The Deployer.
Subscribes to EVALUATION_PASS → serializes model → generates FastAPI app →
deploys to local Docker Compose → monitors for drift.
"""

import json
import logging
import os
import pickle
import subprocess
import time
import uuid
from pathlib import Path

import redis.asyncio as aioredis

from agents.base import BaseAgent
from agents.harbor.serving_template import SERVING_APP_TEMPLATE
from bus.events import ENDPOINT_LIVE, DRIFT_ALERT, STREAM_HARBOR_OUTPUT
from bus.publisher import publish
from memory.schemas import MissionBrief
from serving.metrics import (
    harbor_prediction_requests_total, harbor_psi_score, harbor_drift_alerts_total,
)

logger = logging.getLogger(__name__)

HARBOR_SYSTEM_PROMPT = "You are Harbor, the Deployer agent. You deploy trained models."
SERVING_PORT = int(os.getenv("SERVING_PORT", 8080))
OUTPUTS_DIR = os.getenv("OUTPUTS_DIR", "./outputs")


class HarborAgent(BaseAgent):

    def __init__(self, job_id: str, redis_client: aioredis.Redis):
        super().__init__(job_id)
        self._redis = redis_client

    @property
    def agent_name(self) -> str:
        return "Harbor"

    @property
    def system_prompt(self) -> str:
        return HARBOR_SYSTEM_PROMPT

    async def run(self, checkpoint_path: str, eval_report_path: str) -> str:
        """
        Full Harbor deployment:
        1. Read mission brief for feature names
        2. Generate FastAPI app from template
        3. Start uvicorn serving process locally (Phase 1-2)
        4. Verify /health endpoint responds
        5. Publish ENDPOINT_LIVE
        Returns: endpoint URL
        """
        logger.info(f"[Harbor][job={self.job_id}] Deploying model from {checkpoint_path}")

        # Read mission brief for feature names
        brief_raw = await self._redis.get(f"job:{self.job_id}:mission_brief")
        brief = MissionBrief(**json.loads(brief_raw))
        feature_names = [
            col for col, dtype in brief.dataset.column_types.items()
            if dtype in ("numeric", "categorical") and col != brief.target_column
        ]

        # Attempt ONNX serialization, fallback to pickle
        model_format = "pickle"
        try:
            import onnxmltools
            from onnxconverter_common.data_types import FloatTensorType
            with open(checkpoint_path, "rb") as f:
                model = pickle.load(f)
            initial_type = [('float_input', FloatTensorType([None, len(feature_names)]))]
            onnx_model = onnxmltools.convert_lightgbm(model, initial_types=initial_type)
            onnx_path = str(checkpoint_path).replace(".pkl", ".onnx")
            onnxmltools.utils.save_model(onnx_model, onnx_path)
            checkpoint_path = onnx_path
            model_format = "onnx"
            logger.info(f"Successfully converted model to ONNX: {onnx_path}")
        except Exception as e:
            logger.warning(f"ONNX conversion failed: {e}. Falling back to pickle.")

        # Generate serving app
        app_code = SERVING_APP_TEMPLATE.format(
            JOB_ID=self.job_id,
            MODEL_PATH=os.path.abspath(checkpoint_path),
            FEATURE_NAMES=repr(feature_names),
        )

        # Write app to outputs dir
        serving_dir = Path(OUTPUTS_DIR) / self.job_id / "serving"
        serving_dir.mkdir(parents=True, exist_ok=True)
        app_path = serving_dir / "app.py"
        with open(app_path, "w") as f:
            f.write(app_code)

        # Write Dockerfile for deployment
        dockerfile_path = serving_dir / "Dockerfile"
        with open(dockerfile_path, "w") as f:
            f.write("FROM python:3.11-slim\nWORKDIR /app\nCOPY . .\nRUN pip install fastapi uvicorn onnxruntime lightgbm pandas\nCMD [\"uvicorn\", \"app:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8080\"]")
        
        # Start uvicorn via Docker container
        port = SERVING_PORT
        import docker
        client = docker.from_env()
        image_tag = f"harbor-{self.job_id}"
        client.images.build(path=str(serving_dir), tag=image_tag)
        container = client.containers.run(
            image_tag,
            detach=True,
            ports={'8080/tcp': port},
            name=f"harbor-serve-{self.job_id}"
        )

        # Wait for startup (up to 30 seconds)
        import httpx
        endpoint_url = f"http://localhost:{port}"
        for _ in range(30):
            try:
                r = httpx.get(f"{endpoint_url}/health", timeout=2.0)
                if r.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError(f"Harbor: serving endpoint did not start in 30s")

        logger.info(f"[Harbor][job={self.job_id}] Endpoint live: {endpoint_url}")

        # Store endpoint URL in Redis
        await self._redis.set(f"job:{self.job_id}:endpoint_url", endpoint_url)

# Publish ENDPOINT_LIVE
        await publish(
            self._redis, STREAM_HARBOR_OUTPUT, ENDPOINT_LIVE,
            {
                "job_id": self.job_id,
                "endpoint_url": endpoint_url,
                "val_metric": 0.0,  # Read from eval report if needed
                "p95_latency_ms": 0.0,
                "model_format": model_format,
            }
        )

        return endpoint_url
```

---

### DAY 2-5: Phase 2 Gate + Three Kaggle E2E Test

**Run full test suite:**
```bash
pytest tests/unit/ -v
pytest tests/integration/test_bus_e2e.py -v
pytest tests/integration/test_titanic_e2e.py -v
```
All must be green before Phase 3.

```bash
git add -A
git commit -m "[Phase2] Gate passed — Dissect + Arbiter + Harbor complete"
```
Update `.env`: `PHASE_2_COMPLETE=true`

---

## PHASE 3 — CHROMADB MEMORY + ORCHESTRATOR HARDENING
**Duration: 5 days | Goal: ChromaDB memory working, Dissect learning from history, orchestrator bulletproof**

---

### DAY 3-1: ChromaDB Memory Layer

**Create `memory/chroma_client.py`:**
```python
"""ChromaDB client — vector database for long-term memory."""
import logging
import os
from typing import Any

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", 8000))


def get_chroma_client() -> chromadb.HttpClient:
    """Return a connected ChromaDB HTTP client."""
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)


def get_or_create_collection(client: chromadb.HttpClient, name: str):
    """Get or create a ChromaDB collection by name."""
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"}
    )
```

**Create `memory/collections/patch_memory.py`:**
```python
"""patch_memory ChromaDB collection — Dissect learns from past patches."""
import json
import logging
from typing import Any

from memory.chroma_client import get_chroma_client, get_or_create_collection
from agents.llm_client import get_embedding
import asyncio

logger = logging.getLogger(__name__)


async def store_patch(patch_entry: dict) -> None:
    """Store a successful patch in patch_memory collection."""
    client = get_chroma_client()
    collection = get_or_create_collection(client, "patch_memory")

    # Create embedding from error description
    query_text = f"{patch_entry['exception_type']}: {patch_entry['exception_message']}"
    embedding = await get_embedding(query_text)

    collection.add(
        ids=[patch_entry["patch_id"]],
        embeddings=[embedding],
        documents=[json.dumps(patch_entry)],
        metadatas=[{
            "error_category": patch_entry["error_taxonomy_category"],
            "patch_outcome": patch_entry["patch_outcome"],
            "confidence_score": str(patch_entry["confidence_score"]),
        }],
    )
    logger.debug(f"Stored patch {patch_entry['patch_id']} in patch_memory")


async def query_similar_patches(exception_type: str, exception_message: str, k: int = 3) -> list[dict]:
    """
    Query patch_memory for the K most similar past patches.
    Returns list of patch entry dicts, ordered by similarity (most similar first).
    """
    client = get_chroma_client()
    collection = get_or_create_collection(client, "patch_memory")

    # Check if collection has any entries
    if collection.count() == 0:
        return []

    query_text = f"{exception_type}: {exception_message}"
    embedding = await get_embedding(query_text)

    results = collection.query(
        query_embeddings=[embedding],
        n_results=min(k, collection.count()),
        include=["documents", "distances", "metadatas"],
    )

    patches = []
    for doc, dist in zip(results["documents"][0], results["distances"][0]):
        entry = json.loads(doc)
        entry["_similarity_score"] = 1 - dist  # cosine distance → similarity
        patches.append(entry)

    return patches
```

---

### DAY 3-2 to 3-3: Orchestrator Hardening

Update `orchestrator/runtime.py` to add:
1. Concurrent Furnace + Dissect using `asyncio.create_task()`
2. Arbiter after TRAINING_COMPLETE
3. Harbor after EVALUATION_PASS
4. ESCALATE handling → JOB_FAILED
5. Start patch_log_writer as background task

The key pattern for concurrent Furnace + Dissect:
```python
# In run_job(), replace sequential Furnace call with:

# Launch patch_log_writer as background task
patch_log_task = asyncio.create_task(run_writer())

# Run Furnace and Dissect concurrently
# Furnace handles its own WAIT state (see furnace/agent.py)
# Dissect is triggered by Furnace's CRASH_EVENT via Redis Streams
furnace = FurnaceAgent(job_id=job_id, redis_client=self._redis)
dissect = DissectAgent(job_id=job_id, redis_client=self._redis)

# Start Dissect listener as background task
async def dissect_listener():
    """Listen for CRASH_EVENTs and call Dissect.handle_crash()"""
    from bus.consumer import ensure_consumer_group
    from bus.events import STREAM_FURNACE_CRASH, GROUP_DISSECT
    await ensure_consumer_group(self._redis, STREAM_FURNACE_CRASH, GROUP_DISSECT)
    while True:
        results = await self._redis.xreadgroup(
            groupname=GROUP_DISSECT,
            consumername=f"dissect-{job_id}",
            streams={STREAM_FURNACE_CRASH: ">"},
            count=1,
            block=1000,
        )
        if results:
            _, messages = results[0]
            for msg_id, raw_fields in messages:
                crash_event = {k: json.loads(v) if v.startswith(('{','[')) else v
                               for k, v in raw_fields.items()}
                await self._redis.xack(STREAM_FURNACE_CRASH, GROUP_DISSECT, msg_id)
                await dissect.handle_crash(crash_event)
        # Check if training is complete
        status = await self._redis.get(f"job:{job_id}:status")
        if status in ("ARBITER_RUNNING", "COMPLETE", "ESCALATED"):
            break

if self.use_dissect:
    dissect_task = asyncio.create_task(dissect_listener())
furnace_result = await furnace.run(script_path=script_path)
if self.use_dissect:
    dissect_task.cancel()

# After Furnace completes → Arbiter
arbiter = ArbiterAgent(job_id=job_id, redis_client=self._redis)
eval_report = await arbiter.run(checkpoint_path=furnace_result["checkpoint_path"])

if eval_report.decision == "pass":
    harbor = HarborAgent(job_id=job_id, redis_client=self._redis)
    endpoint_url = await harbor.run(
        checkpoint_path=furnace_result["checkpoint_path"],
        eval_report_path=f"outputs/{job_id}/eval_report_{job_id}.json",
    )
    return {"status": "complete", "endpoint_url": endpoint_url, **furnace_result}
```

---

### DAY 3-4 to 3-5: Full Pipeline Tests + Phase 3 Gate

```bash
# Run all tests
pytest tests/ -v --tb=short

# Manually test with House Prices (regression)
python3 -c "
import asyncio
from orchestrator.runtime import Orchestrator

async def main():
    orch = Orchestrator()
    await orch.connect()
    job_id = await orch.submit_job(
        problem_description='Predict house sale prices.',
        file_path='data/house_prices.csv',
        target_column='SalePrice',
    )
    result = await orch.run_job(
        job_id=job_id,
        problem_description='Predict house sale prices.',
        file_path='data/house_prices.csv',
        target_column='SalePrice',
    )
    print('Result:', result)

asyncio.run(main())
"
```

```bash
git add -A
git commit -m "[Phase3] ChromaDB memory + orchestrator hardening complete"
```

---

## PHASE 4 — FINAL RESEARCH BENCHMARK + PAPER
**Duration: 5 days | Goal: Real benchmark results, paper dataset, research-ready system**

---

### DAY 4-1: Verify Claude API + Benchmark Setup

**You should already have your API key from Phase 0. If not:**
1. Go to: https://console.anthropic.com → API Keys → Create Key
2. Set `ANTHROPIC_API_KEY` in `.env` if you haven't already

**Verify the API is still working (Claude Sonnet has been used since Phase 0):**
```bash
python3 -c "
import asyncio
from agents.llm_client import get_llm_response

async def test():
    result = await get_llm_response(
        system_prompt='Reply with JSON only.',
        user_message='Return: {\"status\": \"ok\", \"phase\": \"4\"}',
        job_id='test',
        agent_name='Phase4Check',
    )
    print(result['text'])

asyncio.run(test())
"
```
Expected: JSON with "ok" status.

Then run the full test suite to confirm everything is green before the benchmark:
```bash
pytest tests/ -v --tb=short
```
All tests must pass before proceeding to the benchmark.

---

### DAY 4-2 to 4-3: 50-Problem Benchmark

**YOU DO THIS — download 50 benchmark datasets:**

The benchmark uses standard Kaggle/UCI datasets. Here's the minimal list that covers
the 3 conditions (manual, no Dissect, with Dissect) with statistical power:

For a Mann-Whitney U test with effect size d=0.5 and power=0.8: need n=34 per condition.
Use 50 problems → more than sufficient.

Download from Kaggle (each takes 1 minute):
1. titanic → already have it
2. heart-disease (UCI): https://www.kaggle.com/datasets/redwankarimsony/heart-disease-ms → `data/heart_disease.csv`
3. breast-cancer (UCI): https://www.kaggle.com/datasets/uciml/breast-cancer-wisconsin-data → `data/breast_cancer.csv`
4. adult-income: https://www.kaggle.com/datasets/wenruliu/adult-income-dataset → `data/adult_income.csv`
5. bank-marketing: https://www.kaggle.com/datasets/janiobachmann/bank-marketing-dataset → `data/bank_marketing.csv`

(For the full 50, run the 5 datasets above with 10 different injected error types each.
This gives 50 "problems" — each with a different failure mode for Dissect to handle.)

**Create `research/benchmark/problems.json`:**
```json
[
  {"problem_id": "001", "description": "Predict Titanic survival", "file": "data/titanic.csv", "target": "Survived", "task_type": "classification"},
  {"problem_id": "002", "description": "Predict heart disease presence", "file": "data/heart_disease.csv", "target": "target", "task_type": "classification"},
  {"problem_id": "003", "description": "Classify breast cancer malignancy", "file": "data/breast_cancer.csv", "target": "diagnosis", "task_type": "classification"},
  {"problem_id": "004", "description": "Predict adult income above 50k", "file": "data/adult_income.csv", "target": "income", "task_type": "classification"},
  {"problem_id": "005", "description": "Predict bank customer subscription", "file": "data/bank_marketing.csv", "target": "deposit", "task_type": "classification"}
]
```

**Create `research/run_benchmark.py`:**
```python
"""
Run the 3-condition benchmark for the paper.
Condition A: manual (skip — recorded manually by Mohamed)
Condition B: Prometheus Swarm WITHOUT Dissect (disable Dissect in orchestrator)
Condition C: Prometheus Swarm WITH Dissect (full system)
"""

import asyncio
import json
import os
import time
from pathlib import Path

from orchestrator.runtime import Orchestrator

BENCHMARK_PATH = "research/benchmark/problems.json"
RESULTS_DIR = "research/benchmark/results"


async def run_condition(condition: str, use_dissect: bool) -> list[dict]:
    """Run all benchmark problems under one condition."""
    results = []
    problems = json.loads(Path(BENCHMARK_PATH).read_text())

    for problem in problems:
        print(f"\n[{condition}] Problem {problem['problem_id']}: {problem['description']}")
        start = time.time()

        orch = Orchestrator(use_dissect=use_dissect)
        await orch.connect()

        try:
            job_id = await orch.submit_job(
                problem_description=problem["description"],
                file_path=problem["file"],
                target_column=problem["target"],
            )
            result = await orch.run_job(
                job_id=job_id,
                problem_description=problem["description"],
                file_path=problem["file"],
                target_column=problem["target"],
            )
            duration = time.time() - start
            results.append({
                "problem_id": problem["problem_id"],
                "condition": condition,
                "job_id": job_id,
                "status": result.get("status", "complete"),
                "duration_seconds": duration,
                "best_val_metric": result.get("best_val_metric", 0),
                "total_crashes": result.get("total_crashes_recovered", 0),
                "human_interventions": 0 if result.get("status") != "escalated" else 1,
            })
        except Exception as e:
            results.append({
                "problem_id": problem["problem_id"],
                "condition": condition,
                "status": "failed",
                "error": str(e),
                "human_interventions": 1,
                "duration_seconds": time.time() - start,
            })

    return results


async def main():
    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)

    # Condition B: no Dissect
    print("\n=== CONDITION B: No Dissect ===")
    b_results = await run_condition("B_no_dissect", use_dissect=False)
    with open(f"{RESULTS_DIR}/condition_b.json", "w") as f:
        json.dump(b_results, f, indent=2)

    # Condition C: with Dissect
    print("\n=== CONDITION C: With Dissect ===")
    c_results = await run_condition("C_with_dissect", use_dissect=True)
    with open(f"{RESULTS_DIR}/condition_c.json", "w") as f:
        json.dump(c_results, f, indent=2)

    print("\n=== BENCHMARK COMPLETE ===")
    print(f"Results saved to {RESULTS_DIR}/")


if __name__ == "__main__":
    asyncio.run(main())
```

---

### DAY 4-4: Statistical Analysis

**Create `research/statistical_analysis.py`:**
```python
"""
Mann-Whitney U test comparing Condition B (no Dissect) vs Condition C (with Dissect).
Metric: human_interventions per job (0 = fully automatic, 1 = escalated).
"""

import json
import numpy as np
from scipy import stats
from pathlib import Path

def run_analysis():
    b = json.loads(Path("research/benchmark/results/condition_b.json").read_text())
    c = json.loads(Path("research/benchmark/results/condition_c.json").read_text())

    b_interventions = [r.get("human_interventions", 1) for r in b]
    c_interventions = [r.get("human_interventions", 1) for r in c]

    b_durations = [r.get("duration_seconds", 0) for r in b if r.get("status") != "failed"]
    c_durations = [r.get("duration_seconds", 0) for r in c if r.get("status") != "failed"]

    # Mann-Whitney U test on interventions
    stat, p_value = stats.mannwhitneyu(b_interventions, c_interventions, alternative="greater")

    print("=== RESEARCH RESULTS ===")
    print(f"\nCondition B (No Dissect): n={len(b_interventions)}")
    print(f"  Mean interventions: {np.mean(b_interventions):.3f}")
    print(f"  Median interventions: {np.median(b_interventions):.3f}")

    print(f"\nCondition C (With Dissect): n={len(c_interventions)}")
    print(f"  Mean interventions: {np.mean(c_interventions):.3f}")
    print(f"  Median interventions: {np.median(c_interventions):.3f}")

    print(f"\nMann-Whitney U statistic: {stat:.4f}")
    print(f"p-value: {p_value:.6f}")
    print(f"Result: {'SIGNIFICANT (p < 0.05)' if p_value < 0.05 else 'NOT significant'}")

    print(f"\nMean duration — B: {np.mean(b_durations):.1f}s | C: {np.mean(c_durations):.1f}s")

    reduction = (np.mean(b_interventions) - np.mean(c_interventions)) / max(np.mean(b_interventions), 0.001)
    print(f"Intervention reduction with Dissect: {reduction:.1%}")

if __name__ == "__main__":
    run_analysis()
```

**Run:**
```bash
python3 research/run_benchmark.py
python3 research/statistical_analysis.py
```

---

### DAY 4-5: Paper Scaffolding + Final Conversion

**Create `research/convert_jsonl_to_json.py`:**
```python
"""Convert patch_log.jsonl to JSON array for paper submission and ChromaDB ingestion."""
import json
from pathlib import Path

def convert():
    jsonl_path = Path("research/patch_log.jsonl")
    json_path = Path("research/patch_log_final.json")

    entries = []
    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    with open(json_path, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"Converted {len(entries)} entries → {json_path}")

if __name__ == "__main__":
    convert()
```

**Create `research/paper/draft.md` scaffold:**
```markdown
# Prometheus Swarm: Autonomous ML Pipeline Repair via Multi-Agent Error Recovery

**Authors:** Mohamed Mosad Ghonaim, Alamein International University, Nexora Lab

---

## Abstract
[TBD after results]

## 1. Introduction
ML training pipelines fail frequently. We present Prometheus Swarm and its Dissect agent...

## 2. Related Work
Auto2ML (Amazon, 2025), SWE-agent (Princeton, 2024), AlphaCode (Google DeepMind)...
Unlike Auto2ML which relies on brute-force hyperparameter sweeps, Prometheus uses
multi-agent semantic code modification to patch runtime execution errors directly.

## 3. System Design
### 3.1 Agent Architecture
### 3.2 The Dissect Agent
### 3.3 Error Taxonomy

## 4. Experimental Setup
### 4.1 Benchmark
### 4.2 Conditions
### 4.3 Metrics

## 5. Results
[TBD — paste from statistical_analysis.py output]

## 6. Discussion

## 7. Conclusion

## References
```

**Final test run:**
```bash
pytest tests/ -v --tb=short 2>&1 | tail -20
```

```bash
git add -A
git commit -m "[Phase4] Research experiment complete — paper-ready"
```

**Dataset Publication:**
Upload `research/patch_log_final.json` and the benchmark results to HuggingFace Datasets or Kaggle. This will serve as a permanent open-source artifact for the research community to build upon.

---

## COMPLETE PHASE SUMMARY

| Phase | Days | Goal | Gate |
|-------|------|------|------|
| Phase 0 | 5 | All infra running | Bus test green + all infra checks pass |
| Phase 1 | 6 | Scout + Forge + Furnace | Titanic E2E: val_metric > 0.82 |
| Phase 2 | 5 | Dissect + Arbiter + Harbor | 5/5 injected errors patched |
| Phase 3 | 5 | ChromaDB + hardening | All pytest green + 3 datasets E2E |
| Phase 4 | 5 | Final benchmark + paper | Benchmark results + statistical test |

**Total build: 26 working days. With research benchmark runtime, analysis, paper writing, and debugging overhead: ~10 weeks (45-50 calendar days).**

---

## WHAT CHANGES FROM RESEARCH TO PRODUCTION

The LLM layer stays the same (Claude Sonnet via Anthropic API from Phase 0).
What changes for a production deployment:

| Component | Research (local) | Production |
|-----------|-----------------|------------|
| Serving | Local Docker Compose | GKE (Kubernetes) |
| Redis | Single instance | Redis Cluster with replication |
| ChromaDB | Single node | ChromaDB cluster or Pinecone |
| Model format | ONNX | ONNX + TensorRT (GPU) |
| Auth | None | API key + rate limiting per tenant |
| Monitoring | Prometheus local | Grafana Cloud + PagerDuty |
| CI/CD | GitHub Actions | GitHub Actions + GKE deploy |
| Domain | localhost | Custom domain + TLS |
| API gateway | FastAPI directly | Nginx reverse proxy + rate limiter |

The application code and agent logic do not change between research and production.
All environment-specific configuration lives in `.env`.

---

## QUICK REFERENCE — DAILY STARTUP COMMANDS

```bash
# Start every session with these:
cd prometheus-swarm
.venv\Scripts\Activate.ps1       # Windows PowerShell
# source .venv/bin/activate      # Mac/Linux
docker compose up -d             # Start Redis + ChromaDB

# Verify everything is healthy:
docker exec prometheus-redis redis-cli ping   # → PONG
python3 -c "import urllib.request, json; d=json.loads(urllib.request.urlopen('http://localhost:8000/api/v1/heartbeat').read().decode()); print('ChromaDB', 'OK' if d.get('nanosecond heartbeat') else 'FAIL')"

# Run tests:
pytest tests/ -v --tb=short

# End every session:
docker compose stop              # Stop Redis + ChromaDB (data preserved in volumes)
```

---

*End of PLAN.md — Prometheus Swarm Build Plan*
*Owner: Mohamed Mosad Ghonaim | Nexora Lab | nexoraintel.com*
*Built on CLAUDE.md v1.2 — read CLAUDE.md before reading this file*

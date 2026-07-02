"""
BaseAgent ? common pattern inherited by all six agents.
Provides: LLM calling, Redis I/O, structured logging, retry logic.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from dotenv import load_dotenv

from agents.llm_client import get_llm_response
from memory.redis_client import RedisClient
from shared.metrics import record_agent_llm

# Claude Sonnet pricing per 1M tokens (as of 2026)
_COST_PER_1M_INPUT = 3.00
_COST_PER_1M_OUTPUT = 15.00

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
        """Return the agent name"""

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Return the system prompt"""

    @abstractmethod
    async def run(self) -> None:
        """Main agent loop"""

    async def call_llm(
        self,
        user_message: str,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        self.logger.info(f"[job={self.job_id}] LLM call")
        response = await get_llm_response(
            system_prompt=self.system_prompt,
            user_message=user_message,
            tools=tools,
            job_id=self.job_id,
            agent_name=self.agent_name,
        )
        await self._log_api_cost(response)
        return response

    async def _log_api_cost(self, response: dict[str, Any]) -> None:
        input_tokens = response.get("input_tokens", 0)
        output_tokens = response.get("output_tokens", 0)
        cost = (input_tokens / 1_000_000 * _COST_PER_1M_INPUT) + (
            output_tokens / 1_000_000 * _COST_PER_1M_OUTPUT
        )
        record_agent_llm(self.agent_name, self.job_id, input_tokens, output_tokens, cost)

        entry = json.dumps(
            {
                "agent": self.agent_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost": round(cost, 6),
            }
        )
        await self.redis.rpush(f"job:{self.job_id}:api_cost", entry)

        # Cumulative summary dict for quick retrieval
        existing = await self.redis.get_json(f"job:{self.job_id}:api_cost_summary") or {}
        existing["total_input_tokens"] = existing.get("total_input_tokens", 0) + input_tokens
        existing["total_output_tokens"] = existing.get("total_output_tokens", 0) + output_tokens
        existing["total_cost_usd"] = round(existing.get("total_cost_usd", 0) + cost, 6)
        existing["calls"] = existing.get("calls", 0) + 1
        await self.redis.set_json(
            f"job:{self.job_id}:api_cost_summary", existing, ttl_seconds=86400
        )

        self.logger.info(
            f"[job={self.job_id}] API cost ${cost:.6f} "
            f"({input_tokens} in / {output_tokens} out)"
        )

    async def get_total_api_cost(self) -> float:
        entries = []
        i = 0
        while True:
            entry = await self.redis.lindex(f"job:{self.job_id}:api_cost", i)
            if entry is None:
                break
            entries.append(json.loads(entry))
            i += 1
        return round(sum(e["cost"] for e in entries), 6)

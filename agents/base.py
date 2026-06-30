"""
BaseAgent ? common pattern inherited by all six agents.
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
        return response

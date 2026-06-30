"""
LLM Client ? Anthropic Claude Sonnet interface for all agents.
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
            raise RuntimeError(f"CRITICAL: Model {ANTHROPIC_MODEL} not found") from e
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"[{agent_name}][job={job_id}] LLM call failed attempt {attempt+1}")
            if attempt == max_retries - 1:
                raise RuntimeError(f"LLM failed after {max_retries} attempts") from e
            await asyncio.sleep(wait)

async def get_embedding(text: str) -> list[float]:
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    return model.encode(text).tolist()

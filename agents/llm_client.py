"""
LLM Client ? Anthropic Claude Sonnet interface for all agents.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import Any
from dotenv import load_dotenv, dotenv_values

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration precedence
# ---------------------------------------------------------------------------
# ``load_dotenv()`` deliberately does NOT override variables that already
# exist in the process environment.  That is normally convenient, but it means
# any ``ANTHROPIC_*`` variable exported by a shell profile or launcher script
# (a local proxy, a different model name, a different account's key) silently
# shadows the project's own ``.env``.  Prometheus's agents must run against
# the credentials and endpoint declared in ``.env``, so the settings that
# decide *which account and which API* a call reaches are resolved from the
# ``.env`` file FIRST, with the process environment only as a fallback.
#
# The resolved values are never logged or printed; the API key is used and
# discarded.


def _project_env_file() -> Path | None:
    """Locate the project ``.env`` by walking up from this module."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.is_file():
            return candidate
    return None


def _load_project_env() -> dict[str, str]:
    """Read ``.env`` directly, bypassing ``load_dotenv``'s no-override rule."""
    env_file = _project_env_file()
    if env_file is None:
        return {}
    try:
        return {k: v for k, v in dotenv_values(env_file).items() if v is not None and v != ""}
    except Exception as e:  # malformed .env must not break imports
        logger.warning("Could not parse %s: %s", env_file, e)
        return {}


_PROJECT_ENV = _load_project_env()


def _resolve(name: str, default: str | None = None) -> str | None:
    """Project ``.env`` value, else process environment, else ``default``."""
    value = _PROJECT_ENV.get(name)
    if value is None:
        value = os.getenv(name)
    return value if value is not None else default


ANTHROPIC_MODEL = _resolve("ANTHROPIC_MODEL", "claude-sonnet-4-6")
LLM_TIMEOUT = int(_resolve("LLM_TIMEOUT", "300") or "300")

# Anthropic's canonical endpoint.  Passed explicitly to every client
# construction so that an inherited ``ANTHROPIC_BASE_URL`` (e.g. a local
# proxy exported by a shell profile or launcher script) cannot redirect
# Prometheus's traffic away from the API the ``ANTHROPIC_API_KEY`` in
# ``.env`` actually belongs to.  The SDK only falls back to the env var
# when ``base_url`` is left as ``None``, so this must never be ``None``.
ANTHROPIC_BASE_URL = _resolve("PROMETHEUS_ANTHROPIC_BASE_URL", "https://api.anthropic.com")


async def get_llm_response(
    system_prompt: str,
    user_message: str,
    tools: list[dict] | None = None,
    job_id: str = "unknown",
    agent_name: str = "unknown",
    max_retries: int = 3,
) -> dict[str, Any]:
    import anthropic

    api_key = _resolve("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=ANTHROPIC_BASE_URL)
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
            async with asyncio.timeout(LLM_TIMEOUT):
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
            wait = 2**attempt
            logger.warning(
                f"[{agent_name}][job={job_id}] LLM call failed attempt {attempt + 1}: {e}"
            )
            if attempt == max_retries - 1:
                raise RuntimeError(f"LLM failed after {max_retries} attempts") from e
            await asyncio.sleep(wait)


async def get_llm_response_stream(
    system_prompt: str,
    user_message: str,
    tools: list[dict] | None = None,
    job_id: str = "unknown",
    agent_name: str = "unknown",
    max_retries: int = 3,
    *,
    redis_client=None,
    on_token: callable = None,
) -> dict[str, Any]:
    """Streaming variant of get_llm_response.

    Yields text tokens as they arrive from the API.  If ``redis_client``
    is provided, tokens are also published to the ``agent_thinking``
    stream so the Cockpit can render them live.

    Return value is the same dict as ``get_llm_response`` (full
    accumulated text + tool calls + token counts).

    When tools are used, the first text block is streamed but tool-use
    blocks are collected silently (only yielded at the end).
    """
    import anthropic

    api_key = _resolve("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    client = anthropic.AsyncAnthropic(api_key=api_key, base_url=ANTHROPIC_BASE_URL)

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

            accumulated_text = ""
            tool_calls = []
            input_tokens = 0
            output_tokens = 0

            async with asyncio.timeout(LLM_TIMEOUT):
                async with client.messages.stream(**kwargs) as stream:
                    async for text_delta in stream.text_stream:
                        accumulated_text += text_delta
                        if on_token:
                            on_token(text_delta)
                        if redis_client:
                            from bus.events import STREAM_AGENT_THINKING, THINKING_TOKEN
                            from bus.publisher import publish

                            try:
                                await publish(
                                    redis_client,
                                    STREAM_AGENT_THINKING,
                                    THINKING_TOKEN,
                                    {"agent": agent_name, "job_id": job_id, "text": text_delta},
                                )
                            except Exception:
                                logger.debug("Failed to publish thinking token", exc_info=True)

                    final_message = await stream.get_final_message()
                input_tokens = final_message.usage.input_tokens
                output_tokens = final_message.usage.output_tokens

                for block in final_message.content:
                    if block.type == "tool_use":
                        tool_calls.append({"name": block.name, "arguments": block.input})

                return {
                    "text": accumulated_text,
                    "tool_calls": tool_calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "raw": final_message.model_dump(),
                }

        except anthropic.NotFoundError as e:
            raise RuntimeError(f"CRITICAL: Model {ANTHROPIC_MODEL} not found") from e
        except Exception as e:
            wait = 2**attempt
            logger.warning(
                f"[{agent_name}][job={job_id}] LLM stream call failed attempt {attempt + 1}: {e}"
            )
            if attempt == max_retries - 1:
                raise RuntimeError(f"LLM stream failed after {max_retries} attempts") from e
            await asyncio.sleep(wait)


async def get_embedding(text: str) -> list[float]:
    from memory.embeddings import get_embedding_model

    model = get_embedding_model()
    if model is None:
        return []
    return model.encode(text).tolist()

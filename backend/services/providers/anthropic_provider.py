"""
Anthropic (Claude) LLM provider implementation.

Wraps the Anthropic SDK with rate-limit retry logic and serialization.
"""

import asyncio
import logging
from typing import AsyncGenerator

import anthropic

from config import DEFAULT_MODEL
from event_bus import broadcast
from services.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3

EVALUATE_CONDITION_TOOL = {
    "name": "evaluate_condition",
    "description": "Return the boolean result of evaluating a condition.",
    "input_schema": {
        "type": "object",
        "properties": {
            "result": {
                "type": "boolean",
                "description": "true if the condition is met, false otherwise",
            },
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of why the condition is true or false",
            },
        },
        "required": ["result", "reasoning"],
    },
}


class AnthropicProvider(LLMProvider):
    """Claude provider backed by the Anthropic SDK."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.async_client = anthropic.AsyncAnthropic(api_key=api_key)

    async def _retry_on_rate_limit(self, api_call, context: str = ""):
        """Retry an async API call on RateLimitError up to MAX_RETRIES times."""
        for attempt in range(MAX_RETRIES):
            try:
                return await api_call()
            except anthropic.RateLimitError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                retry_after = 30
                try:
                    retry_after = int(e.response.headers.get("retry-after", 30))
                except (ValueError, TypeError, AttributeError):
                    pass
                logger.warning(
                    "Rate limited (attempt %d/%d) on %s — retrying in %ds",
                    attempt + 1, MAX_RETRIES, context, retry_after,
                )
                broadcast("rate_limit", {
                    "retry_after": retry_after,
                    "attempt": attempt + 1,
                    "max_retries": MAX_RETRIES,
                    "context": context,
                })
                await asyncio.sleep(retry_after)

    @staticmethod
    def _serialize_block(block) -> dict:
        if block.type == "text":
            return {"type": "text", "text": block.text}
        elif block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
        return {"type": block.type}

    # ── LLMProvider interface ────────────────────────────────────────

    async def stream_chat(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> AsyncGenerator[dict, None]:
        model = model or DEFAULT_MODEL
        kwargs = {"model": model, "max_tokens": 8192, "messages": messages}
        if system_prompt:
            kwargs["system"] = system_prompt

        for attempt in range(MAX_RETRIES):
            try:
                async with self.async_client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "content_block_delta":
                            if hasattr(event.delta, "text"):
                                yield {"type": "text", "text": event.delta.text}

                    msg = await stream.get_final_message()
                    yield {
                        "type": "usage",
                        "model": model,
                        "input_tokens": msg.usage.input_tokens,
                        "output_tokens": msg.usage.output_tokens,
                    }
                    return  # success
            except anthropic.RateLimitError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                retry_after = 30
                try:
                    retry_after = int(e.response.headers.get("retry-after", 30))
                except (ValueError, TypeError, AttributeError):
                    pass
                logger.warning(
                    "Rate limited (attempt %d/%d) on stream_chat — retrying in %ds",
                    attempt + 1, MAX_RETRIES, retry_after,
                )
                broadcast("rate_limit", {
                    "retry_after": retry_after,
                    "attempt": attempt + 1,
                    "max_retries": MAX_RETRIES,
                    "context": "stream_chat",
                })
                await asyncio.sleep(retry_after)

    async def complete_chat(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> tuple[str, dict]:
        model = model or DEFAULT_MODEL
        kwargs = {"model": model, "max_tokens": 8192, "messages": messages}
        if system_prompt:
            kwargs["system"] = system_prompt

        msg = await self._retry_on_rate_limit(
            lambda: self.async_client.messages.create(**kwargs), "complete_chat"
        )
        text = ""
        for block in msg.content:
            if block.type == "text":
                text += block.text

        usage = {
            "model": model,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
        return text, usage

    async def call_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str = "",
        system_prompt: str = "",
        tool_choice: dict = None,
        max_tokens: int = 16384,
    ) -> dict:
        model = model or DEFAULT_MODEL
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools,
        }
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if system_prompt:
            kwargs["system"] = system_prompt

        msg = await self._retry_on_rate_limit(
            lambda: self.async_client.messages.create(**kwargs), "call_with_tools"
        )
        return {
            "content": [self._serialize_block(b) for b in msg.content],
            "stop_reason": msg.stop_reason,
            "usage": {
                "model": model,
                "input_tokens": msg.usage.input_tokens,
                "output_tokens": msg.usage.output_tokens,
            },
        }

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str = "",
        system_prompt: str = "",
        tool_choice: dict = None,
        max_tokens: int = 16384,
    ) -> AsyncGenerator[dict, None]:
        model = model or DEFAULT_MODEL
        kwargs = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "tools": tools,
        }
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if system_prompt:
            kwargs["system"] = system_prompt

        for attempt in range(MAX_RETRIES):
            try:
                async with self.async_client.messages.stream(**kwargs) as stream:
                    async for event in stream:
                        if event.type == "content_block_start":
                            block = event.content_block
                            if block.type == "tool_use":
                                yield {"type": "tool_start", "name": block.name}
                        elif event.type == "content_block_delta":
                            if hasattr(event.delta, "partial_json"):
                                yield {"type": "input_delta", "partial_json": event.delta.partial_json}
                        elif event.type == "content_block_stop":
                            pass  # tool_done emitted after final message

                    msg = await stream.get_final_message()
                    # Emit tool_done with the complete parsed input
                    for block in msg.content:
                        if block.type == "tool_use":
                            yield {"type": "tool_done", "input": block.input, "name": block.name}
                    yield {
                        "type": "usage",
                        "model": model,
                        "input_tokens": msg.usage.input_tokens,
                        "output_tokens": msg.usage.output_tokens,
                    }
                    return  # success
            except anthropic.RateLimitError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                retry_after = 30
                try:
                    retry_after = int(e.response.headers.get("retry-after", 30))
                except (ValueError, TypeError, AttributeError):
                    pass
                logger.warning(
                    "Rate limited (attempt %d/%d) on stream_with_tools — retrying in %ds",
                    attempt + 1, MAX_RETRIES, retry_after,
                )
                broadcast("rate_limit", {
                    "retry_after": retry_after,
                    "attempt": attempt + 1,
                    "max_retries": MAX_RETRIES,
                    "context": "stream_with_tools",
                })
                await asyncio.sleep(retry_after)

    async def evaluate_condition(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> tuple[bool, str, dict]:
        model = model or DEFAULT_MODEL
        kwargs = {
            "model": model,
            "max_tokens": 256,
            "messages": messages,
            "tools": [EVALUATE_CONDITION_TOOL],
            "tool_choice": {"type": "tool", "name": "evaluate_condition"},
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        msg = await self._retry_on_rate_limit(
            lambda: self.async_client.messages.create(**kwargs), "evaluate_condition"
        )

        result = False
        reasoning = ""
        for block in msg.content:
            if block.type == "tool_use" and block.name == "evaluate_condition":
                result = bool(block.input.get("result", False))
                reasoning = block.input.get("reasoning", "")
                break

        usage = {
            "model": model,
            "input_tokens": msg.usage.input_tokens,
            "output_tokens": msg.usage.output_tokens,
        }
        return result, reasoning, usage

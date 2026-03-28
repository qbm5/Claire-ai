"""
OpenAI LLM provider implementation.

Translates between Anthropic-format messages (used by all consumers)
and OpenAI API format, so no changes are needed to agent_service,
pipeline_engine, chatbot_routes, or tool_routes.
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

import openai

from config import DEFAULT_MODEL
from event_bus import broadcast
from services.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


EVALUATE_CONDITION_TOOL_OPENAI = {
    "type": "function",
    "function": {
        "name": "evaluate_condition",
        "description": "Return the boolean result of evaluating a condition.",
        "parameters": {
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
    },
}


# ── Translation helpers ──────────────────────────────────────────────


def _anthropic_messages_to_openai(
    messages: list[dict], system_prompt: str = ""
) -> list[dict]:
    """Convert Anthropic-format messages to OpenAI-format messages."""
    out: list[dict] = []

    if system_prompt:
        out.append({"role": "system", "content": system_prompt})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        # Simple string content
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        # Content is a list of blocks (Anthropic style)
        if isinstance(content, list):
            # Check if this message contains tool_use or tool_result blocks
            has_tool_use = any(
                isinstance(b, dict) and b.get("type") == "tool_use" for b in content
            )
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            )

            if role == "assistant" and has_tool_use:
                # Translate assistant tool_use blocks to OpenAI tool_calls
                text_parts = []
                tool_calls = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {})),
                            },
                        })
                assistant_msg: dict = {"role": "assistant"}
                combined_text = "".join(text_parts)
                if combined_text:
                    assistant_msg["content"] = combined_text
                else:
                    assistant_msg["content"] = None
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                out.append(assistant_msg)

            elif role == "user" and has_tool_result:
                # Translate user tool_result blocks to OpenAI tool messages
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_result":
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, list):
                            # Extract text from content blocks
                            parts = []
                            for sub in tool_content:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    parts.append(sub.get("text", ""))
                            tool_content = "\n".join(parts)
                        out.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": str(tool_content),
                        })
                    elif block.get("type") == "text":
                        out.append({"role": "user", "content": block.get("text", "")})
            else:
                # Regular content blocks — combine text
                text_parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                out.append({"role": role, "content": "".join(text_parts)})
        else:
            out.append({"role": role, "content": str(content) if content else ""})

    return out


def _fix_schema(schema: dict) -> dict:
    """Recursively fix JSON Schema for OpenAI: arrays must have 'items'."""
    if not isinstance(schema, dict):
        return schema
    schema = dict(schema)  # shallow copy
    if schema.get("type") == "array" and "items" not in schema:
        schema["items"] = {"type": "string"}
    if "properties" in schema and isinstance(schema["properties"], dict):
        schema["properties"] = {
            k: _fix_schema(v) for k, v in schema["properties"].items()
        }
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = _fix_schema(schema["items"])
    return schema


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function format."""
    out = []
    for tool in tools:
        out.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": _fix_schema(tool.get("input_schema", {})),
            },
        })
    return out


def _openai_choice_to_anthropic_content(choice) -> list[dict]:
    """Convert an OpenAI choice to Anthropic-format content blocks."""
    blocks: list[dict] = []
    message = choice.message

    if message.content:
        blocks.append({"type": "text", "text": message.content})

    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })

    if not blocks:
        blocks.append({"type": "text", "text": ""})

    return blocks


def _openai_finish_reason_to_anthropic(finish_reason: str | None) -> str:
    """Map OpenAI finish_reason to Anthropic stop_reason."""
    if finish_reason == "tool_calls":
        return "tool_use"
    if finish_reason == "length":
        return "max_tokens"
    return "end_turn"


def _build_token_kwargs(max_tokens: int = 8192) -> dict:
    """Return token limit kwarg. All current OpenAI models use max_completion_tokens."""
    return {"max_completion_tokens": max_tokens}


class OpenAIProvider(LLMProvider):
    """OpenAI provider that translates Anthropic-format messages to/from OpenAI API."""

    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)
        logger.info("[OpenAI] Provider initialized")

    async def _retry_on_rate_limit(self, api_call, context: str = ""):
        """Retry an async API call on RateLimitError up to MAX_RETRIES times."""
        for attempt in range(MAX_RETRIES):
            try:
                return await api_call()
            except openai.RateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                retry_after = 30
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

    # ── LLMProvider interface ────────────────────────────────────────

    async def stream_chat(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> AsyncGenerator[dict, None]:
        model = model or DEFAULT_MODEL
        oai_messages = _anthropic_messages_to_openai(messages, system_prompt)

        logger.info("[OpenAI] stream_chat called — model=%s, %d messages", model, len(oai_messages))

        kwargs = {
            "model": model,
            "messages": oai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **_build_token_kwargs(),
        }

        for attempt in range(MAX_RETRIES):
            try:
                logger.info("[OpenAI] stream_chat sending request (attempt %d)...", attempt + 1)
                stream = await self.client.chat.completions.create(**kwargs)
                async for chunk in stream:
                    if chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            yield {"type": "text", "text": delta.content}
                    if chunk.usage:
                        yield {
                            "type": "usage",
                            "model": model,
                            "input_tokens": chunk.usage.prompt_tokens or 0,
                            "output_tokens": chunk.usage.completion_tokens or 0,
                        }
                logger.info("[OpenAI] stream_chat completed successfully")
                return  # success
            except openai.RateLimitError:
                if attempt == MAX_RETRIES - 1:
                    raise
                retry_after = 30
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
        oai_messages = _anthropic_messages_to_openai(messages, system_prompt)

        logger.info("[OpenAI] complete_chat called — model=%s, %d messages", model, len(oai_messages))

        kwargs = {
            "model": model,
            "messages": oai_messages,
            **_build_token_kwargs(),
        }

        response = await self._retry_on_rate_limit(
            lambda: self.client.chat.completions.create(**kwargs), "complete_chat"
        )

        text = response.choices[0].message.content or ""
        usage = {
            "model": model,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        logger.info("[OpenAI] complete_chat done — %d chars, %d in / %d out tokens",
                     len(text), usage["input_tokens"], usage["output_tokens"])
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
        oai_messages = _anthropic_messages_to_openai(messages, system_prompt)
        oai_tools = _anthropic_tools_to_openai(tools)

        logger.info("[OpenAI] call_with_tools — model=%s, %d messages, %d tools", model, len(oai_messages), len(oai_tools))
        logger.debug("[OpenAI] call_with_tools messages: %s", json.dumps(oai_messages, default=str)[:2000])
        logger.debug("[OpenAI] call_with_tools tools: %s", json.dumps(oai_tools, default=str)[:1000])

        kwargs = {
            "model": model,
            "messages": oai_messages,
            "tools": oai_tools,
            **_build_token_kwargs(),
        }
        if tool_choice:
            # Translate Anthropic format to OpenAI format
            if tool_choice.get("type") == "tool" and "name" in tool_choice:
                kwargs["tool_choice"] = {"type": "function", "function": {"name": tool_choice["name"]}}
            else:
                kwargs["tool_choice"] = tool_choice

        logger.info("[OpenAI] call_with_tools sending request...")
        response = await self._retry_on_rate_limit(
            lambda: self.client.chat.completions.create(**kwargs), "call_with_tools"
        )

        choice = response.choices[0]
        finish = choice.finish_reason
        mapped_stop = _openai_finish_reason_to_anthropic(finish)
        content = _openai_choice_to_anthropic_content(choice)

        tool_names = [b["name"] for b in content if b.get("type") == "tool_use"]
        logger.info("[OpenAI] call_with_tools done — finish_reason=%s (mapped=%s), tool_calls=%s, %d in / %d out tokens",
                     finish, mapped_stop, tool_names or "none",
                     response.usage.prompt_tokens if response.usage else 0,
                     response.usage.completion_tokens if response.usage else 0)

        return {
            "content": content,
            "stop_reason": mapped_stop,
            "usage": {
                "model": model,
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }

    async def evaluate_condition(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> tuple[bool, str, dict]:
        model = model or DEFAULT_MODEL
        oai_messages = _anthropic_messages_to_openai(messages, system_prompt)

        kwargs = {
            "model": model,
            "messages": oai_messages,
            "tools": [EVALUATE_CONDITION_TOOL_OPENAI],
            "tool_choice": {"type": "function", "function": {"name": "evaluate_condition"}},
            **_build_token_kwargs(max_tokens=256),
        }

        response = await self._retry_on_rate_limit(
            lambda: self.client.chat.completions.create(**kwargs), "evaluate_condition"
        )

        result = False
        reasoning = ""
        choice = response.choices[0]
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                if tc.function.name == "evaluate_condition":
                    try:
                        args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    result = bool(args.get("result", False))
                    reasoning = args.get("reasoning", "")
                    break

        usage = {
            "model": model,
            "input_tokens": response.usage.prompt_tokens if response.usage else 0,
            "output_tokens": response.usage.completion_tokens if response.usage else 0,
        }
        return result, reasoning, usage

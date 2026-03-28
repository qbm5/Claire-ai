"""
Abstract LLM provider interface.

All LLM providers (Anthropic, OpenAI, Gemini, etc.) implement this ABC.
Callers interact through the registry in services.llm, never directly.
"""

from abc import ABC, abstractmethod
from typing import AsyncGenerator


class LLMProvider(ABC):
    """Base class every LLM provider must implement."""

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> AsyncGenerator[dict, None]:
        """Stream a chat response. Yields dicts with 'type' and 'text' or 'usage'."""
        ...

    @abstractmethod
    async def complete_chat(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> tuple[str, dict]:
        """Non-streaming chat. Returns (text, usage_dict)."""
        ...

    @abstractmethod
    async def call_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str = "",
        system_prompt: str = "",
        tool_choice: dict = None,
        max_tokens: int = 16384,
    ) -> dict:
        """Single-turn tool_use call. Returns dict with 'content', 'stop_reason', 'usage'."""
        ...

    async def stream_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        model: str = "",
        system_prompt: str = "",
        tool_choice: dict = None,
        max_tokens: int = 16384,
    ) -> AsyncGenerator[dict, None]:
        """Stream a tool_use call. Yields event dicts:
        - {"type": "tool_start", "name": str}
        - {"type": "input_delta", "partial_json": str}
        - {"type": "tool_done", "input": dict, "name": str}
        - {"type": "usage", "model": str, "input_tokens": int, "output_tokens": int}
        Default implementation falls back to non-streaming call_with_tools.
        """
        result = await self.call_with_tools(messages, tools, model, system_prompt, tool_choice=tool_choice, max_tokens=max_tokens)
        for block in result.get("content", []):
            if block.get("type") == "tool_use":
                yield {"type": "tool_start", "name": block.get("name", "")}
                import json
                yield {"type": "input_delta", "partial_json": json.dumps(block.get("input", {}), indent=2)}
                yield {"type": "tool_done", "input": block.get("input", {}), "name": block.get("name", "")}
        yield {"type": "usage", **result.get("usage", {})}

    @abstractmethod
    async def evaluate_condition(
        self,
        messages: list[dict],
        model: str = "",
        system_prompt: str = "",
    ) -> tuple[bool, str, dict]:
        """Evaluate a boolean condition. Returns (result, reasoning, usage)."""
        ...

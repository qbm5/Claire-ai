"""
Local LLM provider implementation.

Connects to any local OpenAI-compatible server (Ollama, vLLM, LM Studio, llama.cpp)
by extending OpenAIProvider with a user-configurable base URL.

Model IDs use a 'local-' prefix for routing (e.g., 'local-llama3.2').
The prefix is stripped before sending to the server.
"""

import logging
from typing import AsyncGenerator

import openai

from services.providers.openai_provider import OpenAIProvider

logger = logging.getLogger(__name__)


class LocalLLMProvider(OpenAIProvider):
    """Local LLM provider — OpenAI-compatible API at a user-configured URL."""

    def __init__(self, base_url: str, api_key: str = "local"):
        self.client = openai.AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        logger.info("[LocalLLM] Provider initialized with base_url=%s", base_url)

    @staticmethod
    def _strip_prefix(model: str) -> str:
        """Remove 'local-' routing prefix before sending to the local server."""
        return model[6:] if model.startswith("local-") else model

    async def stream_chat(self, messages, model="", system_prompt="") -> AsyncGenerator[dict, None]:
        async for chunk in super().stream_chat(messages, self._strip_prefix(model), system_prompt):
            yield chunk

    async def complete_chat(self, messages, model="", system_prompt="") -> tuple[str, dict]:
        return await super().complete_chat(messages, self._strip_prefix(model), system_prompt)

    async def call_with_tools(self, messages, tools, model="", system_prompt="", tool_choice=None, max_tokens=16384) -> dict:
        return await super().call_with_tools(messages, tools, self._strip_prefix(model), system_prompt, tool_choice=tool_choice, max_tokens=max_tokens)

    async def evaluate_condition(self, messages, model="", system_prompt="") -> tuple[bool, str, dict]:
        return await super().evaluate_condition(messages, self._strip_prefix(model), system_prompt)

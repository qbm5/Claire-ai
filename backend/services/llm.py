"""
LLM provider registry and convenience functions.

Callers import from here instead of a specific provider module.
On load, auto-registers AnthropicProvider if ANTHROPIC_API_KEY is set.
"""

import logging
from typing import AsyncGenerator

from services.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

# ── Registry ─────────────────────────────────────────────────────

_registry: dict[str, LLMProvider] = {}


def register_provider(name: str, provider: LLMProvider):
    _registry[name] = provider
    logger.info("Registered LLM provider: %s", name)


def get_provider(name: str) -> LLMProvider:
    if name not in _registry:
        raise KeyError(f"LLM provider '{name}' not registered")
    return _registry[name]


_PROVIDER_PREFIXES = [
    (("gpt-", "o1-", "o3-", "o4-"), "openai", "OpenAI", "OPENAI_API_KEY"),
    (("gemini-",), "google", "Google", "GOOGLE_API_KEY"),
    (("grok-",), "xai", "xAI", "XAI_API_KEY"),
    (("local-",), "local", "Local LLM", "LOCAL_LLM_URL"),
]


def get_provider_for_model(model_id: str) -> LLMProvider:
    """Resolve a model ID to its provider via prefix matching."""
    if model_id:
        for prefixes, key, name, setting in _PROVIDER_PREFIXES:
            if model_id.startswith(prefixes):
                if key in _registry:
                    return _registry[key]
                raise RuntimeError(f"{name} provider not registered. Set {setting} in settings.")
    if "anthropic" in _registry:
        return _registry["anthropic"]
    # Fallback: return the first registered provider
    if _registry:
        return next(iter(_registry.values()))
    raise RuntimeError("No LLM providers registered. Check your API keys.")


# ── Convenience functions (match old claude_llm signatures) ──────


async def chat_stream(
    messages: list[dict],
    model: str = "",
    system_prompt: str = "",
) -> AsyncGenerator[dict, None]:
    provider = get_provider_for_model(model)
    async for chunk in provider.stream_chat(messages, model, system_prompt):
        yield chunk


async def chat_complete(
    messages: list[dict],
    model: str = "",
    system_prompt: str = "",
) -> tuple[str, dict]:
    provider = get_provider_for_model(model)
    return await provider.complete_chat(messages, model, system_prompt)


async def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str = "",
    system_prompt: str = "",
    tool_choice: dict = None,
    max_tokens: int = 16384,
) -> dict:
    provider = get_provider_for_model(model)
    return await provider.call_with_tools(messages, tools, model, system_prompt, tool_choice=tool_choice, max_tokens=max_tokens)


async def chat_stream_with_tools(
    messages: list[dict],
    tools: list[dict],
    model: str = "",
    system_prompt: str = "",
    tool_choice: dict = None,
    max_tokens: int = 16384,
) -> AsyncGenerator[dict, None]:
    provider = get_provider_for_model(model)
    async for event in provider.stream_with_tools(messages, tools, model, system_prompt, tool_choice=tool_choice, max_tokens=max_tokens):
        yield event


async def evaluate_condition(
    messages: list[dict],
    model: str = "",
    system_prompt: str = "",
) -> tuple[bool, str, dict]:
    provider = get_provider_for_model(model)
    return await provider.evaluate_condition(messages, model, system_prompt)


# ── Auto-register providers on import ────────────────────────────

def _auto_register():
    from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GOOGLE_API_KEY, XAI_API_KEY, LOCAL_LLM_URL, LOCAL_LLM_API_KEY
    if ANTHROPIC_API_KEY:
        from services.providers.anthropic_provider import AnthropicProvider
        register_provider("anthropic", AnthropicProvider(ANTHROPIC_API_KEY))
    if OPENAI_API_KEY:
        from services.providers.openai_provider import OpenAIProvider
        register_provider("openai", OpenAIProvider(OPENAI_API_KEY))
    if GOOGLE_API_KEY:
        from services.providers.gemini_provider import GeminiProvider
        register_provider("google", GeminiProvider(GOOGLE_API_KEY))
    if XAI_API_KEY:
        from services.providers.grok_provider import GrokProvider
        register_provider("xai", GrokProvider(XAI_API_KEY))
    if LOCAL_LLM_URL:
        from services.providers.local_provider import LocalLLMProvider
        register_provider("local", LocalLLMProvider(LOCAL_LLM_URL, LOCAL_LLM_API_KEY))


def re_register_providers():
    """Re-register all providers with current config values. Called after settings save."""
    _registry.clear()
    _auto_register()


_auto_register()

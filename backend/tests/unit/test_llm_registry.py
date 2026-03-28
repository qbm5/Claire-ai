"""Tests for services/llm.py registry logic."""

import pytest
from unittest.mock import MagicMock
from services.llm import register_provider, get_provider, get_provider_for_model, _registry
from services.llm_provider import LLMProvider


@pytest.fixture(autouse=True)
def cleanup():
    """Save and restore registry between tests."""
    saved = dict(_registry)
    _registry.clear()
    yield
    _registry.clear()
    _registry.update(saved)


class MockProvider(LLMProvider):
    async def stream_chat(self, messages, model="", system_prompt=""):
        yield {"type": "text", "text": "mock"}

    async def complete_chat(self, messages, model="", system_prompt=""):
        return "mock", {}

    async def call_with_tools(self, messages, tools, model="", system_prompt="", tool_choice=None):
        return {"content": [], "stop_reason": "end_turn", "usage": {}}

    async def evaluate_condition(self, messages, model="", system_prompt=""):
        return True, "mocked", {}


class TestRegistry:
    def test_register_and_get(self):
        mock = MockProvider()
        register_provider("test", mock)
        assert get_provider("test") is mock

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError):
            get_provider("nonexistent")


class TestGetProviderForModel:
    def test_gpt_model_routes_to_openai(self):
        mock_openai = MockProvider()
        register_provider("openai", mock_openai)
        register_provider("anthropic", MockProvider())
        assert get_provider_for_model("gpt-5.1") is mock_openai

    def test_claude_model_routes_to_anthropic(self):
        mock_anthropic = MockProvider()
        register_provider("anthropic", mock_anthropic)
        assert get_provider_for_model("claude-sonnet-4-6") is mock_anthropic

    def test_unknown_model_falls_back_to_anthropic(self):
        mock_anthropic = MockProvider()
        register_provider("anthropic", mock_anthropic)
        assert get_provider_for_model("unknown-model") is mock_anthropic

    def test_no_providers_raises(self):
        with pytest.raises(RuntimeError):
            get_provider_for_model("any-model")

    def test_o1_model_routes_to_openai(self):
        mock_openai = MockProvider()
        register_provider("openai", mock_openai)
        register_provider("anthropic", MockProvider())
        assert get_provider_for_model("o1-preview") is mock_openai

    def test_gpt_without_openai_raises(self):
        register_provider("anthropic", MockProvider())
        with pytest.raises(RuntimeError, match="OpenAI provider not registered"):
            get_provider_for_model("gpt-5.1")

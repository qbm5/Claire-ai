"""Tests for LLM provider implementations."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from types import SimpleNamespace

from services.llm_provider import LLMProvider


# ── Mock helpers ─────────────────────────────────────────────────────


def _make_anthropic_message(text="Hello", input_tokens=10, output_tokens=5, content=None):
    """Create a mock Anthropic message response."""
    if content is None:
        content = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(
        content=content,
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason="end_turn",
    )


def _make_openai_message(text="Hello", input_tokens=10, output_tokens=5, tool_calls=None):
    """Create a mock OpenAI ChatCompletion response."""
    choice = SimpleNamespace(
        message=SimpleNamespace(
            role="assistant",
            content=text,
            tool_calls=tool_calls,
        ),
        finish_reason="stop",
    )
    return SimpleNamespace(
        choices=[choice],
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        ),
        model="gpt-4o",
    )


# ── Anthropic Provider ───────────────────────────────────────────────


class TestAnthropicProvider:

    @pytest.fixture()
    def provider(self):
        with patch("services.providers.anthropic_provider.anthropic") as mock_anthropic:
            mock_anthropic.Anthropic = MagicMock()
            mock_anthropic.AsyncAnthropic = MagicMock()
            mock_anthropic.RateLimitError = type("RateLimitError", (Exception,), {})
            from services.providers.anthropic_provider import AnthropicProvider
            p = AnthropicProvider("test-key")
            p.async_client = MagicMock()
            return p

    @pytest.mark.asyncio
    async def test_complete_chat(self, provider):
        msg = _make_anthropic_message("Test response", 20, 10)
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        text, usage = await provider.complete_chat(
            [{"role": "user", "content": "Hello"}], "claude-sonnet-4-6", "Be helpful"
        )
        assert text == "Test response"
        assert usage["input_tokens"] == 20
        assert usage["output_tokens"] == 10
        assert usage["model"] == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_complete_chat_no_system_prompt(self, provider):
        msg = _make_anthropic_message("response")
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        text, _ = await provider.complete_chat(
            [{"role": "user", "content": "Hi"}], "claude-sonnet-4-6"
        )
        assert text == "response"
        # No system kwarg should be passed
        call_kwargs = provider.async_client.messages.create.call_args.kwargs
        assert "system" not in call_kwargs

    @pytest.mark.asyncio
    async def test_call_with_tools(self, provider):
        tool_block = SimpleNamespace(
            type="tool_use", id="tool-1", name="search", input={"q": "test"}
        )
        msg = _make_anthropic_message(content=[tool_block], input_tokens=15, output_tokens=8)
        msg.stop_reason = "tool_use"
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        result = await provider.call_with_tools(
            [{"role": "user", "content": "Search for info"}],
            [{"name": "search", "input_schema": {}}],
            "claude-sonnet-4-6",
        )
        assert result["stop_reason"] == "tool_use"
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "tool_use"
        assert result["content"][0]["name"] == "search"
        assert result["content"][0]["input"] == {"q": "test"}

    @pytest.mark.asyncio
    async def test_call_with_tool_choice(self, provider):
        msg = _make_anthropic_message(content=[
            SimpleNamespace(type="tool_use", id="t1", name="search", input={})
        ])
        msg.stop_reason = "tool_use"
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        await provider.call_with_tools(
            [{"role": "user", "content": "x"}],
            [{"name": "search", "input_schema": {}}],
            "claude-sonnet-4-6",
            tool_choice={"type": "tool", "name": "search"},
        )
        call_kwargs = provider.async_client.messages.create.call_args.kwargs
        assert call_kwargs["tool_choice"] == {"type": "tool", "name": "search"}

    @pytest.mark.asyncio
    async def test_evaluate_condition_true(self, provider):
        tool_block = SimpleNamespace(
            type="tool_use", name="evaluate_condition",
            input={"result": True, "reasoning": "Condition met"}
        )
        msg = _make_anthropic_message(content=[tool_block])
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        result, reasoning, usage = await provider.evaluate_condition(
            [{"role": "user", "content": "Is 2 > 1?"}]
        )
        assert result is True
        assert reasoning == "Condition met"
        assert "input_tokens" in usage

    @pytest.mark.asyncio
    async def test_evaluate_condition_false(self, provider):
        tool_block = SimpleNamespace(
            type="tool_use", name="evaluate_condition",
            input={"result": False, "reasoning": "Not met"}
        )
        msg = _make_anthropic_message(content=[tool_block])
        provider.async_client.messages.create = AsyncMock(return_value=msg)

        result, reasoning, _ = await provider.evaluate_condition(
            [{"role": "user", "content": "Is 1 > 2?"}]
        )
        assert result is False
        assert reasoning == "Not met"

    @pytest.mark.asyncio
    async def test_serialize_text_block(self, provider):
        from services.providers.anthropic_provider import AnthropicProvider
        block = SimpleNamespace(type="text", text="hello")
        assert AnthropicProvider._serialize_block(block) == {"type": "text", "text": "hello"}

    @pytest.mark.asyncio
    async def test_serialize_tool_use_block(self, provider):
        from services.providers.anthropic_provider import AnthropicProvider
        block = SimpleNamespace(type="tool_use", id="t1", name="search", input={"q": "x"})
        result = AnthropicProvider._serialize_block(block)
        assert result["type"] == "tool_use"
        assert result["name"] == "search"
        assert result["id"] == "t1"

    @pytest.mark.asyncio
    async def test_serialize_unknown_block(self, provider):
        from services.providers.anthropic_provider import AnthropicProvider
        block = SimpleNamespace(type="thinking")
        assert AnthropicProvider._serialize_block(block) == {"type": "thinking"}

    @pytest.mark.asyncio
    async def test_stream_chat(self, provider):
        """Stream chat yields text chunks and usage."""
        # Mock the stream context manager
        event1 = SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="Hello "))
        event2 = SimpleNamespace(type="content_block_delta", delta=SimpleNamespace(text="world"))
        final_msg = _make_anthropic_message(input_tokens=10, output_tokens=5)

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.get_final_message = AsyncMock(return_value=final_msg)

        async def mock_iter():
            yield event1
            yield event2

        mock_stream.__aiter__ = lambda self: mock_iter()

        provider.async_client.messages.stream = MagicMock(return_value=mock_stream)

        chunks = []
        async for chunk in provider.stream_chat(
            [{"role": "user", "content": "Hi"}], "claude-sonnet-4-6"
        ):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.get("type") == "text"]
        assert len(text_chunks) == 2
        assert text_chunks[0]["text"] == "Hello "
        usage_chunks = [c for c in chunks if c.get("type") == "usage"]
        assert len(usage_chunks) == 1
        assert usage_chunks[0]["input_tokens"] == 10

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self, provider):
        """Rate limit retry logic works correctly."""
        import anthropic as real_anthropic

        # Create a proper exception-like RateLimitError mock
        call_count = 0

        async def failing_then_succeeding():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                err = real_anthropic.RateLimitError(
                    message="rate limited",
                    response=MagicMock(headers={"retry-after": "1"}),
                    body=None,
                )
                raise err
            return _make_anthropic_message("Success after retry")

        with patch("asyncio.sleep", new_callable=AsyncMock), \
             patch("services.providers.anthropic_provider.broadcast"):
            result = await provider._retry_on_rate_limit(failing_then_succeeding, "test")

        assert result.content[0].text == "Success after retry"
        assert call_count == 2


# ── OpenAI Provider ──────────────────────────────────────────────────


class TestOpenAIProvider:

    @pytest.fixture()
    def provider(self):
        with patch("services.providers.openai_provider.openai") as mock_openai:
            mock_openai.AsyncOpenAI = MagicMock()
            mock_openai.RateLimitError = type("RateLimitError", (Exception,), {})
            from services.providers.openai_provider import OpenAIProvider
            p = OpenAIProvider("test-key")
            p.client = MagicMock()
            return p

    @pytest.mark.asyncio
    async def test_complete_chat(self, provider):
        msg = _make_openai_message("OpenAI response", 20, 10)
        provider.client.chat.completions.create = AsyncMock(return_value=msg)

        text, usage = await provider.complete_chat(
            [{"role": "user", "content": "Hello"}], "gpt-4o"
        )
        assert text == "OpenAI response"
        assert usage["input_tokens"] == 20
        assert usage["output_tokens"] == 10

    @pytest.mark.asyncio
    async def test_call_with_tools(self, provider):
        tool_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(
                name="search",
                arguments='{"q": "test"}',
            ),
            type="function",
        )
        msg = _make_openai_message(text=None, tool_calls=[tool_call])
        msg.choices[0].finish_reason = "tool_calls"
        provider.client.chat.completions.create = AsyncMock(return_value=msg)

        # OpenAI tools use different format
        result = await provider.call_with_tools(
            [{"role": "user", "content": "Search"}],
            [{"name": "search", "description": "Search", "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}}}],
            "gpt-4o",
        )
        assert result["stop_reason"] == "tool_use"
        assert len(result["content"]) >= 1
        tool_use = [c for c in result["content"] if c.get("type") == "tool_use"]
        assert len(tool_use) == 1
        assert tool_use[0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_evaluate_condition(self, provider):
        tool_call = SimpleNamespace(
            id="c1",
            function=SimpleNamespace(
                name="evaluate_condition",
                arguments='{"result": true, "reasoning": "Yes"}',
            ),
            type="function",
        )
        msg = _make_openai_message(text=None, tool_calls=[tool_call])
        msg.choices[0].finish_reason = "tool_calls"
        provider.client.chat.completions.create = AsyncMock(return_value=msg)

        result, reasoning, usage = await provider.evaluate_condition(
            [{"role": "user", "content": "Is sky blue?"}], "gpt-4o"
        )
        assert result is True
        assert reasoning == "Yes"


# ── OpenAI Message Translation ──────────────────────────────────────


class TestOpenAIMessageTranslation:

    def test_simple_text_messages(self):
        from services.providers.openai_provider import _anthropic_messages_to_openai
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _anthropic_messages_to_openai(messages)
        assert len(result) == 2
        assert result[0] == {"role": "user", "content": "Hello"}
        assert result[1] == {"role": "assistant", "content": "Hi there"}

    def test_system_prompt_prepended(self):
        from services.providers.openai_provider import _anthropic_messages_to_openai
        messages = [{"role": "user", "content": "Hello"}]
        result = _anthropic_messages_to_openai(messages, "You are helpful")
        assert result[0] == {"role": "system", "content": "You are helpful"}
        assert result[1] == {"role": "user", "content": "Hello"}

    def test_tool_use_blocks_translated(self):
        from services.providers.openai_provider import _anthropic_messages_to_openai
        messages = [
            {"role": "assistant", "content": [
                {"type": "text", "text": "Let me search"},
                {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "test"}},
            ]},
        ]
        result = _anthropic_messages_to_openai(messages)
        assert len(result) >= 1
        # Should have tool_calls in assistant message
        assert result[0]["role"] == "assistant"

    def test_tool_result_blocks_translated(self):
        from services.providers.openai_provider import _anthropic_messages_to_openai
        messages = [
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "Found result"},
            ]},
        ]
        result = _anthropic_messages_to_openai(messages)
        assert len(result) == 1
        assert result[0]["role"] == "tool"


# ── OpenAI Tool Schema Translation ──────────────────────────────────


class TestOpenAIToolTranslation:

    def test_translates_anthropic_schema_to_openai(self):
        from services.providers.openai_provider import _anthropic_tools_to_openai
        tools = [
            {
                "name": "search",
                "description": "Search the web",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
        ]
        result = _anthropic_tools_to_openai(tools)
        assert len(result) == 1
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "search"
        assert result[0]["function"]["parameters"]["properties"]["query"]["type"] == "string"

    def test_empty_tools(self):
        from services.providers.openai_provider import _anthropic_tools_to_openai
        assert _anthropic_tools_to_openai([]) == []


# ── LLMProvider base class ──────────────────────────────────────────


class TestLLMProviderBase:

    @pytest.mark.asyncio
    async def test_stream_with_tools_fallback(self):
        """Default stream_with_tools falls back to call_with_tools."""

        class TestProvider(LLMProvider):
            async def stream_chat(self, messages, model="", system_prompt=""):
                yield {"type": "text", "text": "x"}

            async def complete_chat(self, messages, model="", system_prompt=""):
                return "text", {}

            async def call_with_tools(self, messages, tools, model="", system_prompt="", tool_choice=None, max_tokens=16384):
                return {
                    "content": [
                        {"type": "tool_use", "name": "search", "input": {"q": "test"}},
                    ],
                    "usage": {"model": "test", "input_tokens": 5, "output_tokens": 3},
                }

            async def evaluate_condition(self, messages, model="", system_prompt=""):
                return True, "yes", {}

        provider = TestProvider()
        chunks = []
        async for chunk in provider.stream_with_tools(
            [{"role": "user", "content": "x"}], [{"name": "search"}]
        ):
            chunks.append(chunk)

        types = [c["type"] for c in chunks]
        assert "tool_start" in types
        assert "input_delta" in types
        assert "tool_done" in types
        assert "usage" in types


# ── Grok Provider ───────────────────────────────────────────────────


class TestGrokProvider:

    def test_initializes_with_xai_base_url(self):
        with patch("services.providers.grok_provider.openai") as mock_openai:
            mock_openai.AsyncOpenAI = MagicMock()
            from services.providers.grok_provider import GrokProvider
            p = GrokProvider("test-key")
            mock_openai.AsyncOpenAI.assert_called_once_with(
                api_key="test-key",
                base_url="https://api.x.ai/v1",
            )

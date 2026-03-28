"""Tests for mcp_client."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace


class TestListMcpTools:

    @pytest.mark.asyncio
    async def test_converts_tools_to_claude_format(self):
        from services.mcp_client import list_mcp_tools

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search",
                    description="Search the web",
                    inputSchema={"type": "object", "properties": {"q": {"type": "string"}}},
                ),
                SimpleNamespace(
                    name="calc",
                    description="Calculate",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
        ))

        result = await list_mcp_tools(mock_session)
        assert len(result) == 2
        assert result[0]["name"] == "search"
        assert result[0]["description"] == "Search the web"
        assert result[0]["input_schema"]["properties"]["q"]["type"] == "string"


class TestCallMcpTool:

    @pytest.mark.asyncio
    async def test_text_only_returns_string(self):
        from services.mcp_client import call_mcp_tool

        tool_result = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Result line 1"),
                SimpleNamespace(type="text", text="Result line 2"),
            ]
        )

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=tool_result)

        # asyncio.wait_for awaits the coro, so mock it to return the result
        async def fake_wait_for(coro, timeout):
            return await coro

        with patch("services.mcp_client.asyncio.wait_for", side_effect=fake_wait_for):
            result = await call_mcp_tool(mock_session, "search", {"q": "test"})

        assert isinstance(result, str)
        assert "Result line 1" in result
        assert "Result line 2" in result

    @pytest.mark.asyncio
    async def test_image_content_returns_list(self):
        from services.mcp_client import call_mcp_tool

        tool_result = SimpleNamespace(
            content=[
                SimpleNamespace(type="text", text="Here's the image"),
                SimpleNamespace(type="image", data="base64data", mimeType="image/png"),
            ]
        )

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=tool_result)

        async def fake_wait_for(coro, timeout):
            return await coro

        with patch("services.mcp_client.asyncio.wait_for", side_effect=fake_wait_for):
            result = await call_mcp_tool(mock_session, "render", {})

        assert isinstance(result, list)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_large_image_omitted(self):
        from services.mcp_client import call_mcp_tool

        large_data = "x" * 200_000  # Over 150K limit
        tool_result = SimpleNamespace(
            content=[
                SimpleNamespace(type="image", data=large_data, mimeType="image/png"),
            ]
        )

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=tool_result)

        async def fake_wait_for(coro, timeout):
            return await coro

        with patch("services.mcp_client.asyncio.wait_for", side_effect=fake_wait_for):
            result = await call_mcp_tool(mock_session, "render", {})

        # Large images should be omitted with a message
        if isinstance(result, str):
            assert "omitted" in result.lower() or "large" in result.lower() or "too" in result.lower()
        else:
            text_items = [r for r in result if isinstance(r, dict) and r.get("type") == "text"]
            assert any("omitted" in t.get("text", "").lower() or "too" in t.get("text", "").lower() for t in text_items)

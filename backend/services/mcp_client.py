"""
MCP (Model Context Protocol) client service.
Connects to MCP servers via stdio or HTTP/SSE and exposes tool listing/calling.
"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client

# Timeout for cleaning up MCP connections (seconds).
# stdio servers that spawn long-lived processes (e.g. Chrome) may not exit
# cleanly, so we force-close after this timeout to avoid hanging forever.
CLEANUP_TIMEOUT = 5

# Timeout for individual MCP tool calls (seconds).
TOOL_CALL_TIMEOUT = 120


@asynccontextmanager
async def connect_mcp(server_config: dict):
    """Connect to an MCP server. Yields a ClientSession.

    Uses an internal AsyncExitStack so that cleanup can be forced
    within a timeout — prevents hanging when stdio subprocesses
    (e.g. headless browsers) refuse to exit cleanly.

    server_config keys: transport (0=stdio, 1=http), command, args, url
    """
    transport = server_config.get("transport", 0)
    exit_stack = AsyncExitStack()

    try:
        await exit_stack.__aenter__()

        if transport == 0:
            # Stdio transport
            params = StdioServerParameters(
                command=server_config.get("command", ""),
                args=server_config.get("args", []),
            )
            read, write = await exit_stack.enter_async_context(stdio_client(params))
        else:
            # HTTP/SSE transport
            url = server_config.get("url", "")
            headers = server_config.get("resolved_headers") or None
            read, write = await exit_stack.enter_async_context(sse_client(url, headers=headers))

        session = await exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        yield session

    finally:
        # Force cleanup within a timeout so we never hang.
        # We avoid asyncio.wait_for here because it cancels the task on
        # timeout, and the MCP SDK's anyio cancel scopes turn that into a
        # CancelledError that propagates uncontrollably.  Instead, fire off
        # the cleanup as a background task and give it a few seconds.
        async def _cleanup():
            try:
                await exit_stack.aclose()
            except BaseException:
                pass

        task = asyncio.create_task(_cleanup())
        try:
            await asyncio.wait({task}, timeout=CLEANUP_TIMEOUT)
        except BaseException:
            pass
        # If the task is still running after the timeout, let it die on its own
        if not task.done():
            task.cancel()


async def list_mcp_tools(session: ClientSession) -> list[dict]:
    """List tools from an MCP session. Returns Claude-compatible tool dicts."""
    result = await session.list_tools()
    tools = []
    for tool in result.tools:
        tools.append({
            "name": tool.name,
            "description": tool.description or tool.name,
            "input_schema": tool.inputSchema,
        })
    return tools


async def call_mcp_tool(session: ClientSession, name: str, arguments: dict) -> list[dict] | str:
    """Call a tool on an MCP server and return structured content.

    Returns a list of Claude-compatible content blocks (text/image) when
    the result contains non-text content, or a plain string for simple
    text-only results.  Has a timeout to prevent hanging on slow tool calls.
    """
    # Max base64 image size to include inline (~100KB encoded ≈ ~75KB image)
    IMAGE_SIZE_LIMIT = 150_000

    result = await asyncio.wait_for(
        session.call_tool(name, arguments=arguments),
        timeout=TOOL_CALL_TIMEOUT,
    )

    has_non_text = any(getattr(b, "type", None) == "image" for b in result.content)

    if not has_non_text:
        # Fast path: text-only results stay as plain strings
        parts = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            else:
                parts.append(str(block))
        return "\n".join(parts) if parts else ""

    # Structured path: return list of content blocks
    content: list[dict] = []
    for block in result.content:
        if hasattr(block, "text"):
            content.append({"type": "text", "text": block.text})
        elif getattr(block, "type", None) == "image" and hasattr(block, "data"):
            if len(block.data) < IMAGE_SIZE_LIMIT:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": getattr(block, "mimeType", "image/png"),
                        "data": block.data,
                    },
                })
            else:
                content.append({"type": "text", "text": f"[Image omitted — {len(block.data)//1000}KB exceeds limit]"})
        else:
            content.append({"type": "text", "text": str(block)})
    return content

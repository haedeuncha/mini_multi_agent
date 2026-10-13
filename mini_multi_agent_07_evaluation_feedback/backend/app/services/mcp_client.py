"""MCP Tool 호출을 위한 공통 Client 함수입니다."""

from __future__ import annotations

import asyncio
import json
from typing import Any


async def call_mcp_tool_async(mcp_url: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            server_tools = {tool.name for tool in (await session.list_tools()).tools}
            if tool_name not in server_tools:
                raise ValueError(f"MCP Server가 제공하지 않는 Tool입니다: {tool_name}")
            result = await session.call_tool(tool_name, arguments=arguments)
            text = "\n".join(item.text for item in result.content if hasattr(item, "text"))
            if result.isError:
                raise RuntimeError(text or "MCP Tool 실행 실패")
            if result.structuredContent is not None:
                return result.structuredContent
            return json.loads(text) if text else None


def call_mcp_tool(mcp_url: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """동기 코드에서 MCP Tool을 호출하기 위한 얇은 wrapper입니다."""

    return asyncio.run(call_mcp_tool_async(mcp_url, tool_name, arguments))

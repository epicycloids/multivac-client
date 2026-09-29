"""Portable MCP calls shared by hosted clients and project adapters."""

import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call_endpoint(endpoint, tool, arguments=None, headers=None):
    async with httpx.AsyncClient(headers=headers or {}, timeout=180) as http:
        async with streamable_http_client(endpoint, http_client=http) as streams:
            async with ClientSession(*streams) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments or {})
                if result.is_error:
                    raise ValueError(
                        "; ".join(c.text for c in result.content if hasattr(c, "text"))
                    )
                content = result.structured_content
                if content is not None:
                    return content.get("result", content) if isinstance(content, dict) else content
                for item in result.content:
                    if hasattr(item, "text"):
                        return json.loads(item.text)
                raise ValueError("Project returned no structured result.")

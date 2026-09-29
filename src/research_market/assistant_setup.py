"""Configure a local assistant to use the Multivac MCP bridge."""

from __future__ import annotations

import asyncio
import json
import shlex
import sys
from enum import Enum


class Harness(str, Enum):
    custom = "custom"
    claude = "claude-code"
    qwen = "qwen"
    kimi = "kimi"
    codex = "codex"


def assistant_config(client):
    oversight = client.config.get("identity", {}).get("role") == "overseer"
    name = "multivac-overseer" if oversight else "multivac"
    args = [
        "-m",
        "research_market.client_entry",
        "--origin",
        client.origin,
        "--connection",
        client.path.stem,
        "--data-dir",
        str(client.directory.parent),
        "overseer-mcp" if oversight else "mcp",
    ]
    return {
        "mcpServers": {name: {"command": sys.executable, "args": args}},
        "codex_command": shlex.join(["codex", "mcp", "add", name, "--", sys.executable, *args]),
        "example": (
            "Inspect allocation activity and the current policy. Explain whether any change is "
            "justified by the evidence; keep contributor limits and project admission intact."
            if oversight
            else "Explore my approved Multivac projects and choose useful work for this assistant. "
            "Contribute up to ten minutes using my current model and tools. Inspect the task "
            "first, respect my resource and data-access permissions, and return findings and "
            "limitations. Show me the project's receipt and any review still needed."
        ),
        "check_prompt": (
            "Use Multivac to inspect the allocation policy and available resources. "
            "Report the current state without changing the policy or issuing grants."
            if oversight
            else "Check my Multivac connection and list the projects I can contribute to. "
            "Summarize their objectives and available work. Do not reserve or start work yet."
        ),
    }


def assistant_setup(client):
    config = assistant_config(client)
    name, server = next(iter(config["mcpServers"].items()))
    snippet = json.dumps({"mcpServers": config["mcpServers"]}, indent=2)
    return {
        **config,
        "profiles": [
            {
                "id": "custom",
                "title": "Custom or other MCP assistant",
                "format": "json",
                "setup": snippet,
                "instructions": "Add this entry to your assistant's MCP configuration. "
                "It starts the installed Multivac client on this machine over stdio.",
                "documentation": "https://modelcontextprotocol.io/docs/develop/connect-local-servers",
            },
            {
                "id": "claude-code",
                "title": "Claude Code",
                "format": "command",
                "setup": shlex.join(
                    [
                        "claude",
                        "mcp",
                        "add",
                        "--transport",
                        "stdio",
                        "--scope",
                        "local",
                        name,
                        "--",
                        server["command"],
                        *server["args"],
                    ]
                ),
                "instructions": "Run this in the project where you use Claude Code. "
                "Start a new session and check /mcp. The entry uses Claude's local project scope.",
                "documentation": "https://code.claude.com/docs/en/mcp",
            },
            {
                "id": "qwen",
                "title": "Qwen Code",
                "format": "json",
                "setup": snippet,
                "instructions": "Merge this entry into .qwen/settings.json in your project, "
                "preserving existing settings. Start a new Qwen Code session and check /mcp.",
                "documentation": "https://qwenlm.github.io/qwen-code-docs/en/users/features/mcp/",
            },
            {
                "id": "kimi",
                "title": "Kimi Code",
                "format": "json",
                "setup": snippet,
                "instructions": "Merge this entry into .kimi-code/mcp.json in your project, "
                "preserving existing entries. Start a new Kimi Code session and check /mcp.",
                "documentation": "https://moonshotai.github.io/kimi-code/en/customization/mcp",
            },
            {
                "id": "codex",
                "title": "Codex",
                "format": "command",
                "setup": config["codex_command"],
                "instructions": "Run this to add the bridge to your Codex configuration, "
                "then open a new chat. Use codex mcp list to inspect the saved entry.",
                "documentation": "https://learn.chatgpt.com/docs/extend/mcp?surface=cli",
            },
        ],
    }


async def check_assistant_bridge(client):
    """Initialize the installed bridge and discover tools without contacting a project."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    name, server = next(iter(assistant_config(client)["mcpServers"].items()))
    try:
        async with asyncio.timeout(15):
            async with stdio_client(StdioServerParameters(**server)) as streams:
                async with ClientSession(*streams, read_timeout_seconds=10) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = sorted(tool.name for tool in tools.tools)
    except Exception:
        raise ValueError(
            "The MCP bridge could not initialize. Check that the client is installed in "
            "the Python environment shown in the setup, then retry."
        ) from None
    required = (
        {"inspect_allocation"}
        if name == "multivac-overseer"
        else {
            "connection_status",
            "list_projects",
            "offer_resources",
            "return_result",
        }
    )
    if not required <= set(names):
        raise ValueError(
            "The bridge's tool list does not match this client. Check its installation."
        )
    return {
        "state": "ready",
        "server": name,
        "tools": names,
        "model_calls": 0,
        "note": "Bridge initialization passed. Check the connection in your assistant next.",
    }

"""Owned SDK MCP server fixture, never a PAL provider or application registration."""

import asyncio
import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("owned-pal-fixture")


@server.list_tools()
async def list_tools():
    return [Tool(name="codereview", inputSchema={"type": "object"})]


@server.call_tool()
async def call_tool(name, arguments):
    assert name == "codereview" and arguments["use_assistant_model"] is False
    assert arguments["step_number"] in {1, 2}
    result = {
        "status": "codereview_in_progress"
        if arguments["step_number"] == 1
        else "code_review_complete_ready_for_implementation",
        "continuation_id": "owned-continuation",
        "step_number": arguments["step_number"],
    }
    return [TextContent(type="text", text=json.dumps(result))]


async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())

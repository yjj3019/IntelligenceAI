"""Restricted MCP SDK stdio server. No HTTP listener, sampling or app registration."""

import argparse
import asyncio
import json
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .security import clean
from .service import TOOLS, ControllerService


def build_server(service: ControllerService) -> Server:
    server = Server("IntelligenceAI-local")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=name,
                description="Local offline controller: " + name,
                inputSchema=model.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=name in {"capabilities", "preview", "status", "results"},
                    destructiveHint=name == "cancel",
                    idempotentHint=True,
                    openWorldHint=False,
                ),
            )
            for name, model in TOOLS.items()
        ]

    # Pydantic validates inside our redacted error boundary; SDK schema errors can
    # otherwise echo sensitive invalid argument values into the protocol stream.
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict):
        try:
            result = clean(await asyncio.to_thread(service.call, name, arguments))
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
            )
        except Exception:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text='{"error":"request invalid, disabled or outside operator grants"}',
                    )
                ],
                isError=True,
            )

    return server


async def serve(root: Path, repositories: dict[str, Path]):
    service = ControllerService(root, repositories)
    server = build_server(service)
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        await asyncio.to_thread(service.close)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline local MCP over stdio only")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument(
        "--repo", action="append", required=True, help="Operator grant NAME=ABSOLUTE_PATH"
    )
    args = parser.parse_args(argv)
    repositories = {}
    for grant in args.repo:
        if "=" not in grant:
            parser.error("repository grant must be NAME=ABSOLUTE_PATH")
        name, path = grant.split("=", 1)
        if name in repositories or not Path(path).is_absolute():
            parser.error("duplicate grant or relative path")
        repositories[name] = Path(path)
    asyncio.run(serve(args.state_dir, repositories))


if __name__ == "__main__":
    main()

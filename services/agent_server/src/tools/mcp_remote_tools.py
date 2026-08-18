"""MCP-backed tool adapter (MCP SDK v2 Streamable HTTP).

This module lets agents use tools exposed by the MCP server
(services/mcp_server) instead of importing local LangChain tool functions.

Design goals:
- Keep agent code unchanged: returned tools expose .name and .invoke(...)
- Avoid importing mcp unless actually used (local mode stays dependency-free)
- Work from synchronous agent code while MCP client is async
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, List, Optional

from eo_llm.adapters.mcp_transport import (
    extract_tool_payload,
    mcp_streamable_http_url,
    tool_input_schema,
)
from src.config import get_config
from src.core import get_logger

logger = get_logger("mcp-remote-tools")


def _mcp_http_url() -> str:
    """MCP Streamable HTTP endpoint URL (…/mcp)."""
    try:
        base = get_config().mcp_server_url.strip()
    except Exception:
        base = ""
    if not base:
        base = (os.getenv("MCP_SERVER_URL") or "http://localhost:8000").strip()
    return mcp_streamable_http_url(base)


def _run_sync(coro: Any) -> Any:
    """Run an async coroutine from sync code.

    If there's already a running event loop, we execute the
    coroutine in a dedicated thread using its own loop.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Running loop exists: run in a separate thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(lambda: asyncio.run(coro))
        return future.result()


async def _list_tools_async() -> list[Any]:
    # Lazy import so local mode doesn't require mcp installed.
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    # MCP 1.x yields (read, write, get_session_id); MCP 2.x yields (read, write).
    async with streamable_http_client(_mcp_http_url()) as streams:
        read, write = streams[0], streams[1]
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.list_tools()
            return list(getattr(result, "tools", []) or [])


async def _call_tool_async(tool_name: str, arguments: dict) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    try:
        async with streamable_http_client(_mcp_http_url()) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                logger.debug(f"MCP tool {tool_name} executed successfully")
                return result
    except Exception as e:
        import traceback

        logger.error(f"Error calling MCP tool {tool_name}: {e}")
        logger.error(traceback.format_exc())
        error_msg = str(e)

        if hasattr(e, "__cause__"):
            errors = e.__cause__
            if errors:
                raise Exception(error_msg) from e

        logger.error(f"MCP tool call failed for {tool_name}: {traceback.format_exc()}")
        raise


def _coerce_args(tool_input: Any, input_schema: Optional[dict]) -> dict:
    """Best-effort mapping from agent tool_input -> MCP tool arguments."""
    if isinstance(tool_input, dict):
        return tool_input

    schema = input_schema or {}
    required = schema.get("required") or []
    properties = schema.get("properties") or {}

    if tool_input is None:
        return {}

    if (
        isinstance(required, list)
        and len(required) == 1
        and isinstance(required[0], str)
    ):
        return {required[0]: tool_input}

    if isinstance(properties, dict) and len(properties) == 1:
        key = next(iter(properties.keys()))
        return {key: tool_input}

    return {"input": tool_input}


def _parse_mcp_call_result(tool_name: str, result: Any) -> Any:
    """Normalize MCP call_tool result into the repo's tool-response dict shape."""
    return extract_tool_payload(tool_name, result)


@dataclass
class MCPRemoteTool:
    name: str
    description: str = ""
    input_schema: Optional[dict] = None

    def invoke(self, tool_input: Any = None) -> Any:
        args = _coerce_args(tool_input, self.input_schema)
        result = _run_sync(_call_tool_async(self.name, args))
        return _parse_mcp_call_result(self.name, result)


def get_mcp_tools() -> List[MCPRemoteTool]:
    """Fetch tool metadata from MCP server and return invokable wrappers."""
    tools = _run_sync(_list_tools_async())

    wrapped: list[MCPRemoteTool] = []
    for t in tools:
        name = getattr(t, "name", None)
        if not isinstance(name, str) or not name.strip():
            continue
        wrapped.append(
            MCPRemoteTool(
                name=name,
                description=getattr(t, "description", "") or "",
                input_schema=tool_input_schema(t) or None,
            )
        )

    wrapped.sort(key=lambda x: x.name)
    return wrapped

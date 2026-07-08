"""Simple MCP client adapter for graph domain nodes."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import json
import os
from typing import Any, Callable, Optional


# Active stream callback used to surface per-tool progress to the UI. Domain
# nodes call the module-level `call_mcp_tool`, so we thread the websocket
# stream callback through a contextvar instead of changing every node signature.
_stream_callback: contextvars.ContextVar[Optional[Callable[[dict[str, Any]], None]]] = (
    contextvars.ContextVar("mcp_stream_callback", default=None)
)


def set_stream_callback(
    callback: Optional[Callable[[dict[str, Any]], None]],
) -> contextvars.Token:
    """Register the stream callback for the current execution context.

    Returns a token that can be passed to `reset_stream_callback`.
    """
    return _stream_callback.set(callback)


def reset_stream_callback(token: contextvars.Token) -> None:
    """Restore the previous stream callback."""
    try:
        _stream_callback.reset(token)
    except (ValueError, LookupError):
        pass


def emit_stream_event(event: dict[str, Any]) -> None:
    """Forward a stream event to the active websocket callback, if any."""
    callback = _stream_callback.get()
    if callback is None:
        return
    try:
        callback(event)
    except Exception:
        # Streaming must never break tool execution.
        pass


def _mcp_sse_url() -> str:
    base = (os.getenv("MCP_SERVER_URL") or "http://localhost:8000").strip().rstrip("/")
    return base if base.endswith("/sse") else f"{base}/sse"


def _run_sync(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # If already in an event loop, run a private loop in a worker thread.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(lambda: asyncio.run(coro))
        return future.result()


async def _call_tool_async(tool_name: str, arguments: dict[str, Any]) -> Any:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(_mcp_sse_url()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.call_tool(tool_name, arguments)


async def _list_tools_async() -> Any:
    from mcp import ClientSession
    from mcp.client.sse import sse_client

    async with sse_client(_mcp_sse_url()) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await session.list_tools()


# Cache of tool signature metadata fetched from the MCP server, keyed by tool
# name: {"all_params": [...], "required_params": [...], "docstring": "..."}.
_tool_metadata_cache: Optional[dict[str, dict[str, Any]]] = None


def _build_tool_metadata_cache() -> dict[str, dict[str, Any]]:
    result = _run_sync(_list_tools_async())
    tools = getattr(result, "tools", None) or []
    out: dict[str, dict[str, Any]] = {}
    for tool in tools:
        name = getattr(tool, "name", None)
        if not name:
            continue
        schema = getattr(tool, "inputSchema", None) or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        out[name] = {
            "all_params": [str(k) for k in properties.keys()],
            "required_params": [str(k) for k in required],
            "docstring": str(getattr(tool, "description", "") or ""),
        }
    return out


def get_tool_metadata(tool_name: str) -> dict[str, Any]:
    """Return MCP-advertised signature metadata for a tool.

    Fetches and caches the MCP server's `list_tools` schemas on first use so the
    Bedrock argument resolver knows each tool's real parameter names, required
    fields, and docstring (needed to derive e.g. dates from the user query).
    """
    global _tool_metadata_cache
    if _tool_metadata_cache is None:
        try:
            _tool_metadata_cache = _build_tool_metadata_cache()
        except Exception:
            _tool_metadata_cache = {}
    return _tool_metadata_cache.get(
        tool_name, {"all_params": [], "required_params": [], "docstring": ""}
    )


def reset_tool_metadata_cache() -> None:
    """Clear the cached MCP tool metadata (e.g. after a server restart)."""
    global _tool_metadata_cache
    _tool_metadata_cache = None


def _parse_result(tool_name: str, result: Any) -> dict[str, Any]:
    content = getattr(result, "content", None) or []
    if not content:
        return {
            "tool_name": tool_name,
            "message": "Empty MCP result.",
            "data": {},
            "error": True,
        }

    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return {
            "tool_name": tool_name,
            "message": "MCP returned non-text content.",
            "data": {"raw": str(result)},
            "error": False,
        }

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    return {
        "tool_name": tool_name,
        "message": str(text),
        "data": {},
        "error": False,
    }


def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Sync MCP transport used by graph domain nodes.

    Tool start/done stream events are emitted by ``ToolExecutor`` so parallel
    steps, retries, and skip paths share one consistent event shape.
    """
    try:
        raw = _run_sync(_call_tool_async(tool_name, arguments))
        parsed = _parse_result(tool_name, raw)
        if "tool_name" not in parsed:
            parsed["tool_name"] = tool_name
        if "error" not in parsed:
            parsed["error"] = False
    except Exception as exc:
        parsed = {
            "tool_name": tool_name,
            "message": f"MCP call failed: {exc}",
            "data": {"arguments": arguments},
            "error": True,
        }
    return parsed


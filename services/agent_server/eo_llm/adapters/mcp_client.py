"""Simple MCP client adapter for graph domain nodes (MCP SDK v2 Streamable HTTP).

Deprecated: prefer :class:`src.tools.runtime.gateway.ToolGateway` for new code.
This class delegates to the unified tool gateway when available.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import ValidationError

from eo_llm.adapters.mcp_transport import (
    extract_tool_payload,
    mcp_streamable_http_url,
    tool_metadata_from_mcp_tool,
)
from src.config import get_config
from src.core.singleton_meta import SingletonMeta
from src.tools.contracts import ToolArtifacts, ToolResponse


class MCPClient(metaclass=SingletonMeta):
    """Adapter for interacting with an MCP server via Streamable HTTP."""

    def __init__(self):
        self.server_url = get_config().mcp_server_url
        self._tool_metadata_cache: Optional[dict[str, dict[str, Any]]] = None

    @property
    def mcp_http_url(self) -> str:
        return mcp_streamable_http_url(self.server_url)

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(self.mcp_http_url) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments)

    async def _list_tools_async(self) -> Any:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with streamable_http_client(self.mcp_http_url) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.list_tools()

    async def _build_tool_metadata_cache(self) -> dict[str, dict[str, Any]]:
        result = await self._list_tools_async()
        tools = getattr(result, "tools", None) or []
        out: dict[str, dict[str, Any]] = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if not name:
                continue
            out[name] = tool_metadata_from_mcp_tool(tool)
        return out

    def reset_tool_metadata_cache(self) -> None:
        self._tool_metadata_cache = None

    @staticmethod
    def _parse_result(tool_name: str, result: Any) -> ToolResponse:
        parsed = extract_tool_payload(tool_name, result)
        if not isinstance(parsed, dict):
            return ToolResponse(tool_name=tool_name, message=str(parsed))
        parsed.setdefault("tool_name", tool_name)
        parsed.setdefault("message", "")
        try:
            return ToolResponse.model_validate(parsed)
        except ValidationError:
            artifacts_raw = parsed.get("artifacts")
            artifacts = (
                ToolArtifacts.model_validate(artifacts_raw)
                if isinstance(artifacts_raw, dict)
                else ToolArtifacts()
            )
            data = parsed.get("data")
            return ToolResponse(
                tool_name=str(parsed.get("tool_name") or tool_name),
                message=str(parsed.get("message") or ""),
                artifacts=artifacts,
                data=data if isinstance(data, dict) else {"raw": parsed},
                error=bool(parsed.get("error", False)),
            )

    async def get_tool_metadata(self, tool_name: str) -> dict[str, Any]:
        try:
            from src.tools.runtime.gateway import get_tool_gateway

            meta = await get_tool_gateway().get_metadata(tool_name)
            if meta.get("all_params") or meta.get("docstring"):
                return meta
        except Exception:
            pass

        if self._tool_metadata_cache is None:
            try:
                self._tool_metadata_cache = await self._build_tool_metadata_cache()
            except Exception:
                self._tool_metadata_cache = {}

        return self._tool_metadata_cache.get(
            tool_name, {"all_params": [], "required_params": [], "docstring": ""}
        )

    async def call_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResponse:
        """Call a tool and return a typed ToolResponse."""
        try:
            from src.tools.runtime.gateway import get_tool_gateway

            return await get_tool_gateway().invoke(tool_name, arguments)
        except Exception:
            pass
        try:
            raw = await self._call_tool_async(tool_name, arguments)
            return self._parse_result(tool_name, raw)
        except Exception as exc:
            detail = _format_mcp_error(exc)
            return ToolResponse(
                tool_name=tool_name,
                message=f"MCP call failed: {detail}",
                data={"arguments": arguments},
                error=True,
            )


def _format_mcp_error(exc: BaseException) -> str:
    """Flatten ExceptionGroup / TaskGroup errors into a readable message."""
    if isinstance(exc, BaseExceptionGroup):
        parts = [_format_mcp_error(e) for e in exc.exceptions]
        return "; ".join(parts) if parts else str(exc)
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, BaseExceptionGroup):
        return f"{exc}: {_format_mcp_error(cause)}"
    return str(exc)

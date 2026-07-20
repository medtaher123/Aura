"""Simple MCP client adapter for graph domain nodes."""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from pydantic import ValidationError

from src.config import get_config
from src.core.singleton_meta import SingletonMeta
from src.tools.contracts import ToolArtifacts, ToolResponse


class MCPClient(metaclass=SingletonMeta):
    """Adapter for interacting with an MCP server via SSE."""

    def __init__(self):
        self.server_url = get_config().mcp_server_url
        self._tool_metadata_cache: Optional[dict[str, dict[str, Any]]] = None

    @property
    def mcp_sse_url(self) -> str:
        base = self.server_url.strip().rstrip("/")
        return base if base.endswith("/sse") else f"{base}/sse"

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(self.mcp_sse_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool_name, arguments)

    async def _list_tools_async(self) -> Any:
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with sse_client(self.mcp_sse_url) as (read, write):
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
            schema = getattr(tool, "inputSchema", None) or {}
            properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = schema.get("required", []) if isinstance(schema, dict) else []
            out[name] = {
                "all_params": [str(k) for k in properties.keys()],
                "required_params": [str(k) for k in required],
                "docstring": str(getattr(tool, "description", "") or ""),
            }
        return out

    async def get_tool_metadata(self, tool_name: str) -> dict[str, Any]:
        # TODO: to remove?
        if self._tool_metadata_cache is None:
            try:
                self._tool_metadata_cache = await self._build_tool_metadata_cache()
            except Exception:
                self._tool_metadata_cache = {}

        return self._tool_metadata_cache.get(
            tool_name, {"all_params": [], "required_params": [], "docstring": ""}
        )

    def reset_tool_metadata_cache(self) -> None:
        self._tool_metadata_cache = None

    @staticmethod
    def _parse_result(tool_name: str, result: Any) -> ToolResponse:
        """Parse MCP transport payload into a typed ToolResponse."""
        content = getattr(result, "content", None) or []
        if not content:
            return ToolResponse(
                tool_name=tool_name,
                message="Empty MCP result.",
                error=True,
            )

        first = content[0]
        text = getattr(first, "text", None)
        if text is None:
            return ToolResponse(
                tool_name=tool_name,
                message="MCP returned non-text content.",
                data={"raw": str(result)},
            )

        try:
            parsed = json.loads(text)
        except Exception:
            return ToolResponse(tool_name=tool_name, message=str(text))

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

    async def call_mcp_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResponse:
        """Call an MCP tool and return a typed ToolResponse."""
        try:
            raw = await self._call_tool_async(tool_name, arguments)
            return self._parse_result(tool_name, raw)
        except Exception as exc:
            return ToolResponse(
                tool_name=tool_name,
                message=f"MCP call failed: {exc}",
                data={"arguments": arguments},
                error=True,
            )

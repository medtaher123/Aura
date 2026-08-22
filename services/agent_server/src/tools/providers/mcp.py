"""MCP Streamable HTTP / stdio tool provider."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import UUID

from pydantic import ValidationError

from eo_llm.adapters.mcp_transport import (
    extract_tool_payload,
    mcp_streamable_http_url,
    tool_metadata_from_mcp_tool,
)
from src.tools.contracts import ToolArtifacts, ToolResponse
from src.tools.providers.base import ProviderHealth, ToolDescriptor, ToolProvider

# First ``npx -y …`` install can be slow; keep bounded so sync/health cannot hang forever.
_STDIO_OP_TIMEOUT_SECONDS = 60.0


class McpToolProvider(ToolProvider):
    """One MCP server connection exposed as a tool provider."""

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str = "",
        transport: str = "streamable_http",
        auth_headers: dict[str, str] | None = None,
        stdio_config: dict[str, Any] | None = None,
        mcp_server_id: UUID | None = None,
        db_tool_ids: dict[str, UUID] | None = None,
    ) -> None:
        self._provider_id = provider_id
        self.base_url = (base_url or "").rstrip("/")
        self.transport = transport
        self.auth_headers = auth_headers or {}
        self.stdio_config = dict(stdio_config or {})
        self.mcp_server_id = mcp_server_id
        self._db_tool_ids = db_tool_ids or {}
        self._metadata_cache: dict[str, dict[str, Any]] | None = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def mcp_http_url(self) -> str:
        if self.transport != "streamable_http":
            raise ValueError(f"Unsupported MCP HTTP transport: {self.transport}")
        return mcp_streamable_http_url(self.base_url)

    @asynccontextmanager
    async def _client_session(self) -> AsyncIterator[Any]:
        """Open an initialized MCP ClientSession (HTTP or stdio)."""
        from mcp import ClientSession

        if self.transport == "stdio":
            import os
            import shutil

            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            command = str(self.stdio_config.get("command") or "").strip()
            if not command:
                raise ValueError(
                    f"stdio MCP provider {self.provider_id} missing command"
                )
            # Resolve via PATH so relative commands work even when the parent
            # process has a minimal environment.
            resolved = shutil.which(command) or command
            args = [str(a) for a in (self.stdio_config.get("args") or [])]
            # Empty ``{}`` must NOT be passed through — the MCP SDK treats a
            # dict as the full process env, which drops PATH and yields
            # ``[Errno 2] No such file or directory``.
            raw_env = self.stdio_config.get("env")
            if isinstance(raw_env, dict) and raw_env:
                env = {**os.environ, **{str(k): str(v) for k, v in raw_env.items()}}
            else:
                env = None
            params = StdioServerParameters(
                command=resolved,
                args=args,
                env=env,
            )
            async with stdio_client(params) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
            return

        if self.transport != "streamable_http":
            raise ValueError(f"Unsupported MCP transport: {self.transport}")

        from mcp.client.streamable_http import (
            create_mcp_http_client,
            streamable_http_client,
        )

        # MCP SDK v2 no longer accepts headers= on streamable_http_client;
        # pass auth via a preconfigured httpx client instead.
        headers = dict(self.auth_headers) if self.auth_headers else None
        async with create_mcp_http_client(headers=headers) as http_client:
            async with streamable_http_client(
                self.mcp_http_url, http_client=http_client
            ) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    async def _call_tool_async(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return await self._with_timeout(
            self._call_tool_raw(tool_name, arguments),
            op=f"call_tool:{tool_name}",
        )

    async def _call_tool_raw(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        async with self._client_session() as session:
            return await session.call_tool(tool_name, arguments)

    async def _list_tools_async(self) -> Any:
        return await self._with_timeout(self._list_tools_raw(), op="list_tools")

    async def _list_tools_raw(self) -> Any:
        async with self._client_session() as session:
            return await session.list_tools()

    async def _with_timeout(self, awaitable, *, op: str) -> Any:
        if self.transport != "stdio":
            return await awaitable
        try:
            return await asyncio.wait_for(awaitable, timeout=_STDIO_OP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"stdio MCP {self.provider_id} timed out during {op} "
                f"after {_STDIO_OP_TIMEOUT_SECONDS:.0f}s"
            ) from exc

    async def discover_tools(self) -> list[ToolDescriptor]:
        result = await self._list_tools_async()
        tools = getattr(result, "tools", None) or []
        descriptors: list[ToolDescriptor] = []
        self._metadata_cache = {}
        for tool in tools:
            name = getattr(tool, "name", None)
            if not name:
                continue
            meta = tool_metadata_from_mcp_tool(tool)
            self._metadata_cache[name] = meta
            descriptors.append(
                ToolDescriptor(
                    id=self._db_tool_ids.get(name),
                    name=name,
                    source="mcp",
                    provider_id=self.provider_id,
                    description=str(meta.get("docstring") or ""),
                    input_schema=dict(meta.get("input_schema") or {}),
                    enabled=True,
                    mcp_server_id=self.mcp_server_id,
                )
            )
        return descriptors

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

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        try:
            raw = await self._call_tool_async(name, arguments)
            return self._parse_result(name, raw)
        except Exception as exc:
            return ToolResponse(
                tool_name=name,
                message=f"MCP call failed: {_format_mcp_error(exc)}",
                data={"arguments": arguments, "provider": self.provider_id},
                error=True,
            )

    async def health(self) -> ProviderHealth:
        """Probe reachability via MCP session + ``list_tools``."""
        try:
            result = await self._list_tools_async()
            tools = getattr(result, "tools", None) or []
            count = len(tools)
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=True,
                message="ok",
                details=self._health_details(probe="list_tools"),
                tool_count=count,
            )
        except Exception as exc:
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=False,
                message=_format_mcp_error(exc),
                details=self._health_details(probe="list_tools"),
            )

    def _health_details(self, *, probe: str) -> dict[str, Any]:
        details: dict[str, Any] = {
            "transport": self.transport,
            "probe": probe,
        }
        if self.transport == "stdio":
            command = self.stdio_config.get("command")
            args = self.stdio_config.get("args") or []
            details["command"] = command
            details["args"] = args
            details["launch"] = " ".join(
                [str(command or "")] + [str(a) for a in args]
            ).strip()
        else:
            details["base_url"] = self.base_url
            try:
                details["mcp_url"] = self.mcp_http_url
            except Exception:
                pass
        return details


def _format_mcp_error(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts = [_format_mcp_error(e) for e in exc.exceptions]
        return "; ".join(parts) if parts else str(exc)
    cause = getattr(exc, "__cause__", None)
    if isinstance(cause, BaseExceptionGroup):
        return f"{exc}: {_format_mcp_error(cause)}"
    return str(exc)

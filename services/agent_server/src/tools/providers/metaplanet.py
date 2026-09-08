"""Metaplanet first-party MCP provider.

Unlike external MCP servers (YAML-configured), Metaplanet MCP is built into
the agent server: its URL comes from ``MCP_SERVER_URL``, it is always the
primary provider, and it exposes Metaplanet-specific management APIs
(dashboard / module health).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

import httpx

from src.tools.providers.mcp import McpToolProvider
from src.tools.providers.base import ProviderHealth, ToolDescriptor

METAPLANET_MCP_SLUG = "metaplanet"
METAPLANET_MCP_DISPLAY_NAME = "Metaplanet MCP"


class MetaplanetMcpProvider(McpToolProvider):
    """First-party Metaplanet MCP with dashboard / module management APIs."""

    def __init__(
        self,
        *,
        base_url: str,
        transport: str = "streamable_http",
        auth_headers: dict[str, str] | None = None,
        stdio_config: dict[str, Any] | None = None,
        mcp_server_id: UUID | None = None,
        db_tool_ids: dict[str, UUID] | None = None,
        provider_id: str = METAPLANET_MCP_SLUG,
    ) -> None:
        super().__init__(
            provider_id=provider_id or METAPLANET_MCP_SLUG,
            base_url=base_url,
            transport=transport,
            auth_headers=auth_headers,
            stdio_config=stdio_config,
            mcp_server_id=mcp_server_id,
            db_tool_ids=db_tool_ids,
        )

    async def discover_tools(self) -> list[ToolDescriptor]:
        """Discover tools and attach module names from meta and/or management API."""
        descriptors = await super().discover_tools()
        module_by_tool = await self._module_by_tool_name()
        if not module_by_tool:
            return descriptors

        enriched: list[ToolDescriptor] = []
        for descriptor in descriptors:
            module = descriptor.module or module_by_tool.get(descriptor.name)
            if module and module != descriptor.module:
                if self._metadata_cache is not None and descriptor.name in self._metadata_cache:
                    self._metadata_cache[descriptor.name]["module"] = module
                enriched.append(replace(descriptor, module=module))
            else:
                enriched.append(descriptor)
        return enriched

    async def _module_by_tool_name(self) -> dict[str, str]:
        """Map tool name → module using ``/api/dashboard/modules`` registered_tools."""
        payload = await self.fetch_management_modules()
        if not isinstance(payload, dict):
            return {}
        modules = payload.get("modules")
        if not isinstance(modules, list):
            return {}
        mapping: dict[str, str] = {}
        for entry in modules:
            if not isinstance(entry, dict):
                continue
            module_name = entry.get("name")
            tools = entry.get("registered_tools")
            if not isinstance(module_name, str) or not module_name.strip():
                continue
            if not isinstance(tools, list):
                continue
            for tool_name in tools:
                if isinstance(tool_name, str) and tool_name.strip():
                    mapping[tool_name] = module_name.strip()
        return mapping

    async def health(self) -> ProviderHealth:
        """Use Metaplanet's HTTP ``/health`` endpoint when available."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{self.base_url}/health")
                body = response.json() if response.content else {}
            healthy = response.status_code == 200 and body.get("status") == "healthy"
            return ProviderHealth(
                provider_id=self.provider_id,
                healthy=healthy,
                message=body.get("status", "unknown"),
                details={
                    "base_url": self.base_url,
                    "http_status": response.status_code,
                    "probe": "http_health",
                    **{k: v for k, v in body.items() if k != "status"},
                },
                tool_count=int(body.get("tools_loaded") or 0),
            )
        except Exception as exc:
            # Fall back to MCP protocol probe if /health is unreachable.
            fallback = await super().health()
            fallback.message = (
                f"http /health failed ({exc}); mcp probe: {fallback.message}"
            )
            fallback.details = {
                **fallback.details,
                "http_health_error": str(exc),
            }
            return fallback

    async def fetch_management_modules(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(f"{self.base_url}/api/dashboard/modules")
                if response.status_code != 200:
                    return None
                return response.json()
        except Exception:
            return None

    async def fetch_management_dashboard(self) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(f"{self.base_url}/api/dashboard")
                if response.status_code != 200:
                    return None
                return response.json()
        except Exception:
            return None


def is_metaplanet_server(*, slug: str, is_primary: bool = False) -> bool:
    return is_primary or slug == METAPLANET_MCP_SLUG

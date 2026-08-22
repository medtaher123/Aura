"""Build the correct MCP provider implementation for a DB server row."""

from __future__ import annotations

from uuid import UUID

from src.db.models.mcp_server import McpServer
from src.tools.platform.mcp_provider import McpToolProvider
from src.tools.platform.metaplanet_provider import (
    MetaplanetMcpProvider,
    is_metaplanet_server,
)


def build_mcp_provider(
    server: McpServer,
    *,
    db_tool_ids: dict[str, UUID] | None = None,
) -> McpToolProvider:
    """Return ``MetaplanetMcpProvider`` for the primary, else a generic MCP provider."""
    kwargs = {
        "base_url": server.base_url or "",
        "transport": server.transport,
        "auth_headers": dict(server.auth_headers or {}),
        "stdio_config": dict(server.stdio_config or {}),
        "mcp_server_id": server.id,
        "db_tool_ids": db_tool_ids,
    }
    if is_metaplanet_server(slug=server.slug, is_primary=server.is_primary):
        return MetaplanetMcpProvider(
            provider_id=server.slug,
            **kwargs,
        )
    return McpToolProvider(
        provider_id=server.slug,
        **kwargs,
    )

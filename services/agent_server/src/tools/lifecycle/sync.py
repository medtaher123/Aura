"""Synchronize MCP and native tools with the database and registry."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logger import get_logger
from src.db.repositories.tool_platform import (
    McpServerRepository,
    ToolDefinitionRepository,
)
from src.tools.providers.factory import build_mcp_provider
from src.tools.providers.native import build_default_native_provider
from src.tools.runtime.registry import ToolRegistry

if TYPE_CHECKING:
    from src.tools.lifecycle.bootstrap import ToolPlatformState

logger = get_logger("tool_platform")


class ToolCatalogSyncService:
    """Discover tools from providers and persist catalog entries."""

    def __init__(self, db: AsyncSession, registry: ToolRegistry) -> None:
        self._db = db
        self._registry = registry
        self._servers = McpServerRepository(db)
        self._tools = ToolDefinitionRepository(db)

    async def sync_all(self) -> dict[str, int]:
        counts = {"mcp_tools": 0, "native_tools": 0}
        counts["native_tools"] = await self._sync_native()
        counts["mcp_tools"] = await self._sync_mcp_servers()
        return counts

    async def sync_server(self, server_id: uuid.UUID) -> int:
        server = await self._servers.get(server_id)
        if server is None or not server.enabled:
            return 0
        return await self._sync_one_mcp_server(server)

    async def _sync_native(self) -> int:
        db_tools = await self._tools.list_enabled(source="native")
        native_rows = [
            (t.id, t.name, t.description, t.input_schema) for t in db_tools
        ]
        provider = build_default_native_provider(native_rows)
        # Native tools are code-defined and win over MCP duplicates (get_time, …).
        await self._registry.sync_provider_tools(provider, on_collision="replace")

        count = 0
        for descriptor in await provider.discover_tools():
            await self._tools.upsert_from_discovery(
                name=descriptor.name,
                source="native",
                provider_slug="native",
                description=descriptor.description,
                input_schema=descriptor.input_schema,
                mcp_server_id=None,
                module=None,
            )
            count += 1
        return count

    async def _sync_mcp_servers(self) -> int:
        servers = await self._servers.list_enabled()
        total = 0
        for server in servers:
            total += await self._sync_one_mcp_server(server)
        return total

    async def _sync_one_mcp_server(self, server) -> int:
        db_tools = await self._tools.list_enabled(mcp_server_id=server.id)
        db_ids = {t.name: t.id for t in db_tools}
        provider = build_mcp_provider(server, db_tool_ids=db_ids)
        try:
            discovered = await provider.discover_tools()
        except Exception as exc:
            logger.warning(
                "MCP tool discovery failed for %s (%s): %s",
                server.slug,
                server.base_url,
                exc,
            )
            health = await provider.health()
            health.message = str(exc)
            await self._servers.update_health(
                server.id,
                {
                    "healthy": False,
                    "message": str(exc),
                    "details": health.details,
                },
            )
            await self._registry.remove_provider(server.slug)
            return 0

        # Skip names already owned by native (or another MCP).
        await self._registry.sync_provider_tools(provider, on_collision="skip")
        registered = {
            d.name
            for d in self._registry.list_descriptors(provider_id=server.slug)
        }
        active_names: list[str] = []
        for descriptor in discovered:
            if descriptor.name not in registered:
                # Owned by another provider (typically native) — keep DB row but
                # do not claim the invoke key.
                continue
            await self._tools.upsert_from_discovery(
                name=descriptor.name,
                source="mcp",
                provider_slug=server.slug,
                description=descriptor.description,
                input_schema=descriptor.input_schema,
                mcp_server_id=server.id,
                module=descriptor.module,
            )
            active_names.append(descriptor.name)

        await self._tools.disable_stale_for_server(server.id, active_names)
        health = await provider.health()
        await self._servers.update_health(
            server.id,
            {
                "healthy": health.healthy,
                "message": health.message,
                "details": health.details,
                "tool_count": len(active_names),
            },
        )

        return len(active_names)


async def build_providers_from_db(
    db: AsyncSession,
    registry: ToolRegistry,
) -> ToolPlatformState:
    """Load all providers into the registry from DB configuration."""
    from src.tools.lifecycle.bootstrap import ToolPlatformState

    servers_repo = McpServerRepository(db)
    tools_repo = ToolDefinitionRepository(db)
    state = ToolPlatformState(registry=registry)

    db_native = await tools_repo.list_enabled(source="native")
    native_rows = [(t.id, t.name, t.description, t.input_schema) for t in db_native]
    native = build_default_native_provider(native_rows)
    await registry.sync_provider_tools(native)
    state.native_provider = native

    for server in await servers_repo.list_enabled():
        db_tools = await tools_repo.list_enabled(mcp_server_id=server.id)
        provider = build_mcp_provider(
            server,
            db_tool_ids={t.name: t.id for t in db_tools},
        )
        state.mcp_providers[server.slug] = provider
        try:
            await registry.sync_provider_tools(provider, on_collision="skip")
        except Exception:
            pass

    return state

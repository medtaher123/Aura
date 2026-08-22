"""Bootstrap and lifecycle management for the tool platform."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from src.core.logger import get_logger
from src.core.singleton_meta import SingletonMeta
from src.db.database import AsyncSessionLocal
from src.db.repositories.tool_platform import McpServerRepository
from src.tools.platform.gateway import ToolGateway, get_tool_gateway
from src.tools.platform.mcp_provider import McpToolProvider
from src.tools.platform.native_provider import NativeToolProvider
from src.tools.platform.registry import ToolRegistry
from src.tools.platform.external_mcp import ExternalMcpReconciler
from src.tools.platform.sync import ToolCatalogSyncService, build_providers_from_db

logger = get_logger("tool_platform")


@dataclass
class ToolPlatformState:
    registry: ToolRegistry
    native_provider: NativeToolProvider | None = None
    mcp_providers: dict[str, McpToolProvider] = field(default_factory=dict)
    _health_task: asyncio.Task[None] | None = None


class ToolPlatformBootstrap(metaclass=SingletonMeta):
    """Factory that wires providers from DB config and env fallbacks."""

    def __init__(self) -> None:
        self._state: ToolPlatformState | None = None
        self._gateway: ToolGateway | None = None

    @property
    def state(self) -> ToolPlatformState | None:
        return self._state

    @property
    def gateway(self) -> ToolGateway:
        if self._gateway is None:
            self._gateway = get_tool_gateway()
        return self._gateway

    async def startup(self) -> None:
        if self._state and self._state._health_task:
            self._state._health_task.cancel()
            try:
                await self._state._health_task
            except asyncio.CancelledError:
                pass

        async with AsyncSessionLocal() as db:
            # Metaplanet MCP from app config; external MCPs from YAML.
            await ExternalMcpReconciler().reconcile(db)

            registry = ToolRegistry()
            self._state = await build_providers_from_db(db, registry)
            sync = ToolCatalogSyncService(db, registry)
            try:
                counts = await sync.sync_all()
                logger.info(
                    "Tool catalog synced: %d MCP tools, %d native tools",
                    counts["mcp_tools"],
                    counts["native_tools"],
                )
            except Exception as exc:
                logger.warning("Tool catalog sync partial failure: %s", exc)

            self._gateway = ToolGateway(registry)
            get_tool_gateway().configure(registry)

        self._state._health_task = asyncio.create_task(self._health_loop())

    async def shutdown(self) -> None:
        if self._state and self._state._health_task:
            self._state._health_task.cancel()
            try:
                await self._state._health_task
            except asyncio.CancelledError:
                pass

    async def reload(self) -> dict[str, Any]:
        async with AsyncSessionLocal() as db:
            registry = ToolRegistry()
            self._state = await build_providers_from_db(db, registry)
            sync = ToolCatalogSyncService(db, registry)
            counts = await sync.sync_all()
            self._gateway = ToolGateway(registry)
            get_tool_gateway().configure(registry)
            return counts

    async def _health_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                if self._gateway is None or self._state is None:
                    continue
                async with AsyncSessionLocal() as db:
                    servers_repo = McpServerRepository(db)
                    for server in await servers_repo.list_enabled():
                        provider = self._state.mcp_providers.get(server.slug)
                        if provider is None:
                            continue
                        health = await provider.health()
                        registered = self._state.registry.list_descriptors(
                            provider_id=server.slug
                        )
                        # Re-discover when MCP is up but the in-memory catalog is empty
                        # (e.g. discovery failed at startup, or MCP came online later).
                        if health.healthy and not registered:
                            logger.info(
                                "MCP provider %s healthy with empty registry; re-syncing",
                                server.slug,
                            )
                            sync = ToolCatalogSyncService(db, self._state.registry)
                            synced = await sync.sync_server(server.id)
                            health = await provider.health()
                            health.tool_count = synced
                        await servers_repo.update_health(
                            server.id,
                            {
                                "healthy": health.healthy,
                                "message": health.message,
                                "details": health.details,
                                "tool_count": health.tool_count,
                            },
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("Health loop error: %s", exc)


def get_tool_platform() -> ToolPlatformBootstrap:
    return ToolPlatformBootstrap()

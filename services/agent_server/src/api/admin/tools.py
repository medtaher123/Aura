"""Admin API for MCP servers and tools.

Metaplanet MCP is first-party (``MCP_SERVER_URL`` / app config). Additional MCP
servers come from the external MCP YAML config. This API lists servers, toggles
``enabled``, and probes/syncs health. Module dashboard proxy is Metaplanet-only.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.admin.deps import require_admin_user
from src.db.database import get_db
from src.db.models.mcp_server import McpServer
from src.db.models.user import User
from src.db.repositories.tool_platform import (
    McpServerRepository,
    ToolDefinitionRepository,
)
from src.tools.platform.bootstrap import get_tool_platform
from src.tools.platform.factory import build_mcp_provider
from src.tools.platform.gateway import get_tool_gateway
from src.tools.platform.metaplanet_provider import MetaplanetMcpProvider
from src.tools.platform.schemas import (
    AdminDashboardResponse,
    McpServerEnabledUpdate,
    McpServerRead,
    ToolDefinitionDetail,
    ToolDefinitionRead,
)
from src.tools.platform.sync import ToolCatalogSyncService

router = APIRouter(prefix="/admin", tags=["admin"])


def _server_read(server: McpServer, tool_count: int = 0) -> McpServerRead:
    return McpServerRead(
        id=server.id,
        slug=server.slug,
        display_name=server.display_name,
        base_url=server.base_url,
        transport=server.transport,
        enabled=server.enabled,
        is_primary=server.is_primary,
        stdio_config=dict(server.stdio_config or {}),
        last_health_at=server.last_health_at,
        last_health_status=server.last_health_status,
        created_at=server.created_at,
        tool_count=tool_count,
    )


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> AdminDashboardResponse:
    servers_repo = McpServerRepository(db)
    tools_repo = ToolDefinitionRepository(db)

    servers = await servers_repo.list()
    tools = await tools_repo.list_enabled()

    tool_counts: dict[uuid.UUID, int] = {}
    for tool in tools:
        if tool.mcp_server_id is not None:
            tool_counts[tool.mcp_server_id] = tool_counts.get(tool.mcp_server_id, 0) + 1

    provider_health = [
        {
            "provider_id": h.provider_id,
            "healthy": h.healthy,
            "message": h.message,
            "tool_count": h.tool_count,
            "details": h.details,
        }
        for h in await get_tool_gateway().health_all()
    ]

    return AdminDashboardResponse(
        timestamp=datetime.now(timezone.utc),
        mcp_servers=[
            _server_read(s, tool_counts.get(s.id, 0)) for s in servers
        ],
        tools_total=len(tools),
        tools_native=sum(1 for t in tools if t.source == "native"),
        tools_mcp=sum(1 for t in tools if t.source == "mcp"),
        provider_health=provider_health,
    )


@router.get("/mcp-servers", response_model=list[McpServerRead])
async def list_mcp_servers(
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[McpServerRead]:
    servers_repo = McpServerRepository(db)
    tools_repo = ToolDefinitionRepository(db)
    servers = await servers_repo.list()
    out: list[McpServerRead] = []
    for server in servers:
        count = len(await tools_repo.list_enabled(mcp_server_id=server.id))
        out.append(_server_read(server, count))
    return out


@router.patch("/mcp-servers/{server_id}/enabled", response_model=McpServerRead)
async def set_mcp_server_enabled(
    server_id: uuid.UUID,
    payload: McpServerEnabledUpdate,
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> McpServerRead:
    """Enable or disable an MCP server."""
    repo = McpServerRepository(db)
    tools_repo = ToolDefinitionRepository(db)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    server.enabled = payload.enabled
    await repo.commit()
    await repo.refresh(server)
    # Keep tool rows in sync with the server so catalogs/UI reflect availability.
    await tools_repo.set_enabled_for_server(server.id, enabled=payload.enabled)
    await get_tool_platform().reload()
    count = len(await tools_repo.list_enabled(mcp_server_id=server.id))
    return _server_read(server, count)


@router.post("/mcp-servers/{server_id}/sync")
async def sync_mcp_server(
    server_id: uuid.UUID,
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    sync = ToolCatalogSyncService(db, get_tool_gateway().registry)
    count = await sync.sync_server(server_id)
    await get_tool_platform().reload()
    return {"tools_synced": count}


@router.post("/mcp-servers/{server_id}/health")
async def probe_mcp_server_health(
    server_id: uuid.UUID,
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = McpServerRepository(db)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    provider = build_mcp_provider(server)
    health = await provider.health()
    await repo.update_health(
        server.id,
        {
            "healthy": health.healthy,
            "message": health.message,
            "details": health.details,
            "tool_count": health.tool_count,
        },
    )
    return {
        "healthy": health.healthy,
        "message": health.message,
        "details": health.details,
        "tool_count": health.tool_count,
    }


@router.get("/mcp-servers/{server_id}/modules")
async def proxy_mcp_server_modules(
    server_id: uuid.UUID,
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Proxy Metaplanet MCP module dashboard (not available on generic MCP servers)."""
    repo = McpServerRepository(db)
    server = await repo.get(server_id)
    if server is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    provider = build_mcp_provider(server)
    if not isinstance(provider, MetaplanetMcpProvider):
        raise HTTPException(
            status_code=400,
            detail="Module dashboard is only available for Metaplanet MCP",
        )
    payload = await provider.fetch_management_modules()
    if payload is None:
        raise HTTPException(
            status_code=502,
            detail="MCP server management API unavailable",
        )
    return payload


@router.get("/tools", response_model=list[ToolDefinitionRead])
async def list_tools(
    source: Optional[str] = Query(default=None),
    mcp_server_id: Optional[uuid.UUID] = Query(default=None),
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> list[ToolDefinitionRead]:
    repo = ToolDefinitionRepository(db)
    tools = await repo.list_enabled(source=source, mcp_server_id=mcp_server_id)
    return [ToolDefinitionRead.model_validate(t) for t in tools]


@router.get("/tools/{tool_id}", response_model=ToolDefinitionDetail)
async def get_tool(
    tool_id: uuid.UUID,
    _admin: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ToolDefinitionDetail:
    repo = ToolDefinitionRepository(db)
    tool = await repo.get(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return ToolDefinitionDetail.model_validate(tool)

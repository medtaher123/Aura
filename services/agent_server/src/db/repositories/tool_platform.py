"""Persistence layer for the tool platform."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models.agent_profile import AgentProfile, AgentToolBinding
from src.db.models.mcp_server import McpServer
from src.db.models.tool_definition import ToolDefinition
from src.db.repositories.base import BaseRepository


class McpServerRepository(BaseRepository[McpServer]):
    model = McpServer

    async def get_by_slug(self, slug: str) -> Optional[McpServer]:
        stmt = select(McpServer).where(McpServer.slug == slug)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_enabled(self) -> list[McpServer]:
        stmt = (
            select(McpServer)
            .where(McpServer.enabled.is_(True))
            .order_by(McpServer.is_primary.desc(), McpServer.slug)
        )
        return await self.list(statement=stmt)

    async def get_primary(self) -> Optional[McpServer]:
        stmt = select(McpServer).where(McpServer.is_primary.is_(True)).limit(1)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_primary(
        self,
        *,
        base_url: str,
        slug: str = "metaplanet",
        display_name: str = "Metaplanet MCP",
    ) -> McpServer:
        existing = await self.get_by_slug(slug)
        if existing is not None:
            if existing.base_url != base_url:
                existing.base_url = base_url
                await self.commit()
                await self.refresh(existing)
            return existing

        await self.db.execute(
            select(McpServer).where(McpServer.is_primary.is_(True))
        )
        entity = McpServer(
            id=uuid.uuid4(),
            slug=slug,
            display_name=display_name,
            base_url=base_url.rstrip("/"),
            transport="streamable_http",
            auth_headers={},
            enabled=True,
            is_primary=True,
        )
        return await self.add(entity)

    async def update_health(
        self,
        server_id: uuid.UUID,
        status: dict[str, Any],
    ) -> None:
        entity = await self.get(server_id)
        if entity is None:
            return
        entity.last_health_at = datetime.now(timezone.utc)
        entity.last_health_status = status
        await self.commit()


class ToolDefinitionRepository(BaseRepository[ToolDefinition]):
    model = ToolDefinition

    async def get_by_name(self, name: str) -> Optional[ToolDefinition]:
        stmt = select(ToolDefinition).where(ToolDefinition.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_enabled(
        self,
        *,
        source: Optional[str] = None,
        mcp_server_id: Optional[uuid.UUID] = None,
    ) -> list[ToolDefinition]:
        """Return enabled tools, excluding those whose MCP server is disabled."""
        from sqlalchemy import or_

        stmt = (
            select(ToolDefinition)
            .outerjoin(McpServer, ToolDefinition.mcp_server_id == McpServer.id)
            .where(ToolDefinition.enabled.is_(True))
            .where(
                or_(
                    ToolDefinition.mcp_server_id.is_(None),
                    McpServer.enabled.is_(True),
                )
            )
        )
        if source is not None:
            stmt = stmt.where(ToolDefinition.source == source)
        if mcp_server_id is not None:
            stmt = stmt.where(ToolDefinition.mcp_server_id == mcp_server_id)
        stmt = stmt.order_by(ToolDefinition.name)
        return await self.list(statement=stmt)

    async def set_enabled_for_server(
        self,
        mcp_server_id: uuid.UUID,
        *,
        enabled: bool,
    ) -> int:
        """Flip ``enabled`` for every tool belonging to an MCP server."""
        stmt = select(ToolDefinition).where(
            ToolDefinition.mcp_server_id == mcp_server_id,
            ToolDefinition.source == "mcp",
        )
        tools = await self.list(statement=stmt)
        count = 0
        for tool in tools:
            if tool.enabled != enabled:
                tool.enabled = enabled
                count += 1
        if count:
            await self.commit()
        return count

    async def upsert_from_discovery(
        self,
        *,
        name: str,
        source: str,
        provider_slug: str,
        description: str,
        input_schema: dict[str, Any],
        mcp_server_id: Optional[uuid.UUID] = None,
        module: Optional[str] = None,
    ) -> ToolDefinition:
        existing = await self.get_by_name(name)
        now = datetime.now(timezone.utc)
        if existing is not None:
            existing.source = source
            existing.provider_slug = provider_slug
            existing.description = description
            existing.input_schema = input_schema
            existing.mcp_server_id = mcp_server_id
            existing.module = module
            existing.enabled = True
            existing.discovered_at = existing.discovered_at or now
            existing.updated_at = now
            await self.commit()
            await self.refresh(existing)
            return existing

        entity = ToolDefinition(
            id=uuid.uuid4(),
            name=name,
            source=source,
            provider_slug=provider_slug,
            description=description,
            input_schema=input_schema,
            mcp_server_id=mcp_server_id,
            module=module,
            enabled=True,
            discovered_at=now,
            updated_at=now,
        )
        return await self.add(entity)

    async def disable_stale_for_server(
        self,
        mcp_server_id: uuid.UUID,
        active_names: Sequence[str],
    ) -> int:
        stmt = select(ToolDefinition).where(
            ToolDefinition.mcp_server_id == mcp_server_id,
            ToolDefinition.source == "mcp",
        )
        tools = await self.list(statement=stmt)
        active = set(active_names)
        count = 0
        for tool in tools:
            if tool.name not in active and tool.enabled:
                tool.enabled = False
                count += 1
        if count:
            await self.commit()
        return count


class AgentProfileRepository(BaseRepository[AgentProfile]):
    model = AgentProfile

    async def get_by_slug(self, slug: str) -> Optional[AgentProfile]:
        stmt = (
            select(AgentProfile)
            .where(AgentProfile.slug == slug)
            .options(
                selectinload(AgentProfile.tool_bindings).selectinload(
                    AgentToolBinding.tool_definition
                )
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_default(self) -> Optional[AgentProfile]:
        stmt = (
            select(AgentProfile)
            .where(AgentProfile.is_default.is_(True))
            .options(
                selectinload(AgentProfile.tool_bindings).selectinload(
                    AgentToolBinding.tool_definition
                )
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def allowed_tool_names(self, profile: AgentProfile) -> set[str]:
        return {
            binding.tool_definition.name
            for binding in profile.tool_bindings
            if binding.enabled and binding.tool_definition.enabled
        }

    async def replace_tool_bindings(
        self,
        profile_id: uuid.UUID,
        tool_ids: Sequence[uuid.UUID],
    ) -> AgentProfile:
        profile = await self.get(profile_id)
        if profile is None:
            raise ValueError(f"Agent profile not found: {profile_id}")

        profile.tool_bindings.clear()
        await self.flush()
        for tool_id in tool_ids:
            self.db.add(
                AgentToolBinding(
                    agent_profile_id=profile_id,
                    tool_definition_id=tool_id,
                    enabled=True,
                )
            )
        await self.commit()
        await self.refresh(profile)
        stmt = (
            select(AgentProfile)
            .where(AgentProfile.id == profile_id)
            .options(
                selectinload(AgentProfile.tool_bindings).selectinload(
                    AgentToolBinding.tool_definition
                )
            )
        )
        result = await self.db.execute(stmt)
        refreshed = result.scalar_one()
        return refreshed

    async def bind_tools_by_names(
        self,
        profile_id: uuid.UUID,
        tool_names: Sequence[str],
    ) -> None:
        if not tool_names:
            return
        stmt = select(ToolDefinition).where(ToolDefinition.name.in_(list(tool_names)))
        result = await self.db.execute(stmt)
        tools = list(result.scalars().all())
        existing = await self.get(profile_id)
        if existing is None:
            return
        bound_ids = {b.tool_definition_id for b in existing.tool_bindings}
        for tool in tools:
            if tool.id in bound_ids:
                continue
            self.db.add(
                AgentToolBinding(
                    agent_profile_id=profile_id,
                    tool_definition_id=tool.id,
                    enabled=True,
                )
            )
        await self.commit()

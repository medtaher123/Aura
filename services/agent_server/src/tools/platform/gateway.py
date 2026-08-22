"""Facade for tool discovery and invocation."""

from __future__ import annotations

from typing import Any

from src.core.singleton_meta import SingletonMeta
from src.tools.contracts import ToolResponse
from src.tools.platform.provider import ProviderHealth, ToolDescriptor
from src.tools.platform.registry import ToolRegistry


class ToolGateway(metaclass=SingletonMeta):
    """Single entry point for planners, executors, and admin APIs."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry or ToolRegistry()

    def configure(self, registry: ToolRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolResponse:
        provider = self._registry.get_provider_for_tool(tool_name)
        if provider is None:
            return ToolResponse(
                tool_name=tool_name,
                message=f"Tool not found in registry: {tool_name}",
                error=True,
            )
        return await provider.invoke(tool_name, arguments)

    async def get_metadata(self, tool_name: str) -> dict[str, Any]:
        return self._registry.get_metadata(tool_name)

    def list_tools(
        self,
        *,
        provider_id: str | None = None,
        source: str | None = None,
        allowed_names: set[str] | None = None,
    ) -> list[ToolDescriptor]:
        descriptors = self._registry.list_descriptors(
            provider_id=provider_id,
            source=source,
        )
        if allowed_names is not None:
            descriptors = [d for d in descriptors if d.name in allowed_names]
        return descriptors

    async def health_all(self) -> list[ProviderHealth]:
        results: list[ProviderHealth] = []
        for provider_id in self._registry.provider_ids:
            provider = self._registry.get_provider(provider_id)
            if provider is None:
                continue
            results.append(await provider.health())
        return results


def get_tool_gateway() -> ToolGateway:
    return ToolGateway()

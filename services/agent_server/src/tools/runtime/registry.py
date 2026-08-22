"""Central catalog of tool descriptors."""

from __future__ import annotations

import asyncio
from typing import Any

from src.tools.providers.base import ToolDescriptor, ToolProvider


class ToolRegistry:
    """Thread-safe registry mapping tool names to descriptors and providers."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tools: dict[str, ToolDescriptor] = {}
        self._providers: dict[str, ToolProvider] = {}
        self._tool_provider: dict[str, str] = {}

    async def register_provider(self, provider: ToolProvider) -> None:
        async with self._lock:
            self._providers[provider.provider_id] = provider

    async def sync_provider_tools(
        self,
        provider: ToolProvider,
        *,
        on_collision: str = "raise",
    ) -> list[ToolDescriptor]:
        """Register tools from ``provider``.

        ``on_collision``:
        - ``raise``: fail if another provider owns the name
        - ``skip``: keep the existing registration
        - ``replace``: overwrite with this provider's descriptor
        """
        if on_collision not in {"raise", "skip", "replace"}:
            raise ValueError(f"Invalid on_collision: {on_collision!r}")

        discovered = await provider.discover_tools()
        accepted: list[ToolDescriptor] = []
        async with self._lock:
            self._providers[provider.provider_id] = provider
            for descriptor in discovered:
                existing = self._tools.get(descriptor.name)
                if existing is not None and existing.provider_id != provider.provider_id:
                    if on_collision == "raise":
                        raise ValueError(
                            f"Tool name collision: {descriptor.name!r} "
                            f"({existing.provider_id} vs {provider.provider_id})"
                        )
                    if on_collision == "skip":
                        continue
                self._tools[descriptor.name] = descriptor
                self._tool_provider[descriptor.name] = provider.provider_id
                accepted.append(descriptor)
        return accepted

    async def remove_provider(self, provider_id: str) -> None:
        async with self._lock:
            self._providers.pop(provider_id, None)
            stale = [
                name
                for name, pid in self._tool_provider.items()
                if pid == provider_id
            ]
            for name in stale:
                self._tools.pop(name, None)
                self._tool_provider.pop(name, None)

    def get_descriptor(self, name: str) -> ToolDescriptor | None:
        return self._tools.get(name)

    def list_descriptors(
        self,
        *,
        provider_id: str | None = None,
        source: str | None = None,
        enabled_only: bool = True,
    ) -> list[ToolDescriptor]:
        out: list[ToolDescriptor] = []
        for descriptor in self._tools.values():
            if enabled_only and not descriptor.enabled:
                continue
            if provider_id is not None and descriptor.provider_id != provider_id:
                continue
            if source is not None and descriptor.source != source:
                continue
            out.append(descriptor)
        return sorted(out, key=lambda d: d.name)

    def get_provider(self, provider_id: str) -> ToolProvider | None:
        return self._providers.get(provider_id)

    def get_provider_for_tool(self, name: str) -> ToolProvider | None:
        provider_id = self._tool_provider.get(name)
        if provider_id is None:
            return None
        return self._providers.get(provider_id)

    def get_metadata(self, name: str) -> dict[str, Any]:
        descriptor = self._tools.get(name)
        if descriptor is None:
            return {"all_params": [], "required_params": [], "docstring": ""}

        schema = descriptor.input_schema or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = schema.get("required", []) if isinstance(schema, dict) else []
        return {
            "all_params": [str(k) for k in properties.keys()]
            if isinstance(properties, dict)
            else [],
            "required_params": [str(k) for k in required]
            if isinstance(required, list)
            else [],
            "docstring": descriptor.description,
            "input_schema": schema,
        }

    def update_descriptor(self, descriptor: ToolDescriptor) -> None:
        self._tools[descriptor.name] = descriptor
        self._tool_provider[descriptor.name] = descriptor.provider_id

    @property
    def provider_ids(self) -> list[str]:
        return sorted(self._providers.keys())

"""In-process native tool provider."""

from __future__ import annotations

import inspect
from typing import Any, Awaitable, Callable
from uuid import UUID

from src.tools.contracts import ToolResponse
from src.tools.native.base import NATIVE_INPUT_SCHEMA_ATTR
from src.tools.providers.base import ProviderHealth, ToolDescriptor, ToolProvider

NativeHandler = Callable[..., ToolResponse | Awaitable[ToolResponse]]


class NativeToolProvider(ToolProvider):
    """Executes tools registered in the agent_server process."""

    def __init__(self) -> None:
        self._provider_id = "native"
        self._handlers: dict[str, NativeHandler] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def register(
        self,
        name: str,
        handler: NativeHandler,
        *,
        description: str = "",
        input_schema: dict[str, Any] | None = None,
        tool_id: UUID | None = None,
    ) -> None:
        self._handlers[name] = handler
        if input_schema is not None:
            schema = input_schema
        else:
            schema = self._schema_from_handler(handler)
        self._schemas[name] = schema
        self._descriptions: dict[str, str] = getattr(self, "_descriptions", {})
        self._descriptions[name] = description or inspect.getdoc(handler) or ""
        self._tool_ids: dict[str, UUID | None] = getattr(self, "_tool_ids", {})
        self._tool_ids[name] = tool_id

    def _schema_from_handler(self, handler: NativeHandler) -> dict[str, Any]:
        sig = inspect.signature(handler)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in sig.parameters.values():
            if param.kind not in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            ):
                continue
            properties[param.name] = {"type": "string"}
            if param.default is inspect.Parameter.empty:
                required.append(param.name)
        return {"type": "object", "properties": properties, "required": required}

    async def discover_tools(self) -> list[ToolDescriptor]:
        descriptions = getattr(self, "_descriptions", {})
        tool_ids = getattr(self, "_tool_ids", {})
        return [
            ToolDescriptor(
                id=tool_ids.get(name),
                name=name,
                source="native",
                provider_id=self.provider_id,
                description=descriptions.get(name, ""),
                input_schema=self._schemas.get(name, {}),
                enabled=True,
            )
            for name in sorted(self._handlers.keys())
        ]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        handler = self._handlers.get(name)
        if handler is None:
            return ToolResponse(
                tool_name=name,
                message=f"Native tool not found: {name}",
                error=True,
            )
        try:
            sig = inspect.signature(handler)
            filtered = {
                key: value
                for key, value in arguments.items()
                if key in sig.parameters
            }
            result = handler(**filtered)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, ToolResponse):
                return result
            return ToolResponse(tool_name=name, message=str(result))
        except Exception as exc:
            return ToolResponse(
                tool_name=name,
                message=f"Native tool failed: {exc}",
                data={"arguments": arguments},
                error=True,
            )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider_id=self.provider_id,
            healthy=True,
            message="Native tools available",
            tool_count=len(self._handlers),
        )


def build_default_native_provider(
    db_tools: list[tuple[UUID | None, str, str, dict[str, Any]]] | None = None,
) -> NativeToolProvider:
    """Register every ``@native_tool`` found under ``src.tools.native``."""
    from src.tools.native.discover import discover_native_tools

    provider = NativeToolProvider()
    db_by_name = {
        name: (tid, desc, schema) for tid, name, desc, schema in (db_tools or [])
    }

    for name, handler, description in discover_native_tools():
        db_entry = db_by_name.get(name)
        schema = getattr(handler, NATIVE_INPUT_SCHEMA_ATTR, None)
        provider.register(
            name,
            handler,
            description=db_entry[1] if db_entry else description,
            input_schema=db_entry[2] if db_entry else schema,
            tool_id=db_entry[0] if db_entry else None,
        )
    return provider

"""Tests for the tool platform registry and providers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.tools.contracts import ToolResponse
from src.tools.providers.native import NativeToolProvider
from src.tools.providers.base import ProviderHealth, ToolDescriptor, ToolProvider
from src.tools.runtime.registry import ToolRegistry


class _StubProvider(ToolProvider):
    def __init__(self, provider_id: str, source: str) -> None:
        self._provider_id = provider_id
        self._source = source

    @property
    def provider_id(self) -> str:
        return self._provider_id

    async def discover_tools(self) -> list[ToolDescriptor]:
        return [
            ToolDescriptor(
                id=None,
                name="shared_tool",
                source=self._source,  # type: ignore[arg-type]
                provider_id=self._provider_id,
                description="",
                input_schema={},
            )
        ]

    async def invoke(self, name: str, arguments: dict[str, Any]) -> ToolResponse:
        return ToolResponse(tool_name=name, message=self._provider_id)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(provider_id=self._provider_id, healthy=True)


@pytest.mark.asyncio
async def test_registry_detects_tool_name_collision():
    registry = ToolRegistry()

    await registry.sync_provider_tools(_StubProvider("a", "native"))
    with pytest.raises(ValueError, match="collision"):
        await registry.sync_provider_tools(_StubProvider("b", "mcp"))


@pytest.mark.asyncio
async def test_registry_skip_collisions_keeps_existing():
    registry = ToolRegistry()

    await registry.sync_provider_tools(_StubProvider("native", "native"))
    await registry.sync_provider_tools(
        _StubProvider("metaplanet", "mcp"), on_collision="skip"
    )
    descriptor = registry.get_descriptor("shared_tool")
    assert descriptor is not None
    assert descriptor.provider_id == "native"


@pytest.mark.asyncio
async def test_registry_replace_collisions_prefers_new_provider():
    registry = ToolRegistry()

    await registry.sync_provider_tools(_StubProvider("native", "native"))
    await registry.sync_provider_tools(
        _StubProvider("metaplanet", "mcp"), on_collision="replace"
    )
    descriptor = registry.get_descriptor("shared_tool")
    assert descriptor is not None
    assert descriptor.provider_id == "metaplanet"
    assert registry.get_provider_for_tool("shared_tool").provider_id == "metaplanet"


def test_providers_subclass_tool_provider():
    from src.tools.providers.mcp import McpToolProvider

    assert issubclass(NativeToolProvider, ToolProvider)
    assert issubclass(McpToolProvider, ToolProvider)
    from src.tools.providers.metaplanet import MetaplanetMcpProvider

    assert issubclass(MetaplanetMcpProvider, McpToolProvider)


@pytest.mark.asyncio
async def test_native_provider_invokes_calculator():
    provider = NativeToolProvider()

    async def calculator(expression: str) -> ToolResponse:
        return ToolResponse(tool_name="calculator", message="42", data={"result": "42"})

    provider.register("calculator", calculator, description="calc")
    result = await provider.invoke("calculator", {"expression": "6*7"})
    assert result.error is False
    assert result.message == "42"


@pytest.mark.asyncio
async def test_gateway_invoke_routes_to_provider():
    from src.tools.runtime.gateway import get_tool_gateway

    registry = ToolRegistry()
    provider = NativeToolProvider()

    async def get_time() -> ToolResponse:
        return ToolResponse(tool_name="get_time", message="12h00")

    provider.register("get_time", get_time)
    await registry.sync_provider_tools(provider)

    gateway = get_tool_gateway()
    gateway.configure(registry)
    result = await gateway.invoke("get_time", {})
    assert result.message == "12h00"


@pytest.mark.asyncio
async def test_mcp_provider_passes_auth_via_http_client(monkeypatch):
    """MCP SDK v2 rejects headers= on streamable_http_client; use http_client."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from src.tools.providers.mcp import McpToolProvider

    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_create_mcp_http_client(headers=None, timeout=None, auth=None):
        captured["client_headers"] = headers
        yield object()

    @asynccontextmanager
    async def fake_streamable_http_client(url, *, http_client=None, terminate_on_close=True):
        captured["url"] = url
        captured["http_client"] = http_client
        yield (object(), object(), lambda: None)

    class FakeSession:
        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="detect_fire_tool",
                        description="fires",
                        input_schema={"type": "object", "properties": {}},
                    )
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    def fake_client_session(read, write):
        return FakeSession()

    import mcp.client.streamable_http as streamable_http_mod
    import mcp as mcp_mod

    monkeypatch.setattr(
        streamable_http_mod, "create_mcp_http_client", fake_create_mcp_http_client
    )
    monkeypatch.setattr(
        streamable_http_mod, "streamable_http_client", fake_streamable_http_client
    )
    monkeypatch.setattr(mcp_mod, "ClientSession", fake_client_session)

    provider = McpToolProvider(
        provider_id="metaplanet",
        base_url="http://mcp-server:8000",
        auth_headers={"Authorization": "Bearer t"},
    )
    tools = await provider.discover_tools()
    assert [t.name for t in tools] == ["detect_fire_tool"]
    assert captured["url"] == "http://mcp-server:8000/mcp"
    assert captured["client_headers"] == {"Authorization": "Bearer t"}
    assert captured["http_client"] is not None



@pytest.mark.asyncio
async def test_mcp_provider_stdio_session(monkeypatch):
    """stdio transport opens StdioServerParameters + stdio_client."""
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from src.tools.providers.mcp import McpToolProvider

    captured: dict[str, Any] = {}

    @asynccontextmanager
    async def fake_stdio_client(params):
        captured["params"] = params
        yield (object(), object())

    class FakeSession:
        async def initialize(self):
            return None

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    SimpleNamespace(
                        name="geocode_address",
                        description="geocode",
                        input_schema={"type": "object"},
                    )
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    def fake_client_session(read, write):
        return FakeSession()

    import shutil

    import mcp as mcp_mod
    import mcp.client.stdio as stdio_mod

    monkeypatch.setattr(stdio_mod, "stdio_client", fake_stdio_client)
    monkeypatch.setattr(mcp_mod, "ClientSession", fake_client_session)
    monkeypatch.setattr(
        shutil,
        "which",
        lambda cmd: f"/usr/bin/{cmd}" if cmd == "npx" else None,
    )

    provider = McpToolProvider(
        provider_id="immo-france",
        transport="stdio",
        stdio_config={"command": "npx", "args": ["-y", "mcp-immo-france"], "env": {}},
    )
    tools = await provider.discover_tools()
    assert [t.name for t in tools] == ["geocode_address"]
    assert captured["params"].command == "/usr/bin/npx"
    assert list(captured["params"].args) == ["-y", "mcp-immo-france"]
    # Empty env must inherit the parent process (None), not wipe PATH.
    assert captured["params"].env is None


@pytest.mark.asyncio
async def test_mcp_provider_health_uses_list_tools(monkeypatch):
    """Generic MCP health probes list_tools, not HTTP /health."""
    from types import SimpleNamespace

    from src.tools.providers.mcp import McpToolProvider

    provider = McpToolProvider(
        provider_id="ign-geocontext",
        base_url="https://geollm.beta.ign.fr/geocontext",
    )

    async def fake_list_tools():
        return SimpleNamespace(tools=[SimpleNamespace(name="geocode")])

    monkeypatch.setattr(provider, "_list_tools_async", fake_list_tools)
    health = await provider.health()
    assert health.healthy is True
    assert health.tool_count == 1
    assert health.details["probe"] == "list_tools"


@pytest.mark.asyncio
async def test_metaplanet_health_uses_http_endpoint(monkeypatch):
    from src.tools.providers.metaplanet import MetaplanetMcpProvider
    from src.tools.providers.base import ProviderHealth

    provider = MetaplanetMcpProvider(base_url="http://localhost:8000")

    class FakeResponse:
        status_code = 200
        content = b'{"status":"healthy","tools_loaded":3}'

        def json(self):
            return {"status": "healthy", "tools_loaded": 3}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            assert url.endswith("/health")
            return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    health = await provider.health()
    assert health.healthy is True
    assert health.tool_count == 3
    assert health.details["probe"] == "http_health"


@pytest.mark.asyncio
async def test_metaplanet_discover_enriches_module_from_dashboard(monkeypatch):
    from types import SimpleNamespace

    from src.tools.providers.metaplanet import MetaplanetMcpProvider

    provider = MetaplanetMcpProvider(base_url="http://localhost:8000")

    async def fake_list_tools():
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="get_terrazard_flood_briefing_tool",
                    description="briefing",
                    input_schema={"type": "object", "properties": {}},
                ),
                SimpleNamespace(
                    name="detect_fire_tool",
                    description="fire",
                    input_schema={"type": "object", "properties": {}},
                    meta={"module": "hazards"},
                ),
            ]
        )

    async def fake_modules():
        return {
            "modules": [
                {
                    "name": "flood",
                    "registered_tools": ["get_terrazard_flood_briefing_tool"],
                },
                {
                    "name": "hazards",
                    "registered_tools": ["detect_fire_tool"],
                },
            ]
        }

    monkeypatch.setattr(provider, "_list_tools_async", fake_list_tools)
    monkeypatch.setattr(provider, "fetch_management_modules", fake_modules)

    tools = await provider.discover_tools()
    by_name = {t.name: t for t in tools}
    assert by_name["get_terrazard_flood_briefing_tool"].module == "flood"
    # Explicit MCP meta wins / stays set.
    assert by_name["detect_fire_tool"].module == "hazards"


def test_resolve_allowed_tools_intersects_profile():
    from types import SimpleNamespace

    from src.tools.filtering.agent_filter import resolve_allowed_tools

    domain_tools = ["a", "b", "c"]
    binding = SimpleNamespace(
        enabled=True,
        tool_definition=SimpleNamespace(name="b", enabled=True),
    )
    profile = SimpleNamespace(tool_bindings=[binding])
    assert resolve_allowed_tools(domain_tools, profile) == ["b"]


def test_resolve_allowed_tools_without_bindings():
    from src.tools.filtering.agent_filter import resolve_allowed_tools

    domain_tools = ["a", "b"]
    profile = SimpleNamespace(tool_bindings=[])
    assert resolve_allowed_tools(domain_tools, profile) == ["a", "b"]


def test_discover_native_tools_scans_package():
    from src.tools.native.discover import discover_native_tools

    names = [name for name, _, _ in discover_native_tools()]
    assert names == [
        "calculator",
        "get_date",
        "get_time",
        "request_bounding_box_user_input",
        "request_location_user_input",
        "request_multiple_choice_user_input",
        "wait",
    ]


@pytest.mark.asyncio
async def test_build_default_native_provider_registers_discovered_tools():
    from src.tools.providers.native import build_default_native_provider

    provider = build_default_native_provider()
    tools = await provider.discover_tools()
    names = {t.name for t in tools}
    assert names == {
        "calculator",
        "get_date",
        "get_time",
        "request_bounding_box_user_input",
        "request_location_user_input",
        "request_multiple_choice_user_input",
        "wait",
    }

    result = await provider.invoke("calculator", {"expression": "2+3"})
    assert result.error is False
    assert result.message == "5"

    waited = await provider.invoke("wait", {"seconds": 0})
    assert waited.error is False
    assert waited.data["seconds"] == 0
    assert "Waited 0" in waited.message

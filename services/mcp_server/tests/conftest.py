"""Pytest configuration and fixtures for MCP server tests."""

import os
import sys
import asyncio
from pathlib import Path

import pytest
from starlette.testclient import TestClient

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


# Ensure required settings are present during tests.
# These are required in production, but unit tests should not depend on
# external secrets or environment configuration.
os.environ.setdefault("OPENTOPO_API_KEY", "test-opentopo-api-key")
os.environ.setdefault("MAP_KEY", "test-map-key")
os.environ.setdefault("GEOSERVER_BASE_URL", "https://example.invalid/geoserver")
os.environ.setdefault("TERRAZARD_TILE_SERVER_URL", "https://tiles.example.invalid")
os.environ.setdefault("TERRAZARD_DEFAULT_MODEL", "flood80")


from mcp_singleton import mcp
from config import get_config


# Configure pytest to handle async tests
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


class MockMCPClient:
    """Mock MCP client for testing tools."""

    def __init__(self, mcp_instance):
        self.mcp = mcp_instance

    async def call_tool(self, tool_name: str, arguments: dict = None):
        """Call a tool by name with given arguments."""
        if arguments is None:
            arguments = {}

        result = await self.mcp.call_tool(tool_name, arguments)

        if isinstance(result, tuple) and len(result) == 2:
            text_contents, result_dict = result
            return result_dict

        import json

        if result and len(result) > 0 and hasattr(result[0], "text"):
            return json.loads(result[0].text)

        return result

    async def list_tools(self):
        """List all available tools."""
        tools_result = await self.mcp.list_tools()

        tools_list = []
        for tool in tools_result:
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                }
            )
        return tools_list


@pytest.fixture(scope="session")
def bootstrapped_app():
    """Import main to run module discovery + tool registration once per session."""
    import main

    return main.app


@pytest.fixture
def mcp_client(bootstrapped_app):
    """MCP client fixture for testing tools."""
    return MockMCPClient(mcp)


@pytest.fixture
def mcp_server(bootstrapped_app):
    """MCPServer instance fixture."""
    return mcp


@pytest.fixture
def config():
    """MCP server configuration fixture."""
    return get_config()


@pytest.fixture
def sample_tool_call():
    """Sample tool call payload for testing."""
    return {"name": "get_time", "arguments": {}}


@pytest.fixture
def sample_city_bbox_call():
    """Sample bbox tool call for testing."""
    return {
        "name": "infrastructure_query_tool",
        "arguments": {"location": "Paris", "radius_km": 10},
    }


@pytest.fixture
def client(bootstrapped_app):
    """HTTP test client for management API + Streamable HTTP."""
    return TestClient(bootstrapped_app)

"""Pytest configuration and fixtures for MCP server tests."""

import os
import asyncio

import pytest
from starlette.testclient import TestClient


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
        # Import tools to ensure they're registered
        import tools  # noqa: F401

    async def call_tool(self, tool_name: str, arguments: dict = None):
        """Call a tool by name with given arguments."""
        if arguments is None:
            arguments = {}

        # Use FastMCP's built-in call_tool method
        # Returns a list of TextContent objects (most tools)
        # OR a tuple ([TextContent...], dict) for some tools like geoserver
        result = await self.mcp.call_tool(tool_name, arguments)

        # Handle tuple case (geoserver_risk_mask_tool returns tuple)
        if isinstance(result, tuple) and len(result) == 2:
            text_contents, result_dict = result
            return result_dict

        # Handle list of TextContent objects (most tools)
        import json

        if result and len(result) > 0 and hasattr(result[0], "text"):
            return json.loads(result[0].text)

        return result

    async def list_tools(self):
        """List all available tools."""
        # Use FastMCP's built-in list_tools method
        tools_result = await self.mcp.list_tools()

        # tools_result is already a list of Tool objects
        tools_list = []
        for tool in tools_result:
            tools_list.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                }
            )
        return tools_list


@pytest.fixture
def mcp_client():
    """MCP client fixture for testing tools."""
    return MockMCPClient(mcp)


@pytest.fixture
def mcp_server():
    """FastMCP server instance fixture."""
    # Import tools to ensure they're registered
    import tools  # noqa: F401

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
    return {"name": "infrastructure_query_tool", "arguments": {"location": "Paris", "radius_km": 10}}


@pytest.fixture
def client():
    """HTTP test client for testing FastMCP HTTP endpoints."""
    # Import server to ensure routes are registered
    import server  # noqa: F401

    # Get the ASGI app from FastMCP (call the method)
    app = mcp.streamable_http_app()
    return TestClient(app)

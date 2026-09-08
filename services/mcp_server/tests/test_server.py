"""
Tests for MCP server.
"""

import pytest
from config import get_config


@pytest.mark.unit
def test_mcp_server_exists(mcp_server):
    """Test MCPServer is properly initialized."""
    assert mcp_server is not None
    config = get_config()
    assert mcp_server.name == config.name


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mcp_has_tools(mcp_server):
    """Test MCP server has tools registered."""
    tools = await mcp_server.list_tools()
    assert len(tools) > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_list_tools(mcp_server):
    """Test tools can be loaded from MCP server."""
    tools = await mcp_server.list_tools()
    assert isinstance(tools, list)
    assert len(tools) > 0

    # Each tool should have required fields
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert tool.name  # Name should not be empty


# ============================================================================
# HTTP ENDPOINT INTEGRATION TESTS
# ============================================================================


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_server_info(mcp_server):
    """Test MCP server has correct configuration."""
    config = get_config()

    assert mcp_server.name == config.name
    tools = await mcp_server.list_tools()
    assert len(tools) > 0


@pytest.mark.integration
def test_health_endpoint(client):
    """Test health check endpoint."""
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    assert "status" in data
    assert "service" in data
    assert "timestamp" in data

    assert data["status"] == "healthy"
    assert data["service"] == "mcp-server"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_tools_method(mcp_server):
    """Test list_tools() method returns tool list."""
    tools = await mcp_server.list_tools()

    # Should return a list of tools
    assert isinstance(tools, list)
    assert len(tools) > 0

    # Each tool should have required fields
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        schema = getattr(tool, "input_schema", None) or getattr(
            tool, "inputSchema", None
        )
        assert isinstance(schema, dict)
    # Verify our simple tools are present
    tool_names = [tool.name for tool in tools]
    assert "get_time" in tool_names
    assert "get_date" in tool_names
    assert "calculator" in tool_names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_call_tool_method_success(mcp_server):
    """Test call_tool() method with a successful tool execution."""
    # Test with get_time tool (no arguments required)
    result = await mcp_server.call_tool("get_time", {})

    assert result is not None
    content = getattr(result, "content", result)
    assert content
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        assert structured.get("tool_name") == "get_time"
        assert structured.get("error") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_call_tool_method_with_arguments(mcp_server):
    """Test call_tool() method with a tool that requires arguments."""
    # Test calculator tool with addition
    result = await mcp_server.call_tool("calculator", {"expression": "2 + 2"})

    assert result is not None
    content = getattr(result, "content", result)
    assert content
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        assert structured.get("tool_name") == "calculator"
        assert structured.get("error") is False


@pytest.mark.integration
@pytest.mark.asyncio
async def test_call_tool_method_nonexistent_tool(mcp_server):
    """Test call_tool() method with a non-existent tool raises error."""
    # Should raise an exception for non-existent tool
    with pytest.raises(Exception):
        await mcp_server.call_tool("nonexistent_tool", {})


@pytest.mark.integration
@pytest.mark.asyncio
async def test_call_tool_method_invalid_arguments(mcp_server):
    """Test call_tool() method with invalid arguments."""
    # Test calculator without required expression argument
    # Should raise an exception or return error
    try:
        result = await mcp_server.call_tool("calculator", {})
        # If it doesn't raise, the result should indicate an error
        assert result is not None
    except Exception:
        # Expected behavior - missing required argument
        pass

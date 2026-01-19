"""
Tests for itinerary/route tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_route_info_exists(mcp_client):
    """Test route info tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "get_route_info" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_get_route_info_with_cities(mcp_client):
    """Test route tool accepts source and destination."""
    result = await mcp_client.call_tool(
        "get_route_info", {"source": "Paris", "destination": "Lyon"}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_get_route_info_structure(mcp_client):
    """Test route tool returns proper structure."""
    result = await mcp_client.call_tool(
        "get_route_info", {"source": "London", "destination": "Manchester"}
    )
    assert isinstance(result, dict)
    assert "message" in result
    # Should have route information or error
    assert "data" in result or "error" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_get_route_info_error_handling(mcp_client):
    """Test route tool handles invalid locations."""
    # Invalid source
    result = await mcp_client.call_tool(
        "get_route_info", {"source": "InvalidCity12345XYZ", "destination": "Paris"}
    )
    assert isinstance(result, dict)

    # Missing parameters - should handle gracefully
    result = await mcp_client.call_tool("get_route_info", {})
    assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_get_route_info_backward_compatibility(mcp_client):
    """Test route tool handles legacy query parameter."""
    # Some tools might support query: "Paris -> Lyon" format
    result = await mcp_client.call_tool("get_route_info", {"query": "Berlin -> Munich"})
    assert isinstance(result, dict)
    assert "tool_name" in result

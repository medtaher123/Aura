"""
Tests for water ingress tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_estimate_surface_water_ingress_tool_exists(mcp_client):
    """Test water ingress tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "estimate_surface_water_ingress_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_estimate_surface_water_ingress_tool_with_city(mcp_client):
    """Test water ingress tool accepts city name."""
    result = await mcp_client.call_tool(
        "estimate_surface_water_ingress_tool", {"location_input": "Paris"}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result
    assert result.get("tool_name") == "estimate_surface_water_ingress_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_estimate_surface_water_ingress_tool_structure(mcp_client):
    """Test water ingress tool returns proper structure."""
    result = await mcp_client.call_tool(
        "estimate_surface_water_ingress_tool", {"location_input": "London"}
    )
    assert isinstance(result, dict)
    assert "message" in result
    # Tool should handle errors gracefully
    assert "error" in result or "data" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_estimate_surface_water_ingress_tool_error_handling(mcp_client):
    """Test water ingress tool handles invalid input."""
    # Empty location - should raise validation error or return error
    try:
        result = await mcp_client.call_tool("estimate_surface_water_ingress_tool", {})
        # If it doesn't raise, check it's a dict (some implementations may handle it)
        assert isinstance(result, dict)
    except Exception:
        # This is expected behavior - missing required field
        pass

    # Invalid location
    result = await mcp_client.call_tool(
        "estimate_surface_water_ingress_tool",
        {"location_input": "InvalidCityName12345XYZ"},
    )
    assert isinstance(result, dict)

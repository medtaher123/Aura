"""
Tests for geographic info tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_exists(mcp_client):
    """Test geographic info tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "geo_info_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geo_info_tool_with_country(mcp_client):
    """Test geo info tool accepts country name."""
    result = await mcp_client.call_tool("geo_info_tool", {"name": "France"})
    assert isinstance(result, dict)
    assert "tool_name" in result
    assert result.get("tool_name") == "geo_info_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geo_info_tool_with_city(mcp_client):
    """Test geo info tool accepts city name."""
    result = await mcp_client.call_tool("geo_info_tool", {"name": "Paris"})
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geo_info_tool_various_locations(mcp_client):
    """Test geo info tool handles different locations."""
    locations = ["Japan", "Brazil", "London", "Cairo", "Australia"]

    for location in locations:
        result = await mcp_client.call_tool("geo_info_tool", {"name": location})
        assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geo_info_tool_error_handling(mcp_client):
    """Test geo info tool handles invalid input."""
    # Invalid location
    result = await mcp_client.call_tool(
        "geo_info_tool", {"name": "InvalidLocationName12345XYZ"}
    )
    assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geo_info_tool_structure(mcp_client):
    """Test geo info tool returns proper structure."""
    result = await mcp_client.call_tool("geo_info_tool", {"name": "Germany"})
    assert isinstance(result, dict)
    assert "tool_name" in result
    # Should have geographic data or error
    assert "data" in result or "error" in result

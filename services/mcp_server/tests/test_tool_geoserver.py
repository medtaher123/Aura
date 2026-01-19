"""
Tests for GeoServer risk mask tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geoserver_risk_mask_tool_exists(mcp_client):
    """Test GeoServer tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "geoserver_risk_mask_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geoserver_risk_mask_tool_with_location(mcp_client):
    """Test GeoServer tool accepts location parameter."""
    result = await mcp_client.call_tool(
        "geoserver_risk_mask_tool", {"location": "Tunis", "risk_type": "flood"}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geoserver_risk_mask_tool_risk_types(mcp_client):
    """Test GeoServer tool accepts different risk types."""
    risk_types = ["flood", "fire", "landslide"]

    for rtype in risk_types:
        result = await mcp_client.call_tool(
            "geoserver_risk_mask_tool", {"location": "Paris", "risk_type": rtype}
        )
        assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geoserver_risk_mask_tool_with_filters(mcp_client):
    """Test GeoServer tool accepts filter parameters."""
    result = await mcp_client.call_tool(
        "geoserver_risk_mask_tool",
        {
            "location": "Rome",
            "risk_type": "flood",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
        },
    )
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_geoserver_risk_mask_tool_structure(mcp_client):
    """Test GeoServer tool returns proper structure."""
    result = await mcp_client.call_tool(
        "geoserver_risk_mask_tool", {"location": "Madrid", "risk_type": "fire"}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result
    # Should have data or error
    assert "data" in result or "error" in result

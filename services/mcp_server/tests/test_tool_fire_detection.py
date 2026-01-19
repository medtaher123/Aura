"""
Tests for fire detection tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_detect_fire_tool_exists(mcp_client):
    """Test fire detection tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "detect_fire_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_with_city(mcp_client):
    """Test fire tool accepts city parameter."""
    result = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "Los Angeles",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
        },
    )
    assert isinstance(result, dict)
    assert "tool_name" in result
    assert result.get("tool_name") == "detect_fire_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_with_coordinates(mcp_client):
    """Test fire tool accepts coordinate parameters."""
    result = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "34.05,-118.25",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
            "radius_km": 50,
        },
    )
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_date_validation(mcp_client):
    """Test fire tool validates date parameters."""
    # Valid dates
    result = await mcp_client.call_tool(
        "detect_fire_tool",
        {"location": "Paris", "start_date": "2024-06-01", "end_date": "2024-06-30"},
    )
    assert isinstance(result, dict)

    # Single date (should use as both start and end)
    result = await mcp_client.call_tool(
        "detect_fire_tool",
        {"location": "Tokyo", "start_date": "2024-07-01", "end_date": "2024-07-01"},
    )
    assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_radius_parameter(mcp_client):
    """Test fire tool accepts and validates radius."""
    result = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "Sydney",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "radius_km": 100,
        },
    )
    assert isinstance(result, dict)
    assert "tool_name" in result

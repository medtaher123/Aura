"""
Tests for disaster events tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_disaster_events_tool_exists(mcp_client):
    """Test disaster events tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "query_disaster_events_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_disaster_events_tool_with_country(mcp_client):
    """Test disaster tool accepts country parameter."""
    result = await mcp_client.call_tool(
        "query_disaster_events_tool",
        {
            "country_name": "France",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "disaster_type": "flood",
        },
    )
    assert isinstance(result, dict)
    assert "tool_name" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_disaster_events_tool_date_range(mcp_client):
    """Test disaster tool handles date ranges."""
    result = await mcp_client.call_tool(
        "query_disaster_events_tool",
        {
            "country_name": "Japan",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "disaster_type": "earthquake",
        },
    )
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_disaster_events_tool_disaster_types(mcp_client):
    """Test disaster tool accepts different disaster types."""
    disaster_types = ["flood", "storm", "earthquake", "drought"]

    for dtype in disaster_types:
        result = await mcp_client.call_tool(
            "query_disaster_events_tool",
            {
                "country_name": "USA",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "disaster_type": dtype,
            },
        )
        assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_disaster_events_tool_with_location(mcp_client):
    """Test disaster tool accepts location parameter."""
    result = await mcp_client.call_tool(
        "query_disaster_events_tool",
        {
            "country_name": "Italy",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "location": "Sicily",
            "disaster_type": "flood",
        },
    )
    assert isinstance(result, dict)
    assert "tool_name" in result

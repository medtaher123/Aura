"""
Tests for STAC catalog tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_stac_catalog_exists(mcp_client):
    """Test STAC catalog tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "query_stac_catalog" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_stac_catalog_with_city(mcp_client):
    """Test STAC tool accepts city parameter."""
    result = await mcp_client.call_tool(
        "query_stac_catalog",
        {
            "city": "Paris",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
            "collection": "sentinel-2-l2a",
        },
    )
    assert isinstance(result, dict)
    assert "tool_name" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_stac_catalog_date_range(mcp_client):
    """Test STAC tool handles date ranges."""
    result = await mcp_client.call_tool(
        "query_stac_catalog",
        {"city": "Tokyo", "start_date": "2024-06-01", "end_date": "2024-06-05"},
    )
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_stac_catalog_collections(mcp_client):
    """Test STAC tool accepts different collections."""
    collections = ["sentinel-2-l2a", "sentinel-1", "modis"]

    for collection in collections:
        result = await mcp_client.call_tool(
            "query_stac_catalog",
            {"city": "London", "start_date": "2024-01-01", "collection": collection},
        )
        assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_stac_catalog_single_date(mcp_client):
    """Test STAC tool with single date (defaults end_date)."""
    result = await mcp_client.call_tool(
        "query_stac_catalog", {"city": "New York", "start_date": "2024-03-15"}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result

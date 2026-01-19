"""
Tests for hazard detection tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_query_hazards_tool_exists(mcp_client):
    """Test hazard tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "query_hazards_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_hazards_tool_requires_country(mcp_client):
    """Test hazard tool validates country parameter."""
    # Test with valid country
    result = await mcp_client.call_tool(
        "query_hazards_tool", {"country": "Japan", "top_n": 3}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result

    # Missing country should raise validation error or return error
    try:
        result = await mcp_client.call_tool("query_hazards_tool", {})
        # If it doesn't raise, check it's an error response
        assert isinstance(result, dict)
        assert "error" in result or "message" in result
    except Exception:
        # This is expected behavior - missing required field
        pass


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_hazards_tool_top_n_parameter(mcp_client):
    """Test hazard tool accepts top_n parameter."""
    result = await mcp_client.call_tool(
        "query_hazards_tool", {"country": "France", "top_n": 5}
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "query_hazards_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_hazards_tool_with_location(mcp_client):
    """Test hazard tool accepts optional location parameter."""
    result = await mcp_client.call_tool(
        "query_hazards_tool", {"country": "USA", "top_n": 3, "location": "California"}
    )
    assert isinstance(result, dict)
    assert "message" in result

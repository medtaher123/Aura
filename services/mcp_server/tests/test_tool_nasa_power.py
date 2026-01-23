"""Tests for NASA POWER tool."""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nasa_power_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "nasa_power_hourly_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_nasa_power_tool_basic_call(mcp_client):
    # Use a small historical range to keep responses small and stable.
    result = await mcp_client.call_tool(
        "nasa_power_hourly_tool",
        {
            "location": "Paris",
            "start_date": "2020-01-01",
            "end_date": "2020-01-02",
            "parameters": ["T2M"],
            "community": "re",
            "units": "metric",
            "time_standard": "utc",
            "max_days": 7,
        },
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "nasa_power_hourly_tool"
    # Either success with data, or a structured error (e.g. network/rate limiting)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nasa_power_tool_validation(mcp_client):
    # Missing location and coordinates
    result = await mcp_client.call_tool("nasa_power_hourly_tool", {})
    assert isinstance(result, dict)
    assert result.get("error") is True

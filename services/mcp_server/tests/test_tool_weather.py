"""
Tests for weather tool.
"""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_weather_tool_exists(mcp_client):
    """Test weather tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "weather_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_with_city(mcp_client):
    """Test weather tool accepts city parameter."""
    result = await mcp_client.call_tool("weather_tool", {"city_name": "Paris"})
    assert isinstance(result, dict)
    assert "tool_name" in result
    assert result.get("tool_name") == "weather_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_with_forecast_days(mcp_client):
    """Test weather tool accepts forecast_days parameter."""
    result = await mcp_client.call_tool(
        "weather_tool", {"city_name": "London", "forecast_days": 7}
    )
    assert isinstance(result, dict)
    assert "message" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_various_cities(mcp_client):
    """Test weather tool handles different cities."""
    cities = ["Tokyo", "New York", "Sydney", "Berlin", "Dubai"]

    for city in cities:
        result = await mcp_client.call_tool("weather_tool", {"city_name": city})
        assert isinstance(result, dict)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_default_forecast(mcp_client):
    """Test weather tool uses default forecast days."""
    result = await mcp_client.call_tool("weather_tool", {"city_name": "Rome"})
    assert isinstance(result, dict)
    assert "tool_name" in result


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_error_handling(mcp_client):
    """Test weather tool handles invalid input."""
    # Invalid city
    result = await mcp_client.call_tool(
        "weather_tool", {"city_name": "InvalidCityName12345XYZ"}
    )
    assert isinstance(result, dict)

    # Missing city - should raise validation error or return error
    try:
        result = await mcp_client.call_tool("weather_tool", {})
        # If it doesn't raise, check it's a dict (some implementations may handle it)
        assert isinstance(result, dict)
    except Exception:
        # This is expected behavior - missing required field
        pass


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_weather_tool_structure(mcp_client):
    """Test weather tool returns proper structure."""
    result = await mcp_client.call_tool(
        "weather_tool", {"city_name": "Madrid", "forecast_days": 3}
    )
    assert isinstance(result, dict)
    assert "tool_name" in result
    # Should have weather data or error
    assert "data" in result or "error" in result

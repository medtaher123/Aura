"""
Tests for geographic info tool.
"""

import pytest

from modules.utility import geographic_info as geo


_FRANCE_INFO = {
    "Type": "Country",
    "Name": "France",
    "Capital": "Paris",
    "Population": 67000000,
    "Area (km²)": 551695,
    "Region": "Europe",
    "Subregion": "Western Europe",
    "Languages": ["French"],
    "Currency": "Euro",
    "Flag": "https://example.invalid/fr.png",
}

_PARIS_INFO = {
    "Type": "City",
    "Name": "Paris, France",
    "Country": "France",
    "Region": "Île-de-France",
    "Latitude": "48.8566",
    "Longitude": "2.3522",
    "Population": 2100000,
}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_exists(mcp_client):
    """Test geographic info tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "geo_info_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_with_country(mcp_client, monkeypatch):
    """Test geo info tool accepts country name."""
    monkeypatch.setattr(geo, "get_country_info", lambda _name: _FRANCE_INFO)

    result = await mcp_client.call_tool("geo_info_tool", {"name": "France"})
    assert isinstance(result, dict)
    assert result.get("tool_name") == "geo_info_tool"
    assert result.get("error") is False
    assert result.get("country") == "France"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_with_city(mcp_client, monkeypatch):
    """Test geo info tool accepts city name."""
    monkeypatch.setattr(geo, "get_country_info", lambda _name: None)
    monkeypatch.setattr(geo, "get_city_candidates", lambda _name: [])
    monkeypatch.setattr(geo, "get_city_info", lambda _name: _PARIS_INFO)

    result = await mcp_client.call_tool("geo_info_tool", {"name": "Paris"})
    assert isinstance(result, dict)
    assert "message" in result
    assert result.get("error") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_various_locations(mcp_client, monkeypatch):
    """Test geo info tool handles different locations."""
    monkeypatch.setattr(
        geo,
        "get_country_info",
        lambda name: {**_FRANCE_INFO, "Name": name},
    )

    for location in ["Japan", "Brazil", "London", "Cairo", "Australia"]:
        result = await mcp_client.call_tool("geo_info_tool", {"name": location})
        assert isinstance(result, dict)
        assert result.get("error") is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_error_handling(mcp_client, monkeypatch):
    """Test geo info tool handles invalid input."""
    monkeypatch.setattr(geo, "get_country_info", lambda _name: None)
    monkeypatch.setattr(geo, "get_city_candidates", lambda _name: [])
    monkeypatch.setattr(geo, "get_city_info", lambda _name: None)

    result = await mcp_client.call_tool(
        "geo_info_tool", {"name": "InvalidLocationName12345XYZ"}
    )
    assert isinstance(result, dict)
    assert result.get("error") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_geo_info_tool_structure(mcp_client, monkeypatch):
    """Test geo info tool returns proper structure."""
    monkeypatch.setattr(
        geo,
        "get_country_info",
        lambda _name: {**_FRANCE_INFO, "Name": "Germany"},
    )

    result = await mcp_client.call_tool("geo_info_tool", {"name": "Germany"})
    assert isinstance(result, dict)
    assert "tool_name" in result
    assert "data" in result or "error" in result

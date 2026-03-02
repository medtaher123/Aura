"""Tests for flood depth-damage tool."""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_exists(mcp_client):
    """Test flood depth-damage tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "flood_depth_damage_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_basic(mcp_client):
    """Test flood depth-damage tool returns estimates for valid inputs."""
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {
            "country": "Kenya",
            "asset_class": "residential",
            "depth_m": 0.8,
            "continent": "Africa",
            "basis": "building",
            "year": 2024,
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is False

    data = result.get("data") or {}
    assert data.get("asset_class") == "residential"
    assert "adjusted_max_damage_value" in data
    assert "estimated_damage" in data
    assert "base_max_damage_value" not in data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_building_type_alias(mcp_client):
    """Test building_type is accepted as an alias for asset_class."""
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {
            "country": "France",
            "building_type": "residential",
            "depth_m": 0.5,
            "continent": "Europe",
            "basis": "building",
            "year": 2024,
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is False
    data = result.get("data") or {}
    assert data.get("asset_class") == "residential"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_invalid_year(mcp_client):
    """Test tool rejects unsupported years."""
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {
            "country": "Kenya",
            "asset_class": "residential",
            "depth_m": 0.8,
            "continent": "Africa",
            "year": 2040,
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_missing_asset_class(mcp_client):
    """Test tool returns error when asset class is missing."""
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {"country": "Kenya", "depth_m": 0.8},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_france_3m_2025(mcp_client):
    """
    Test 3-meter flood depth damage for France (2025).
    Verifies output correctness: estimated damage ~1,133 EUR/m², max damage ~1,511 EUR/m².
    """
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {
            "country": "France",
            "asset_class": "residential",
            "depth_m": 3.0,
            "continent": "Europe",
            "basis": "building",
            "year": 2025,
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is False
    assert result.get("country", "").upper() == "FRANCE"

    data = result.get("data") or {}
    assert data.get("asset_class") == "residential"
    assert data.get("depth_m") == 3.0
    assert data.get("unit") == "EUR/m2"

    estimated = data.get("estimated_damage")
    max_damage = data.get("adjusted_max_damage_value")

    assert estimated is not None, "response must include estimated_damage"
    assert max_damage is not None, "response must include adjusted_max_damage_value"

    assert estimated == pytest.approx(1133, rel=0.02), (
        f"estimated damage should be ~1,133 EUR/m², got {estimated}"
    )
    assert max_damage == pytest.approx(1511, rel=0.02), (
        f"maximum damage should be ~1,511 EUR/m², got {max_damage}"
    )


# Expected output for "estimated flood damage for residential buildings in France at 2 m depth in 2025".
EXPECTED_FRANCE_RESIDENTIAL_2M_2025 = {
    "fractional_damage": 0.600,
    "adjusted_max_damage_value_eur_m2": 1510.93,
    "estimated_damage_eur_m2": 906.56,
}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_depth_damage_tool_france_residential_2m_2025_output(mcp_client):
    """
    Test flood damage for residential buildings in France at 2 m depth (2025).
    At this depth, damage fraction is 0.600 (60%). Max damage 1510.93 EUR/m² (2025 adjusted),
    estimated damage ~906.56 EUR/m².
    """
    result = await mcp_client.call_tool(
        "flood_depth_damage_tool",
        {
            "country": "France",
            "asset_class": "residential",
            "depth_m": 2.0,
            "continent": "Europe",
            "basis": "building",
            "year": 2025,
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_depth_damage_tool"
    assert result.get("error") is False
    assert result.get("country", "").lower() == "france"

    data = result.get("data") or {}
    assert data.get("asset_class") == "residential"
    assert data.get("depth_m") == 2.0
    assert data.get("unit") == "EUR/m2"

    fractional = data.get("fractional_damage")
    max_damage = data.get("adjusted_max_damage_value")
    estimated = data.get("estimated_damage")

    assert fractional is not None, "response must include fractional_damage"
    assert max_damage is not None, "response must include adjusted_max_damage_value"
    assert estimated is not None, "response must include estimated_damage"

    assert fractional == pytest.approx(EXPECTED_FRANCE_RESIDENTIAL_2M_2025["fractional_damage"], rel=0.01), (
        f"damage fraction should be 0.600 (60%), got {fractional}"
    )
    assert max_damage == pytest.approx(
        EXPECTED_FRANCE_RESIDENTIAL_2M_2025["adjusted_max_damage_value_eur_m2"], rel=0.01
    ), (
        f"max damage should be ~1510.93 EUR/m², got {max_damage}"
    )
    assert estimated == pytest.approx(
        EXPECTED_FRANCE_RESIDENTIAL_2M_2025["estimated_damage_eur_m2"], rel=0.01
    ), (
        f"estimated damage should be ~906.56 EUR/m², got {estimated}"
    )

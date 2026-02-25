"""Tests for flood damage city tool."""

import pytest

from tools import flood_damage_city as fdc


# ----- Helper unit tests -----


@pytest.mark.unit
def test_geojson_polygon_to_wkt_polygon():
    """_geojson_polygon_to_wkt converts a GeoJSON Polygon to WKT."""
    geojson = {
        "type": "Polygon",
        "coordinates": [[[2.0, 48.0], [2.5, 48.0], [2.5, 48.5], [2.0, 48.5], [2.0, 48.0]]],
    }
    wkt = fdc._geojson_polygon_to_wkt(geojson)
    assert wkt is not None
    assert "POLYGON" in wkt
    assert "2.0 48.0" in wkt


@pytest.mark.unit
def test_geojson_polygon_to_wkt_multipolygon():
    """_geojson_polygon_to_wkt converts a GeoJSON MultiPolygon to WKT."""
    geojson = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[2.0, 48.0], [2.5, 48.0], [2.5, 48.5], [2.0, 48.5], [2.0, 48.0]]]
        ],
    }
    wkt = fdc._geojson_polygon_to_wkt(geojson)
    assert wkt is not None
    assert "MULTIPOLYGON" in wkt


@pytest.mark.unit
def test_geojson_polygon_to_wkt_invalid():
    """_geojson_polygon_to_wkt returns None for invalid input."""
    assert fdc._geojson_polygon_to_wkt(None) is None
    assert fdc._geojson_polygon_to_wkt({}) is None
    assert fdc._geojson_polygon_to_wkt({"type": "Point", "coordinates": [2, 48]}) is None
    assert fdc._geojson_polygon_to_wkt({"type": "Polygon", "coordinates": []}) is None


@pytest.mark.unit
def test_get_damage_per_m2_returns_float_or_none():
    """_get_damage_per_m2 returns a positive float for valid inputs or None."""
    result = fdc._get_damage_per_m2(
        country="France",
        asset_class="residential",
        depth_m=2.0,
        year=2024,
        continent="europe",
        basis="building_total",
    )
    assert result is not None
    assert isinstance(result, float)
    assert result > 0

    result_unknown = fdc._get_damage_per_m2(
        country="NonExistentCountryXYZ",
        asset_class="residential",
        depth_m=2.0,
        year=2024,
        continent="europe",
        basis="building_total",
    )
    assert result_unknown is None


# ----- MCP tool tests -----


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_exists(mcp_client):
    """Test flood damage city tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "flood_damage_city_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_empty_city(mcp_client):
    """Test tool returns error when city is empty."""
    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "", "depth_m": 2},
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is True
    assert "city" in (result.get("message") or "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_unsupported_asset_class(mcp_client):
    """Test tool returns error when asset_class is invalid."""
    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "Paris", "depth_m": 2.0, "asset_class": "invalid_type"},
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is True
    msg = (result.get("message") or "").lower()
    assert "asset" in msg or "residential" in msg


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_year_passed_through(mcp_client, monkeypatch):
    """Test tool passes year through to output when all deps are mocked."""
    def fake_geocode(_city_name):
        return "POLYGON((2 48, 3 48, 3 49, 2 48))", "France", "Lyon"

    def fake_query_areas(*_args, **_kwargs):
        return {"residential": 1000.0}, None

    class FakeConfig:
        daylight_athena_output = "s3://metaplanet-daylight-athena-query-results-96327/"
        athena_db = "default"

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)
    monkeypatch.setattr(fdc, "_query_daylight_building_areas", fake_query_areas)
    monkeypatch.setattr(fdc, "_ensure_daylight_table", lambda *a, **k: None)
    monkeypatch.setattr(fdc, "get_config", lambda: FakeConfig())

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "Lyon", "depth_m": 2.0, "year": 2024},
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is False
    assert (result.get("data") or {}).get("year") == 2024


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_city_not_found(mcp_client, monkeypatch):
    """Test tool returns error when geocoding returns no polygon."""
    def fake_geocode(_city_name):
        return None, None, None

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "NonExistentCityXYZ123", "depth_m": 2.0},
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is True
    assert "geocode" in (result.get("message") or "").lower() or "polygon" in (result.get("message") or "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_missing_s3_config(mcp_client, monkeypatch):
    """Test tool returns error when DAYLIGHT_ATHENA_OUTPUT is not set or placeholder."""
    def fake_geocode(_city_name):
        return "POLYGON((2 48, 3 48, 3 49, 2 49, 2 48))", "France", "Lyon"

    class FakeConfig:
        daylight_athena_output = "s3://your-bucket/"
        athena_db = "default"

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)
    monkeypatch.setattr(fdc, "get_config", lambda: FakeConfig())

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "Lyon", "depth_m": 2.0},
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is True
    assert "DAYLIGHT_ATHENA_OUTPUT" in (result.get("message") or "") or "us-west-2" in (result.get("message") or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_success_with_mocked_athena(mcp_client, monkeypatch):
    """Test full flow with mocked geocoding and Athena: returns breakdown and total."""
    def fake_geocode(_city_name):
        return "POLYGON((2 48, 3 48, 3 49, 2 49, 2 48))", "France", "Lyon"

    def fake_query_areas(*_args, **_kwargs):
        return {"residential": 10000.0, "commercial": 2000.0}, None

    def fake_ensure_table(*_args, **_kwargs):
        return None

    class FakeConfig:
        daylight_athena_output = "s3://metaplanet-daylight-athena-query-results-96327/"
        athena_db = "default"

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)
    monkeypatch.setattr(fdc, "_query_daylight_building_areas", fake_query_areas)
    monkeypatch.setattr(fdc, "_ensure_daylight_table", fake_ensure_table)
    monkeypatch.setattr(fdc, "get_config", lambda: FakeConfig())

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "Lyon", "depth_m": 2.0, "year": 2024},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is False
    assert "Lyon" in (result.get("message") or "")
    assert "EUR" in (result.get("message") or "")

    data = result.get("data") or {}
    assert data.get("city") == "Lyon"
    assert data.get("country") == "France"
    assert data.get("depth_m") == 2.0
    assert data.get("year") == 2024
    assert data.get("total_area_m2") == 12000.0
    assert data.get("total_estimated_damage_eur") > 0
    assert data.get("unit") == "EUR"
    breakdown = data.get("breakdown") or []
    assert len(breakdown) >= 1
    asset_classes = {b["asset_class"] for b in breakdown}
    assert "residential" in asset_classes or "commercial" in asset_classes
    for b in breakdown:
        assert "asset_class" in b
        assert "area_m2" in b
        assert "cost_per_m2_eur" in b
        assert "estimated_damage_eur" in b


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_no_buildings(mcp_client, monkeypatch):
    """Test tool returns friendly message when Athena finds no buildings in polygon."""
    def fake_geocode(_city_name):
        return "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", "France", "TinyVillage"

    def fake_query_areas(*_args, **_kwargs):
        return {}, None  # no buildings

    class FakeConfig:
        daylight_athena_output = "s3://metaplanet-daylight-athena-query-results-96327/"
        athena_db = "default"

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)
    monkeypatch.setattr(fdc, "_query_daylight_building_areas", fake_query_areas)
    monkeypatch.setattr(fdc, "_ensure_daylight_table", lambda *a, **k: None)
    monkeypatch.setattr(fdc, "get_config", lambda: FakeConfig())

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "TinyVillage", "depth_m": 1.0},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "flood_damage_city_tool"
    assert result.get("error") is False
    assert "No buildings" in (result.get("message") or "")
    assert (result.get("data") or {}).get("city") == "TinyVillage"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flood_damage_city_tool_filter_asset_residential(mcp_client, monkeypatch):
    """Test tool with asset_class=residential only returns residential in breakdown."""
    def fake_geocode(_city_name):
        return "POLYGON((2 48, 3 48, 3 49, 2 48))", "France", "Lyon"

    def fake_query_areas(*_args, **_kwargs):
        return {"residential": 5000.0}, None

    class FakeConfig:
        daylight_athena_output = "s3://metaplanet-daylight-athena-query-results-96327/"
        athena_db = "default"

    monkeypatch.setattr(fdc, "_get_city_polygon_and_country", fake_geocode)
    monkeypatch.setattr(fdc, "_query_daylight_building_areas", fake_query_areas)
    monkeypatch.setattr(fdc, "_ensure_daylight_table", lambda *a, **k: None)
    monkeypatch.setattr(fdc, "get_config", lambda: FakeConfig())

    result = await mcp_client.call_tool(
        "flood_damage_city_tool",
        {"city": "Lyon", "depth_m": 2.0, "asset_class": "residential", "year": 2024},
    )

    assert isinstance(result, dict)
    assert result.get("error") is False
    breakdown = (result.get("data") or {}).get("breakdown") or []
    assert all(b["asset_class"] == "residential" for b in breakdown)
    assert (result.get("data") or {}).get("total_area_m2") == 5000.0

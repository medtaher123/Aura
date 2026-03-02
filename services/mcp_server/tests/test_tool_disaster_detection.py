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


# Expected output for "Are there storms in Spain in 2025" (Spain, storm, 2025-01-01–2025-12-31).
EXPECTED_SPAIN_STORMS_2025_MESSAGE = (
    "3 event(s) found in Spain between 2025-01-01 and 2025-12-31. "
    "Breakdown: storm: 3. Geocoded 3/3 missing locations."
)
# View state is derived from the 3 points; we only assert it's in Spain (tool uses view_state_from_points).
SPAIN_VIEW_STATE_BOUNDS = {"lat_min": 35, "lat_max": 44, "lon_min": -10, "lon_max": 5, "zoom_min": 4, "zoom_max": 9}
# Geocoded map points (3 storm events in 2025).
EXPECTED_SPAIN_STORMS_2025_MAP_DATA = [
    {
        "lat": 42.1939629,
        "lon": -7.537124,
        "type": "Storm",
        "requested_disaster_type": "storm",
        "country": "Spain",
        "location": "Ourense, Galicia autonomous community",
        "start_date": "2025-1-27",
        "end_date": "2025-1-28",
        "total_deaths": 1,
        "total_affected": None,
        "origin": None,
        "emoji": "🌪️",
        "color": [128, 0, 128, 200],
    },
    {
        "lat": 39.4697065,
        "lon": -0.3763353,
        "type": "Storm",
        "requested_disaster_type": "storm",
        "country": "Spain",
        "location": "Valencia, Zaragoza, Castellón, Alicante, Tarragona, and Baleares, with Ibiza Island",
        "start_date": "2025-9-25",
        "end_date": "2025-9-27",
        "total_deaths": None,
        "total_affected": None,
        "origin": None,
        "emoji": "🌪️",
        "color": [128, 0, 128, 200],
    },
    {
        "lat": 41.8523094,
        "lon": 1.5745043,
        "type": "Storm",
        "requested_disaster_type": "storm",
        "country": "Spain",
        "location": "Catalonia, Valencia, Alicante, Murcia, Balearic Islands",
        "start_date": "2025-10-10",
        "end_date": "2025-10-13",
        "total_deaths": None,
        "total_affected": 1018,
        "origin": None,
        "emoji": "🌪️",
        "color": [128, 0, 128, 200],
    },
]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_query_disaster_events_tool_spain_storms_2025_output(mcp_client):
    """Test disaster tool behaviour and output for storms in Spain in 2025."""
    result = await mcp_client.call_tool(
        "query_disaster_events_tool",
        {
            "country_name": "Spain",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "disaster_type": ["storm"],
        },
    )
    assert isinstance(result, dict)
    assert result.get("tool_name") == "query_disaster_events_tool"
    assert result.get("error") is False
    assert result.get("start_date") == "2025-01-01"
    assert result.get("end_date") == "2025-12-31"
    assert result.get("country") == "Spain"

    message = result.get("message") or ""
    # Message may say "Geocoded 3/3" or "Geocoded 0/3" etc. when Nominatim rate-limits (429)
    assert "3 event(s) found" in message
    assert "Spain" in message
    assert "2025-01-01" in message
    assert "2025-12-31" in message
    assert "storm: 3" in message

    data = result.get("data") or {}
    assert data.get("iso3") == "ESP"
    assert data.get("disaster_types") == ["storm"]
    events = data.get("events") or []
    assert len(events) == 3
    events_by_type = data.get("events_by_type") or {}
    assert "storm" in events_by_type
    assert len(events_by_type["storm"]) == 3

    artifacts = result.get("artifacts") or {}
    maps_list = artifacts.get("maps") or []
    # When Nominatim returns 429, geocoding can fail and no map may be produced
    if len(maps_list) == 0:
        return  # Pass: we already asserted event count and message; map skipped due to rate limit
    map_spec = maps_list[0]
    assert map_spec.get("title") == "Disaster events in Spain"

    actual_view = map_spec.get("view_state") or {}
    bounds = SPAIN_VIEW_STATE_BOUNDS
    assert bounds["lat_min"] <= actual_view.get("latitude", 0) <= bounds["lat_max"]
    assert bounds["lon_min"] <= actual_view.get("longitude", 0) <= bounds["lon_max"]
    assert bounds["zoom_min"] <= actual_view.get("zoom", 0) <= bounds["zoom_max"]

    layers = map_spec.get("layers") or []
    assert len(layers) >= 2
    scatter_layer = next((l for l in layers if l.get("type") == "ScatterplotLayer"), None)
    map_data = scatter_layer.get("data") if scatter_layer else (layers[0].get("data") if layers else [])
    if len(map_data) == 3:
        assert map_data == EXPECTED_SPAIN_STORMS_2025_MAP_DATA
    assert len(map_data) in (0, 3), "map_data should have 0 (rate-limited) or 3 points"

"""
Tests for fire detection tool.
"""

import pytest

from utils.contracts import ToolResponse

# Expected output for Paris @osm_id:R7444 on 2023-07-09 (fire archive).
EXPECTED_PARIS_2023_07_09_POINTS = [
    {"lat": 49.65547, "lon": 1.88436, "brightness": 327.69, "acq_date": "2023-07-09", "acq_time": "48"},
    {"lat": 49.65504, "lon": 1.88012, "brightness": 312.38, "acq_date": "2023-07-09", "acq_time": "48"},
    {"lat": 49.65504, "lon": 1.8881, "brightness": 310.05, "acq_date": "2023-07-09", "acq_time": "48"},
    {"lat": 49.65392, "lon": 1.8887, "brightness": 307.21, "acq_date": "2023-07-09", "acq_time": "229"},
    {"lat": 49.65081, "lon": 1.88843, "brightness": 305.16, "acq_date": "2023-07-09", "acq_time": "229"},
    {"lat": 48.98249, "lon": 1.75892, "brightness": 307.67, "acq_date": "2023-07-09", "acq_time": "229"},
    {"lat": 48.38588, "lon": 2.98437, "brightness": 327.85, "acq_date": "2023-07-09", "acq_time": "1216"},
]
# View state is derived from the 6 points; assert bounds for Paris region.
PARIS_VIEW_STATE_BOUNDS = {"lat_min": 48, "lat_max": 50, "lon_min": 1.5, "lon_max": 3.5, "zoom_min": 5, "zoom_max": 11}


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
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "Los Angeles",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
        },
    )
    result = ToolResponse.model_validate(raw)
    assert result.tool_name == "detect_fire_tool"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_with_coordinates(mcp_client):
    """Test fire tool accepts coordinate parameters."""
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "34.05,-118.25",
            "start_date": "2024-01-01",
            "end_date": "2024-01-07",
            "radius_km": 50,
        },
    )
    result = ToolResponse.model_validate(raw)
    assert result.message is not None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_date_validation(mcp_client):
    """Test fire tool validates date parameters."""
    # Valid dates
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {"location": "Paris", "start_date": "2024-06-01", "end_date": "2024-06-30"},
    )
    ToolResponse.model_validate(raw)

    # Single date (should use as both start and end)
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {"location": "Tokyo", "start_date": "2024-07-01", "end_date": "2024-07-01"},
    )
    ToolResponse.model_validate(raw)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_radius_parameter(mcp_client):
    """Test fire tool accepts and validates radius."""
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "location": "Sydney",
            "start_date": "2024-01-01",
            "end_date": "2024-01-31",
            "radius_km": 100,
        },
    )
    result = ToolResponse.model_validate(raw)
    assert result.tool_name


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.slow
async def test_detect_fire_tool_paris_2023_07_09_output(mcp_client):
    """Test fire tool behaviour and output for Paris on 2023-07-09 only."""
    raw = await mcp_client.call_tool(
        "detect_fire_tool",
        {
            "start_date": "2023-07-09",
            "end_date": "2023-07-09",
            "location": "@osm_id:R7444",
            "radius_km": None,
        },
    )
    result = ToolResponse.model_validate(raw)
    assert result.tool_name == "detect_fire_tool"

    # Skip when geocoding fails (e.g. Nominatim 429) or when fire archive is not configured (CI).
    if result.error:
        msg = (result.message or "").lower()
        if "429" in msg or "too many requests" in msg or "could not geocode" in msg:
            pytest.skip("Geocoding failed (often due to Nominatim rate limit 429)")
        if "fire_archive_dir" in msg or "must be set to an s3 uri" in msg:
            pytest.skip("FIRE_ARCHIVE_DIR not set (e.g. in CI); skipping output assertion test")
        raise AssertionError(f"Tool returned error: {result.message}")

    maps = result.artifacts.maps or []
    assert len(maps) >= 1, "expected at least one map artifact"
    map_spec = maps[0]

    assert "points" in map_spec
    actual_points = map_spec["points"] or []
    sort_key = lambda p: (
        p.get("acq_date"),
        p.get("acq_time"),
        p.get("lat"),
        p.get("lon"),
        p.get("brightness"),
    )
    assert sorted(actual_points, key=sort_key) == sorted(
        EXPECTED_PARIS_2023_07_09_POINTS, key=sort_key
    )

    assert "view_state" in map_spec
    actual_view = map_spec["view_state"]
    bounds = PARIS_VIEW_STATE_BOUNDS
    assert bounds["lat_min"] <= actual_view["latitude"] <= bounds["lat_max"]
    assert bounds["lon_min"] <= actual_view["longitude"] <= bounds["lon_max"]
    assert bounds["zoom_min"] <= actual_view["zoom"] <= bounds["zoom_max"]

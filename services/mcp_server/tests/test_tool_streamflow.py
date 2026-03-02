"""Tests for streamflow forecast tool."""

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_exists(mcp_client):
    """Test streamflow forecast tool is properly defined."""
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "streamflow_forecast_tool" in tool_names


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_with_river_name(mcp_client, monkeypatch):
    """Test streamflow tool can infer reach_id from river name via geocoding."""
    import tools.streamflow as streamflow_mod

    def _fake_get_city_bbox(query: str, require_confirmation: bool = True):
        return ([2.20, 48.80, 2.45, 48.92], 48.8566, 2.3522, "Seine, Paris, France")

    def _fake_identify_geoglows_river_feature(lat, lon, return_geometry=False):
        # Simulate successful reach_id inference
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"river_id": 230366127, "reach_id": 230366127},
                "geometry": {"type": "LineString", "coordinates": [[2.3, 48.85], [2.35, 48.86]]}
            }]
        } if return_geometry else None
        return 230366127, geojson

    def _fake_view_state_from_points(points, padding=0.1, min_zoom=8.0, max_zoom=12.0):
        return {"latitude": 48.8566, "longitude": 2.3522, "zoom": 10.0, "pitch": 0, "bearing": 0}

    monkeypatch.setattr(streamflow_mod, "get_city_bbox", _fake_get_city_bbox)
    monkeypatch.setattr(streamflow_mod, "_identify_geoglows_river_feature", _fake_identify_geoglows_river_feature)
    monkeypatch.setattr(streamflow_mod, "view_state_from_points", _fake_view_state_from_points)
    monkeypatch.setattr(streamflow_mod, "_river_id_exists", lambda rid: True)
    monkeypatch.setattr(
        streamflow_mod,
        "_get_return_periods",
        lambda rid: {
            "return_period_2": 850.0,
            "return_period_5": 1200.0,
            "return_period_10": 1500.0,
            "return_period_25": 1900.0,
            "return_period_50": 2200.0,
            "return_period_100": 2500.0,
        },
    )
    monkeypatch.setattr(
        streamflow_mod,
        "_get_forecast_stats",
        lambda rid: {
            "peak_discharge_m3s": 750.0,
            "peak_time": "2026-02-10T15:00:00Z",
            "forecast_count": 40,
        },
    )

    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {
            "river_name": "Seine",
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    # Should succeed - the tool infers reach_id from geocoded location
    assert result.get("error") is False
    
    data = result.get("data") or {}
    assert data.get("reach_id") == 230366127
    assert data.get("river_id") == 230366127
    assert "peak_discharge_m3s" in data
    assert "risk_level" in data


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_cannot_infer_reach_id(mcp_client, monkeypatch):
    """Test streamflow tool returns error when it cannot infer reach_id from river name."""
    import tools.streamflow as streamflow_mod

    def _fake_get_city_bbox(query: str, require_confirmation: bool = True):
        return ([2.20, 48.80, 2.45, 48.92], 48.8566, 2.3522, "Some Unknown Location")

    def _fake_identify_geoglows_river_feature(lat, lon, return_geometry=False):
        # Simulate failure to find reach_id
        return None, None

    monkeypatch.setattr(streamflow_mod, "get_city_bbox", _fake_get_city_bbox)
    monkeypatch.setattr(streamflow_mod, "_identify_geoglows_river_feature", _fake_identify_geoglows_river_feature)

    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {
            "river_name": "UnknownRiver",
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    assert result.get("error") is True
    assert "river_id" in result.get("message", "").lower() or "reach_id" in result.get("message", "").lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_with_reach_id(mcp_client, monkeypatch):
    """Test streamflow tool accepts reach_id and returns forecast + risk."""
    import tools.streamflow as streamflow_mod

    def _fake_get_city_bbox(query: str, require_confirmation: bool = True):
        return ([2.20, 48.80, 2.45, 48.92], 48.8566, 2.3522, "Seine, Paris, France")

    def _fake_view_state_from_points(points, padding=0.1, min_zoom=8.0, max_zoom=12.0):
        return {"latitude": 48.8566, "longitude": 2.3522, "zoom": 10.0, "pitch": 0, "bearing": 0}

    def _fake_identify_geoglows_river_feature(lat, lon, return_geometry=False):
        geojson = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"river_id": 12345678, "reach_id": 12345678},
                "geometry": {"type": "LineString", "coordinates": [[2.3, 48.85], [2.35, 48.86]]}
            }]
        } if return_geometry else None
        return 12345678, geojson

    monkeypatch.setattr(streamflow_mod, "get_city_bbox", _fake_get_city_bbox)
    monkeypatch.setattr(streamflow_mod, "_identify_geoglows_river_feature", _fake_identify_geoglows_river_feature)
    monkeypatch.setattr(streamflow_mod, "view_state_from_points", _fake_view_state_from_points)
    monkeypatch.setattr(streamflow_mod, "_river_id_exists", lambda rid: True)
    monkeypatch.setattr(
        streamflow_mod,
        "_get_return_periods",
        lambda rid: {
            "return_period_2": 100.0,
            "return_period_5": 150.0,
            "return_period_10": 200.0,
            "return_period_25": 300.0,
            "return_period_50": 400.0,
            "return_period_100": 500.0,
        },
    )
    monkeypatch.setattr(
        streamflow_mod,
        "_get_forecast_stats",
        lambda rid: {
            "peak_discharge_m3s": 450.0,
            "peak_time": "2026-01-21T00:00:00Z",
            "forecast_count": 40,
        },
    )

    reach_id = 12345678
    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {"river_name": "Seine", "reach_id": reach_id},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    assert result.get("error") is False

    data = result.get("data") or {}
    assert data.get("reach_id") == reach_id
    assert data.get("river_id") == reach_id
    assert data.get("peak_discharge_m3s") == 450.0
    assert data.get("risk_level") in {"low", "moderate", "high", "severe", "extreme", "normal", "unknown"}

    artifacts = result.get("artifacts") or {}
    assert "urls" in artifacts
    assert any("geoglows-hydroviewer" in u for u in artifacts.get("urls", []))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_reach_id_validation(mcp_client):
    """Test streamflow tool validates reach_id."""
    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {"reach_id": -1},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    assert result.get("error") is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_unknown_reach_id(mcp_client, monkeypatch):
    """Test streamflow tool returns an error when reach_id is not found."""
    import tools.streamflow as streamflow_mod

    monkeypatch.setattr(streamflow_mod, "_river_id_exists", lambda rid: False)

    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {"reach_id": 999999999},
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    assert result.get("error") is True
    assert "not found" in result.get("message", "").lower()

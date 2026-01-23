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
async def test_streamflow_forecast_tool_requires_river_id(mcp_client, monkeypatch):
    """Test streamflow tool requests reach_id when only a name is provided."""
    import tools.streamflow as streamflow_mod

    def _fake_get_city_bbox(query: str, require_confirmation: bool = True):
        return ([2.20, 48.80, 2.45, 48.92], 48.8566, 2.3522, "Seine, Paris, France")

    monkeypatch.setattr(streamflow_mod, "get_city_bbox", _fake_get_city_bbox)

    result = await mcp_client.call_tool(
        "streamflow_forecast_tool",
        {
            "river_name": "Seine",
        },
    )

    assert isinstance(result, dict)
    assert result.get("tool_name") == "streamflow_forecast_tool"
    assert result.get("error") is True
    assert "river_id" in result.get("message", "") or "reach_id" in result.get("message", "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_streamflow_forecast_tool_with_reach_id(mcp_client, monkeypatch):
    """Test streamflow tool accepts reach_id and returns forecast + risk."""
    import tools.streamflow as streamflow_mod

    def _fake_get_city_bbox(query: str, require_confirmation: bool = True):
        return ([2.20, 48.80, 2.45, 48.92], 48.8566, 2.3522, "Seine, Paris, France")

    def _fake_view_state_from_points(points, padding=0.1, min_zoom=8.0, max_zoom=12.0):
        return {"latitude": 48.8566, "longitude": 2.3522, "zoom": 10.0, "pitch": 0, "bearing": 0}

    monkeypatch.setattr(streamflow_mod, "get_city_bbox", _fake_get_city_bbox)
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

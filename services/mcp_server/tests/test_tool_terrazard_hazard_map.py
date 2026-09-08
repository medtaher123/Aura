"""Tests for TerraZard hazard map MCP tool."""

from __future__ import annotations

import pytest


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terrazard_hazard_map_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "get_terrazard_hazard_map_tool" in tool_names


@pytest.mark.unit
def test_hazard_map_tool_requires_observation_date():
    from modules.flood.terrazard.terrazard_hazard_map import get_terrazard_hazard_map_tool

    result = get_terrazard_hazard_map_tool(
        observation_date="",
        lat=48.8566,
        lon=2.3522,
    )
    assert result.error is True
    assert "observation_date" in result.message


@pytest.mark.unit
def test_hazard_map_tool_requires_location():
    from modules.flood.terrazard.terrazard_hazard_map import get_terrazard_hazard_map_tool

    result = get_terrazard_hazard_map_tool(observation_date="20240315")
    assert result.error is True
    assert "location" in result.message.lower() and "lat/lon" in result.message.lower()


@pytest.mark.unit
def test_hazard_map_tool_location_ambiguity(monkeypatch):
    from modules.flood.terrazard import terrazard_hazard_map as mod
    from utils.bbox_service import LocationAmbiguousError

    def _raise_ambiguity(*_args, **_kwargs):
        raise LocationAmbiguousError(
            query="Paris",
            candidates=[{"display_name": "Paris, France"}, {"display_name": "Paris, Texas"}],
        )

    monkeypatch.setattr(mod, "resolve_spatial_context", _raise_ambiguity)

    result = mod.get_terrazard_hazard_map_tool(
        observation_date="20240315",
        location="Paris",
    )
    assert result.error is False
    assert result.data["needs_location_confirmation"] is True


@pytest.mark.unit
def test_hazard_map_tool_success(monkeypatch):
    from modules.flood.terrazard import terrazard_hazard_map as mod
    from modules.flood.terrazard.map_service import TerrazardMapConfig
    from modules.flood.terrazard.tile_url_builder import VectorLayerConfig
    from utils.contracts import ToolCoordinates

    monkeypatch.setattr(
        mod,
        "resolve_spatial_context",
        lambda *_args, **_kwargs: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            [48.80, 48.90, 2.20, 2.45],
            "Paris",
        ),
    )

    class StubMapService:
        def build_single_date_map(self, **_kwargs):
            return TerrazardMapConfig(
                title="TerraZard flood polygons — Paris (2024-03-15)",
                view_state={"latitude": 48.8566, "longitude": 2.3522, "zoom": 13.0},
                vector_layers=[
                    VectorLayerConfig(
                        name="Water Depth",
                        tile_url="https://tiles.example/water",
                        style="water_depth",
                        visible=True,
                    )
                ],
                reference_layers=[],
                stats={
                    "observation_date": "20240315",
                    "model_id": "flood80",
                    "water_count": 42,
                    "cloud_count": 3,
                    "total_polygons": 45,
                },
                bbox=[48.80, 48.90, 2.20, 2.45],
            )

    monkeypatch.setattr(mod, "TerrazardMapService", lambda: StubMapService())

    result = mod.get_terrazard_hazard_map_tool(
        observation_date="20240315",
        location="Paris",
    )

    assert result.error is False
    assert result.artifacts.maps
    map_spec = result.artifacts.maps[0]
    assert map_spec["renderer"] == "vector_tile"
    assert map_spec["view_state"]["latitude"] == 48.8566
    assert len(map_spec["vector_layers"]) == 1
    assert "geometry" not in map_spec
    assert result.data["stats"]["water_count"] == 42


@pytest.mark.unit
def test_hazard_map_tool_accepts_iso_observation_date(monkeypatch):
    from modules.flood.terrazard import terrazard_hazard_map as mod
    from modules.flood.terrazard.map_service import TerrazardMapConfig
    from modules.flood.terrazard.tile_url_builder import VectorLayerConfig
    from utils.contracts import ToolCoordinates

    monkeypatch.setattr(
        mod,
        "resolve_spatial_context",
        lambda *_args, **_kwargs: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            [48.80, 48.90, 2.20, 2.45],
            "Paris",
        ),
    )

    class StubMapService:
        def build_single_date_map(self, *, observation_date, **_kwargs):
            assert observation_date == "20240315"
            return TerrazardMapConfig(
                title="TerraZard flood polygons — Paris (2024-03-15)",
                view_state={"latitude": 48.8566, "longitude": 2.3522, "zoom": 13.0},
                vector_layers=[
                    VectorLayerConfig(
                        name="Water Depth",
                        tile_url="https://tiles.example/water",
                        style="water_depth",
                        visible=True,
                    )
                ],
                reference_layers=[],
                stats={
                    "observation_date": observation_date,
                    "model_id": "flood80",
                    "water_count": 1,
                    "cloud_count": 0,
                    "total_polygons": 1,
                },
                bbox=[48.80, 48.90, 2.20, 2.45],
            )

    monkeypatch.setattr(mod, "TerrazardMapService", lambda: StubMapService())

    result = mod.get_terrazard_hazard_map_tool(
        observation_date="2024-03-15",
        lat=48.8566,
        lon=2.3522,
    )

    assert result.error is False
    assert result.data["observation_date"] == "20240315"


@pytest.mark.unit
def test_hazard_map_tool_empty_data(monkeypatch):
    from modules.flood.terrazard import terrazard_hazard_map as mod
    from modules.flood.terrazard.errors import TerrazardDataError
    from utils.contracts import ToolCoordinates

    monkeypatch.setattr(
        mod,
        "resolve_spatial_context",
        lambda *_args, **_kwargs: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            [48.80, 48.90, 2.20, 2.45],
            "Paris",
        ),
    )

    class EmptyMapService:
        def build_single_date_map(self, **_kwargs):
            raise TerrazardDataError("No hazard polygon data for Paris on 20240315 (model=flood80).")

    monkeypatch.setattr(mod, "TerrazardMapService", lambda: EmptyMapService())

    result = mod.get_terrazard_hazard_map_tool(
        observation_date="20240315",
        lat=48.8566,
        lon=2.3522,
    )

    assert result.error is True
    assert "No hazard polygon data" in result.message

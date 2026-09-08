"""Tests for TerraZard flood damage MCP tool."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from modules.flood.terrazard.damage_service import FloodDamageEstimate
from utils.contracts import BoundingBox, ToolArtifacts, ToolCoordinates

_EMPTY_TOUCHED_BUILDINGS = {"type": "FeatureCollection", "features": []}
# Stay under the tool's 1 km x 1 km bbox cap (~0.4 km x 0.4 km around Paris).
_SAMPLE_BBOX = BoundingBox(
    min_lat=48.8540,
    max_lat=48.8580,
    min_lon=2.3500,
    max_lon=2.3550,
)
_SAMPLE_BBOX_LIST = _SAMPLE_BBOX.as_list()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_terrazard_flood_damage_tool_exists(mcp_client):
    tools = await mcp_client.list_tools()
    tool_names = [t["name"] for t in tools]
    assert "get_terrazard_flood_damage_tool" in tool_names


@pytest.mark.unit
def test_flood_damage_tool_bbox_schema_is_structured():
    from mcp.server.mcpserver.utilities.func_metadata import func_metadata

    from modules.flood.terrazard.terrazard_flood_damage import get_terrazard_flood_damage_tool

    meta = func_metadata(get_terrazard_flood_damage_tool)
    schema = meta.arg_model.model_json_schema()
    bbox_schema = schema["properties"]["bbox"]
    if "$ref" in bbox_schema:
        ref_name = bbox_schema["$ref"].rsplit("/", 1)[-1]
        bbox_schema = schema["$defs"][ref_name]
    assert bbox_schema["type"] == "object"
    assert set(bbox_schema.get("required", [])) >= {
        "min_lat",
        "max_lat",
        "min_lon",
        "max_lon",
    }
    assert "min_lat" in bbox_schema["properties"]
    assert "max_lat" in bbox_schema["properties"]
    assert "min_lon" in bbox_schema["properties"]
    assert "max_lon" in bbox_schema["properties"]


@pytest.mark.unit
def test_flood_damage_tool_requires_observation_date():
    from modules.flood.terrazard.terrazard_flood_damage import get_terrazard_flood_damage_tool

    result = get_terrazard_flood_damage_tool(
        observation_date="",
        bbox=_SAMPLE_BBOX,
    )
    assert result.error is True


@pytest.mark.unit
def test_flood_damage_bbox_rejects_list_and_incomplete_object():
    with pytest.raises(ValidationError):
        BoundingBox.model_validate([48.0, 49.0])
    with pytest.raises(ValidationError):
        BoundingBox.model_validate({"min_lat": 48.0, "max_lat": 49.0})


@pytest.mark.unit
def test_flood_damage_tool_success(monkeypatch):
    from modules.flood.terrazard import terrazard_flood_damage as mod

    monkeypatch.setattr(
        mod,
        "resolve_from_bbox",
        lambda bbox: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            list(bbox),
            "Paris",
        ),
    )

    class StubDamageService:
        def estimate(self, **_kwargs):
            return FloodDamageEstimate(
                observation_date="20240315",
                model_id="flood80",
                location_name="Paris",
                country="France",
                year=2025,
                depth_bands=[
                    {
                        "depth_min_m": 0.0,
                        "depth_max_m": 0.25,
                        "representative_depth_m": 0.125,
                        "flooded_area_m2": 12000.0,
                    }
                ],
                exposure_rows=[],
                by_asset_class=[
                    {"asset_class": "residential", "area_m2": 500.0, "total_damage_eur": 12000.0}
                ],
                by_depth_band=[
                    {
                        "depth_min_m": 0.0,
                        "depth_max_m": 0.25,
                        "representative_depth_m": 0.125,
                        "flooded_area_m2": 12000.0,
                        "exposed_area_m2": 500.0,
                        "total_damage_eur": 12000.0,
                    }
                ],
                total_damage_eur=12000.0,
                total_exposed_area_m2=500.0,
                total_flooded_area_m2=12000.0,
                building_count=3,
                caveats=["test caveat"],
                message="Estimated TerraZard flood damage for Paris on 20240315: €12,000",
                touched_buildings={
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [2.35, 48.85],
                                        [2.351, 48.85],
                                        [2.351, 48.851],
                                        [2.35, 48.851],
                                        [2.35, 48.85],
                                    ]
                                ],
                            },
                            "properties": {
                                "source": "bdtopo_raw.batiment",
                                "land_type": "Résidentiel",
                                "asset_class": "residential",
                                "cleabs": "BATIMENT0000000000012345",
                                "depth_min_m": 0.0,
                                "depth_max_m": 0.25,
                                "representative_depth_m": 0.125,
                                "intersection_area_m2": 40.0,
                            },
                        }
                    ],
                },
            )

    monkeypatch.setattr(mod, "FloodDamageService", lambda: StubDamageService())
    monkeypatch.setattr(
        mod,
        "_build_exposure_artifacts",
        lambda **_kwargs: ToolArtifacts(),
    )

    result = mod.get_terrazard_flood_damage_tool(
        observation_date="2024-03-15",
        bbox=_SAMPLE_BBOX,
    )

    assert result.error is False
    assert result.data["total_damage_eur"] == 12000.0
    assert result.data["building_count"] == 3
    assert result.data["by_asset_class"][0]["asset_class"] == "residential"
    assert result.data["touched_buildings"]["type"] == "FeatureCollection"
    assert len(result.data["touched_buildings"]["features"]) == 1
    assert (
        result.data["touched_buildings"]["features"][0]["properties"]["cleabs"]
        == "BATIMENT0000000000012345"
    )
    assert result.data["bbox"] == _SAMPLE_BBOX_LIST


@pytest.mark.unit
def test_flood_damage_tool_attaches_vector_tile_artifact(monkeypatch):
    from modules.flood.terrazard import terrazard_flood_damage as mod

    monkeypatch.setattr(
        mod,
        "resolve_from_bbox",
        lambda bbox: (
            ToolCoordinates(lat=48.8566, lon=2.3522),
            list(bbox),
            "Paris",
        ),
    )

    class StubDamageService:
        def estimate(self, **_kwargs):
            return FloodDamageEstimate(
                observation_date="20240315",
                model_id="flood80",
                location_name="Paris",
                country="France",
                year=2025,
                depth_bands=[],
                exposure_rows=[],
                by_asset_class=[],
                by_depth_band=[],
                total_damage_eur=12000.0,
                total_exposed_area_m2=500.0,
                total_flooded_area_m2=12000.0,
                building_count=3,
                caveats=[],
                message="ok",
                touched_buildings=_EMPTY_TOUCHED_BUILDINGS,
            )

    monkeypatch.setattr(mod, "FloodDamageService", lambda: StubDamageService())
    monkeypatch.setattr(
        mod,
        "_build_exposure_artifacts",
        lambda **_kwargs: ToolArtifacts(
            maps=[
                {
                    "renderer": "vector_tile",
                    "title": "Flood damage exposure — Paris",
                    "vector_layers": [
                        {
                            "name": "Water Depth",
                            "tile_url": "https://tiles.example/{z}/{x}/{y}.pbf",
                            "style": "water_depth",
                            "visible": True,
                        }
                    ],
                }
            ]
        ),
    )

    result = mod.get_terrazard_flood_damage_tool(
        observation_date="2024-03-15",
        bbox=_SAMPLE_BBOX,
    )

    assert result.error is False
    assert len(result.artifacts.maps) == 1
    map_spec = result.artifacts.maps[0]
    assert map_spec["renderer"] == "vector_tile"
    assert "layers" not in map_spec
    assert map_spec["vector_layers"][0]["style"] == "water_depth"


@pytest.mark.unit
def test_flood_damage_tool_passes_bbox_to_estimate(monkeypatch):
    from modules.flood.terrazard import terrazard_flood_damage as mod

    calls: dict = {}

    def fake_resolve(bbox):
        calls["bbox"] = list(bbox)
        return (
            ToolCoordinates(lat=48.5, lon=2.5),
            list(bbox),
            "drawn-area",
        )

    monkeypatch.setattr(mod, "resolve_from_bbox", fake_resolve)

    class StubDamageService:
        def estimate(self, **kwargs):
            calls["estimate_bbox"] = kwargs["bbox"]
            return FloodDamageEstimate(
                observation_date="20240315",
                model_id="flood80",
                location_name="drawn-area",
                country="France",
                year=2025,
                depth_bands=[],
                exposure_rows=[],
                by_asset_class=[],
                by_depth_band=[],
                total_damage_eur=0.0,
                total_exposed_area_m2=0.0,
                total_flooded_area_m2=0.0,
                building_count=0,
                caveats=[],
                message="ok",
                touched_buildings=_EMPTY_TOUCHED_BUILDINGS,
            )

    monkeypatch.setattr(mod, "FloodDamageService", lambda: StubDamageService())
    monkeypatch.setattr(
        mod,
        "_build_exposure_artifacts",
        lambda **_kwargs: ToolArtifacts(),
    )

    bbox = BoundingBox(min_lat=48.8500, max_lat=48.8550, min_lon=2.3400, max_lon=2.3450)
    result = mod.get_terrazard_flood_damage_tool(
        observation_date="2024-03-15",
        bbox=bbox,
    )

    assert result.error is False
    assert calls["bbox"] == bbox.as_list()
    assert calls["estimate_bbox"] == bbox.as_list()
    assert result.data["bbox"] == bbox.as_list()

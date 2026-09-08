"""Unit tests for TerraZard map artifact builder."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.map_artifact_builder import (
    build_damage_exposure_map_artifact,
    build_vector_tile_map_artifact,
)
from modules.flood.terrazard.map_service import TerrazardMapConfig
from modules.flood.terrazard.reference_layers import PRESET_PERMANENT_WATER, build_reference_layer
from modules.flood.terrazard.repository import MapStats
from modules.flood.terrazard.tile_url_builder import VectorLayerConfig
from utils.contracts import ToolCoordinates


@pytest.mark.unit
def test_build_vector_tile_map_artifact_includes_reference_layers():
    config = TerrazardMapConfig(
        title="TerraZard flood polygons — Paris (2024-03-15)",
        view_state={"latitude": 48.86, "longitude": 2.35, "zoom": 13.0},
        vector_layers=[
            VectorLayerConfig(
                name="Water Depth",
                tile_url="https://tiles.example/water",
                style="water_depth",
                visible=True,
            )
        ],
        reference_layers=[build_reference_layer(PRESET_PERMANENT_WATER)],
        stats={
            "observation_date": "20240315",
            "model_id": "flood80",
            "water_count": 42,
            "cloud_count": 0,
            "total_polygons": 42,
        },
        bbox=[48.8, 48.9, 2.2, 2.5],
    )

    artifacts = build_vector_tile_map_artifact(config)
    map_spec = artifacts.maps[0]

    assert map_spec["renderer"] == "vector_tile"
    assert len(map_spec["vector_layers"]) == 1
    assert map_spec["reference_layers"] == [
        {
            "type": "esri_land_cover",
            "preset": "permanent_water",
            "name": "Permanent Water",
            "visible": True,
        }
    ]
    assert map_spec["bbox"] == [48.8, 48.9, 2.2, 2.5]
    box = map_spec["box"]
    assert box["type"] == "Feature"
    assert box["properties"]["kind"] == "treated_area_bbox"
    assert box["geometry"]["type"] == "Polygon"
    assert box["geometry"]["coordinates"][0] == [
        [2.2, 48.8],
        [2.5, 48.8],
        [2.5, 48.9],
        [2.2, 48.9],
        [2.2, 48.8],
    ]


@pytest.mark.unit
def test_build_damage_exposure_map_artifact_composites_tile_layers(monkeypatch):
    from modules.flood.terrazard import map_artifact_builder as mod

    class FakeConfig:
        terrazard_tile_server_url = "https://terrazard-tiles.example"
        bdtopo_tile_server_url = "https://bdtopo-tiles.example"

    monkeypatch.setattr(mod, "get_config", lambda: FakeConfig())

    artifacts = build_damage_exposure_map_artifact(
        observation_date="20240315",
        model_id="flood80",
        bbox=[48.8, 48.9, 2.2, 2.5],
        coords=ToolCoordinates(lat=48.85, lon=2.35),
        location_name="Paris",
        map_stats=MapStats(
            total_polygons=10,
            water_count=8,
            cloud_count=2,
            avg_lat=48.85,
            avg_lon=2.35,
        ),
        total_damage_eur=12000.0,
        building_count=3,
        total_exposed_area_m2=500.0,
        total_flooded_area_m2=12000.0,
    )

    assert len(artifacts.maps) == 1
    map_spec = artifacts.maps[0]
    assert map_spec["renderer"] == "vector_tile"
    assert map_spec["title"] == "Flood damage exposure — Paris"
    assert "layers" not in map_spec

    layer_by_name = {layer["name"]: layer for layer in map_spec["vector_layers"]}
    assert set(layer_by_name) >= {
        "Water Depth",
        "Clouds",
        "Buildings",
        "Vegetation / land cover",
    }

    water = layer_by_name["Water Depth"]
    assert water["style"] == "water_depth"
    assert "get_hazard_layer" in water["tile_url"]
    assert "p_date=20240315" in water["tile_url"]
    assert "FeatureCollection" not in water["tile_url"]

    buildings = layer_by_name["Buildings"]
    assert buildings["style"] == "bdtopo_buildings"
    assert buildings["minzoom"] == 14
    assert "bdtopo_raw.batiment" in buildings["tile_url"]
    assert buildings["tile_url"].endswith("/{z}/{x}/{y}.pbf")

    vegetation = layer_by_name["Vegetation / land cover"]
    assert vegetation["style"] == "bdtopo_vegetation"
    assert "bdtopo_raw.zone_de_vegetation" in vegetation["tile_url"]

    assert map_spec["stats"]["total_damage_eur"] == 12000.0
    assert map_spec["stats"]["building_count"] == 3
    assert map_spec["bbox"] == [48.8, 48.9, 2.2, 2.5]
    assert map_spec["box"]["properties"]["kind"] == "treated_area_bbox"
    assert map_spec["view_state"]["zoom"] >= 14.0


@pytest.mark.unit
def test_build_damage_exposure_map_includes_touched_building_overlay(monkeypatch):
    from modules.flood.terrazard import map_artifact_builder as mod

    class FakeConfig:
        terrazard_tile_server_url = "https://terrazard-tiles.example"
        bdtopo_tile_server_url = "https://bdtopo-tiles.example"

    monkeypatch.setattr(mod, "get_config", lambda: FakeConfig())

    touched = {
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
                    "land_type": "Résidentiel",
                    "asset_class": "residential",
                    "intersection_area_m2": 12.5,
                },
            }
        ],
    }

    artifacts = build_damage_exposure_map_artifact(
        observation_date="20240315",
        model_id="flood80",
        bbox=[48.8, 48.9, 2.2, 2.5],
        coords=ToolCoordinates(lat=48.85, lon=2.35),
        location_name="Paris",
        map_stats=MapStats(10, 8, 0, 48.85, 2.35),
        total_damage_eur=100.0,
        building_count=1,
        total_exposed_area_m2=12.5,
        total_flooded_area_m2=1000.0,
        touched_buildings=touched,
    )

    map_spec = artifacts.maps[0]
    assert map_spec["geojson_overlays"][0]["name"] == "Touched buildings"
    assert map_spec["geojson_overlays"][0]["data"] == touched
    assert map_spec["stats"]["touched_building_features"] == 1


@pytest.mark.unit
def test_build_damage_exposure_map_artifact_skips_without_tile_servers(monkeypatch):
    from modules.flood.terrazard import map_artifact_builder as mod

    class FakeConfig:
        terrazard_tile_server_url = ""
        bdtopo_tile_server_url = "https://bdtopo-tiles.example"

    monkeypatch.setattr(mod, "get_config", lambda: FakeConfig())

    artifacts = build_damage_exposure_map_artifact(
        observation_date="20240315",
        model_id="flood80",
        bbox=[48.8, 48.9, 2.2, 2.5],
        coords=ToolCoordinates(lat=48.85, lon=2.35),
        location_name="Paris",
        map_stats=MapStats(10, 8, 0, 48.85, 2.35),
        total_damage_eur=1.0,
        building_count=0,
        total_exposed_area_m2=0.0,
        total_flooded_area_m2=0.0,
    )
    assert artifacts.maps == []

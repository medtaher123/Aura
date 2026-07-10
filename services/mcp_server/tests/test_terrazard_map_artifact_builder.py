"""Unit tests for TerraZard map artifact builder."""

from __future__ import annotations

import pytest

from tools.terrazard.map_artifact_builder import build_vector_tile_map_artifact
from tools.terrazard.map_service import TerrazardMapConfig
from tools.terrazard.reference_layers import build_reference_layer, PRESET_PERMANENT_WATER
from tools.terrazard.tile_url_builder import VectorLayerConfig


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

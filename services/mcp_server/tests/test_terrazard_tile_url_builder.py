"""Unit tests for TerraZard tile URL builder."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.errors import TerrazardDataError
from modules.flood.terrazard.repository import MapStats
from modules.flood.terrazard.tile_url_builder import HazardLayerTileBuilder


@pytest.mark.unit
def test_build_layer_url_includes_params():
    builder = HazardLayerTileBuilder(tile_server_url="https://tiles.example")
    url = builder._build_layer_url("20240315", "flood80", 1)

    assert url.startswith("https://tiles.example/public.get_hazard_layer/{z}/{x}/{y}.pbf?")
    assert "p_date=20240315" in url
    assert "p_class=1" in url
    assert "p_model=flood80" in url


@pytest.mark.unit
def test_build_layers_includes_water_depth():
    builder = HazardLayerTileBuilder(tile_server_url="https://tiles.example")
    stats = MapStats(total_polygons=5, water_count=5, cloud_count=0, avg_lat=1.0, avg_lon=2.0)

    layers = builder.build_layers("20240315", "flood80", stats)

    assert len(layers) == 1
    assert layers[0].name == "Water Depth"
    assert layers[0].style == "water_depth"


@pytest.mark.unit
def test_build_layers_includes_cloud_when_present():
    builder = HazardLayerTileBuilder(tile_server_url="https://tiles.example")
    stats = MapStats(total_polygons=5, water_count=5, cloud_count=2, avg_lat=1.0, avg_lon=2.0)

    layers = builder.build_layers("20240315", "flood80", stats)

    assert len(layers) == 2
    assert layers[0].name == "Water Depth"
    assert layers[1].name == "Clouds"
    assert layers[1].style == "cloud"


@pytest.mark.unit
def test_validate_model_id_rejects_unknown():
    with pytest.raises(TerrazardDataError, match="Unsupported model_id"):
        HazardLayerTileBuilder.validate_model_id("unknown-model")


@pytest.mark.unit
def test_build_layers_requires_tile_server():
    builder = HazardLayerTileBuilder(tile_server_url="")
    stats = MapStats(total_polygons=1, water_count=1, cloud_count=0, avg_lat=1.0, avg_lon=2.0)

    with pytest.raises(TerrazardDataError, match="tile server is not configured"):
        builder.build_layers("20240315", "flood80", stats)

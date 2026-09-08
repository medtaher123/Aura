"""Unit tests for TerraZard depth rasterization and BDTOPO zonal exposure."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.bdtopo_exposure import BdtopoFeature, collect_bdtopo_exposure
from modules.flood.terrazard.depth_bands import HazardDepthPolygon, build_depth_band_defs
from modules.flood.terrazard.depth_raster import build_depth_raster


# Small AOI around Arles (approx).
_BBOX = [43.67, 43.69, 4.62, 4.65]


def _square(lon: float, lat: float, half_deg: float = 0.002) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [lon - half_deg, lat - half_deg],
                [lon + half_deg, lat - half_deg],
                [lon + half_deg, lat + half_deg],
                [lon - half_deg, lat + half_deg],
                [lon - half_deg, lat - half_deg],
            ]
        ],
    }


@pytest.mark.unit
def test_build_depth_band_defs_exclusive_intervals():
    bands = build_depth_band_defs([0.0, 0.5, 1.0])
    assert len(bands) == 3
    assert bands[0].depth_min_m == 0.0
    assert bands[0].depth_max_m == 0.5
    assert bands[1].depth_min_m == 0.5
    assert bands[1].depth_max_m == 1.0
    assert bands[2].depth_min_m == 1.0
    assert bands[2].depth_max_m == 100.0


@pytest.mark.unit
def test_build_depth_raster_nested_depths_and_buffer():
    # Nested squares: deep polygon inside shallow polygon.
    shallow = HazardDepthPolygon(
        depth_min_m=0.0,
        geojson=_square(4.635, 43.68, half_deg=0.008),
    )
    deep = HazardDepthPolygon(
        depth_min_m=0.5,
        geojson=_square(4.635, 43.68, half_deg=0.003),
    )

    unbuffered = build_depth_raster(
        [shallow, deep],
        _BBOX,
        resolution_m=10.0,
        flood_buffer_m=0.0,
    )
    buffered = build_depth_raster(
        [shallow, deep],
        _BBOX,
        resolution_m=10.0,
        flood_buffer_m=20.0,
    )

    assert len(unbuffered.depth_bands) == 2
    assert unbuffered.total_flooded_area_m2 > 0
    # Deeper nested pixels should exist.
    assert (unbuffered.band_index == 2).any()
    assert (unbuffered.band_index == 1).any()
    # Buffer expands flooded extent.
    assert buffered.total_flooded_area_m2 > unbuffered.total_flooded_area_m2
    assert buffered.flood_buffer_m == 20.0


@pytest.mark.unit
def test_collect_bdtopo_exposure_zonal_stats():
    flood = HazardDepthPolygon(
        depth_min_m=0.0,
        geojson=_square(4.635, 43.68, half_deg=0.01),
    )
    depth_raster = build_depth_raster(
        [flood],
        _BBOX,
        resolution_m=10.0,
        flood_buffer_m=0.0,
    )
    building = BdtopoFeature(
        source="bdtopo_raw.batiment",
        land_type="Résidentiel",
        asset_class="residential",
        feature_id=1,
        geojson=_square(4.635, 43.68, half_deg=0.001),
        cleabs="BATIMENT0000000000012345",
    )
    dry_building = BdtopoFeature(
        source="bdtopo_raw.batiment",
        land_type="Résidentiel",
        asset_class="residential",
        feature_id=2,
        # Far outside AOI flood square.
        geojson=_square(4.0, 44.0, half_deg=0.001),
        cleabs="BATIMENT0000000000099999",
    )

    result = collect_bdtopo_exposure(depth_raster, [building, dry_building])

    assert len(result.exposure_slices) == 1
    slice_ = result.exposure_slices[0]
    assert slice_.asset_class == "residential"
    assert slice_.area_m2 > 0
    assert slice_.feature_count == 1
    assert len(result.touched_buildings["features"]) == 1
    props = result.touched_buildings["features"][0]["properties"]
    assert props["asset_class"] == "residential"
    assert props["cleabs"] == "BATIMENT0000000000012345"
    assert "band_exposures" in props
    assert props["band_exposures"]


@pytest.mark.unit
def test_flood_bbox_and_windowed_prefilter():
    flood = HazardDepthPolygon(
        depth_min_m=0.0,
        geojson=_square(4.635, 43.68, half_deg=0.005),
    )
    depth_raster = build_depth_raster(
        [flood],
        _BBOX,
        resolution_m=10.0,
        flood_buffer_m=0.0,
    )
    flood_bbox = depth_raster.flood_bbox_wgs84()
    assert flood_bbox is not None
    assert depth_raster.flooded_pixel_window() is not None

    # Flood bbox should be much smaller than the full AOI.
    assert flood_bbox[1] - flood_bbox[0] < _BBOX[1] - _BBOX[0]
    assert flood_bbox[3] - flood_bbox[2] < _BBOX[3] - _BBOX[2]

    wet = BdtopoFeature(
        source="bdtopo_raw.batiment",
        land_type="Résidentiel",
        asset_class="residential",
        feature_id=1,
        geojson=_square(4.635, 43.68, half_deg=0.001),
    )
    # Far corner of AOI; small flood around 4.635/43.68 should not reach it.
    dry = BdtopoFeature(
        source="bdtopo_raw.batiment",
        land_type="Résidentiel",
        asset_class="residential",
        feature_id=2,
        geojson=_square(4.622, 43.671, half_deg=0.0004),
    )

    result = collect_bdtopo_exposure(depth_raster, [wet, dry])
    assert len(result.touched_buildings["features"]) == 1
    assert result.exposure_slices[0].feature_count == 1

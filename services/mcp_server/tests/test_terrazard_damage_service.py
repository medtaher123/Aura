"""Unit tests for TerraZard damage service aggregation."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.damage_service import DamageBreakdownRow, FloodDamageService
from modules.flood.terrazard.depth_bands import DepthBand


@pytest.mark.unit
def test_aggregate_by_asset_and_depth():
    rows = [
        DamageBreakdownRow(
            source="bdtopo_raw.batiment",
            land_type="Résidentiel",
            asset_class="residential",
            depth_min_m=0.0,
            depth_max_m=0.25,
            representative_depth_m=0.125,
            area_m2=100.0,
            feature_count=2,
            unit_damage=10.0,
            unit="EUR/m2",
            total_damage_eur=1000.0,
        ),
        DamageBreakdownRow(
            source="bdtopo_raw.batiment",
            land_type="Commercial et services",
            asset_class="commercial",
            depth_min_m=0.25,
            depth_max_m=0.5,
            representative_depth_m=0.375,
            area_m2=50.0,
            feature_count=1,
            unit_damage=20.0,
            unit="EUR/m2",
            total_damage_eur=500.0,
        ),
    ]
    bands = [
        DepthBand(
            depth_min_m=0.0,
            depth_max_m=0.25,
            representative_depth_m=0.125,
            flooded_area_m2=1000.0,
        ),
        DepthBand(
            depth_min_m=0.25,
            depth_max_m=0.5,
            representative_depth_m=0.375,
            flooded_area_m2=500.0,
        ),
    ]

    by_asset = FloodDamageService._aggregate_by_asset(rows)
    by_depth = FloodDamageService._aggregate_by_depth(rows, bands)

    assert by_asset == [
        {"asset_class": "commercial", "area_m2": 50.0, "total_damage_eur": 500.0},
        {"asset_class": "residential", "area_m2": 100.0, "total_damage_eur": 1000.0},
    ]
    assert by_depth[0]["total_damage_eur"] == 1000.0
    assert by_depth[1]["total_damage_eur"] == 500.0


@pytest.mark.unit
def test_annotate_touched_building_damage(monkeypatch):
    def fake_unit_damage(**kwargs):
        depth = float(kwargs["depth_m"])
        return {
            "estimated_damage": 100.0 if depth < 0.3 else 200.0,
            "unit": "EUR/m2",
        }

    monkeypatch.setattr(
        "modules.flood.terrazard.damage_service.compute_unit_damage_eur",
        fake_unit_damage,
    )

    touched = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "asset_class": "residential",
                    "cleabs": "BATIMENT0000000000011111",
                    "intersection_area_m2": 30.0,
                    "representative_depth_m": 0.125,
                    "band_exposures": [
                        {
                            "representative_depth_m": 0.125,
                            "area_m2": 10.0,
                        },
                        {
                            "representative_depth_m": 0.4,
                            "area_m2": 20.0,
                        },
                    ],
                },
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": []},
                "properties": {
                    "asset_class": "residential",
                    "cleabs": "BATIMENT0000000000022222",
                    "intersection_area_m2": 5.0,
                    "representative_depth_m": 0.125,
                    "band_exposures": [
                        {"representative_depth_m": 0.125, "area_m2": 5.0},
                    ],
                },
            },
        ],
    }

    result = FloodDamageService._annotate_touched_building_damage(
        touched,
        country="France",
        year=2010,
        continent="Europe",
    )

    # 10*100 + 20*200 = 5000 should rank first
    assert result["features"][0]["properties"]["damage_eur"] == 5000.0
    assert result["features"][0]["properties"]["cleabs"] == "BATIMENT0000000000011111"
    assert result["features"][1]["properties"]["damage_eur"] == 500.0
    assert result["features"][1]["properties"]["cleabs"] == "BATIMENT0000000000022222"

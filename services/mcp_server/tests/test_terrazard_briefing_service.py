"""Unit tests for TerraZard briefing service."""

from __future__ import annotations

import pytest

from tools.terrazard.briefing_service import BriefingService
from tools.terrazard.repository import (
    AreaStats,
    DepthProfile,
    MapStats,
    WaterDateCount,
)
from utils.contracts import ToolCoordinates


class StubRepository:
    def get_water_date_counts(self, bbox, start_date, end_date):
        return [
            WaterDateCount("20240310", water_count=20, cloud_count=2),
            WaterDateCount("20240315", water_count=400, cloud_count=3),
        ]

    def get_map_stats(self, observation_date, model_id, bbox):
        return MapStats(403, 400, 3, 48.86, 2.35)

    def get_depth_profile(self, observation_date, model_id, bbox):
        return DepthProfile(
            min_depth_m=0.1,
            max_depth_m=2.1,
            median_depth_m=0.8,
            avg_depth_m=0.9,
            buckets=[{"depth_m": "0-0.25", "polygon_count": 5}],
        )

    def get_area_stats(self, observation_date, model_id, bbox):
        return AreaStats(water_area_m2=12_300_000.0, cloud_area_m2=1_100_000.0)


class StubMapService:
    def build_single_date_map(self, **kwargs):
        from tools.terrazard.map_service import TerrazardMapConfig
        from tools.terrazard.tile_url_builder import VectorLayerConfig

        return TerrazardMapConfig(
            title="Map",
            view_state={"latitude": 48.86, "longitude": 2.35, "zoom": 13},
            vector_layers=[
                VectorLayerConfig(
                    name="Water Depth",
                    tile_url="https://tiles.example/water",
                    style="water_depth",
                )
            ],
            reference_layers=[],
            stats={"observation_date": kwargs["observation_date"], "model_id": "flood80"},
            bbox=kwargs["bbox"],
        )


@pytest.mark.unit
def test_briefing_service_builds_agent_briefing():
    service = BriefingService(repository=StubRepository(), map_service=StubMapService())
    briefing = service.build(
        start_date="20240301",
        end_date="20240331",
        bbox=[48.8, 48.9, 2.2, 2.5],
        coords=ToolCoordinates(lat=48.86, lon=2.35),
        location_name="Paris",
        include_map=True,
    )

    assert briefing.recommended_date == "20240315"
    assert briefing.agent_briefing["severity"]["tier"] == "major"
    assert briefing.agent_briefing["depth_profile"]["median_depth_m"] == 0.8
    assert briefing.agent_briefing["extent"]["flooded_km2"] == 12.3
    assert briefing.artifacts.maps
    assert "TerraZard flood briefing" in briefing.message

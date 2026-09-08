"""Unit tests for TerraZard map service."""

from __future__ import annotations

import pytest

from modules.flood.terrazard.errors import TerrazardDataError
from modules.flood.terrazard.map_service import TerrazardMapService
from modules.flood.terrazard.repository import MapStats
from modules.flood.terrazard.tile_url_builder import HazardLayerTileBuilder, VectorLayerConfig
from utils.contracts import ToolCoordinates


class StubRepository:
    def __init__(self, stats: MapStats) -> None:
        self.stats = stats
        self.calls: list[tuple[str, str, list[float]]] = []

    def get_map_stats(self, observation_date: str, model_id: str, bbox: list[float]) -> MapStats:
        self.calls.append((observation_date, model_id, bbox))
        return self.stats


class StubTileBuilder(HazardLayerTileBuilder):
    def __init__(self) -> None:
        super().__init__(tile_server_url="https://tiles.example")

    def build_layers(
        self, observation_date: str, model_id: str, stats: MapStats
    ) -> list[VectorLayerConfig]:
        return [
            VectorLayerConfig(
                name="Water Depth",
                tile_url=f"https://tiles.example/water?date={observation_date}",
                style="water_depth",
                visible=True,
            )
        ]


@pytest.mark.unit
def test_build_single_date_map_success():
    stats = MapStats(total_polygons=10, water_count=8, cloud_count=2, avg_lat=48.8, avg_lon=2.3)
    service = TerrazardMapService(
        repository=StubRepository(stats),
        tile_builder=StubTileBuilder(),
    )

    config = service.build_single_date_map(
        observation_date="20240315",
        model_id="flood80",
        bbox=[48.7, 48.9, 2.2, 2.5],
        coords=ToolCoordinates(lat=48.8, lon=2.3),
        location_name="Paris",
    )

    assert config.view_state["latitude"] == 48.8
    assert config.view_state["longitude"] == 2.3
    assert config.view_state["zoom"] == 13.0
    assert len(config.vector_layers) == 1
    assert len(config.reference_layers) == 1
    assert config.reference_layers[0].preset == "permanent_water"
    assert config.stats["water_count"] == 8


@pytest.mark.unit
def test_build_single_date_map_no_data_raises():
    stats = MapStats(total_polygons=0, water_count=0, cloud_count=0, avg_lat=None, avg_lon=None)
    service = TerrazardMapService(
        repository=StubRepository(stats),
        tile_builder=StubTileBuilder(),
    )

    with pytest.raises(TerrazardDataError, match="No hazard polygon data"):
        service.build_single_date_map(
            observation_date="20240315",
            model_id="flood80",
            bbox=[48.7, 48.9, 2.2, 2.5],
            coords=ToolCoordinates(lat=48.8, lon=2.3),
            location_name="Paris",
        )

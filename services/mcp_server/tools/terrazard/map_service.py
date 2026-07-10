"""Orchestrates TerraZard map configuration from repository metadata and tile URLs."""

from __future__ import annotations

from dataclasses import dataclass

from tools.terrazard.errors import TerrazardDataError
from tools.terrazard.repository import HazardMaskRepository, MapStats
from tools.terrazard.reference_layers import (
    ReferenceLayerConfig,
    default_terrazard_reference_layers,
)
from tools.terrazard.tile_url_builder import HazardLayerTileBuilder, VectorLayerConfig
from utils.contracts import ToolCoordinates
from utils.map_view_service import view_state_from_bbox


@dataclass(frozen=True)
class TerrazardMapConfig:
    title: str
    view_state: dict[str, float]
    vector_layers: list[VectorLayerConfig]
    stats: dict[str, int | str]
    bbox: list[float]
    reference_layers: list[ReferenceLayerConfig]


class TerrazardMapService:
    """Build lightweight map configs for TerraZard hazard visualization."""

    def __init__(
        self,
        repository: HazardMaskRepository | None = None,
        tile_builder: HazardLayerTileBuilder | None = None,
    ) -> None:
        self._repository = repository or HazardMaskRepository()
        self._tile_builder = tile_builder or HazardLayerTileBuilder()

    @staticmethod
    def _view_state_from_stats(
        stats: MapStats, coords: ToolCoordinates, bbox: list[float]
    ) -> dict[str, float]:
        if stats.avg_lat is not None and stats.avg_lon is not None:
            return {
                "latitude": stats.avg_lat,
                "longitude": stats.avg_lon,
                "zoom": 13.0,
            }

        center = ToolCoordinates(
            lat=(bbox[0] + bbox[1]) / 2,
            lon=(bbox[2] + bbox[3]) / 2,
        )
        return view_state_from_bbox(
            center or coords,
            padding=0.18,
            min_zoom=5.0,
            max_zoom=13.0,
        )

    def build_single_date_map(
        self,
        *,
        observation_date: str,
        model_id: str,
        bbox: list[float],
        coords: ToolCoordinates,
        location_name: str,
    ) -> TerrazardMapConfig:
        validated_model = self._tile_builder.validate_model_id(model_id)
        stats = self._repository.get_map_stats(observation_date, validated_model, bbox)

        if stats.total_polygons <= 0:
            raise TerrazardDataError(
                f"No hazard polygon data for {location_name} on {observation_date} "
                f"(model={validated_model})."
            )

        vector_layers = self._tile_builder.build_layers(
            observation_date, validated_model, stats
        )
        if not vector_layers:
            raise TerrazardDataError(
                f"No renderable hazard layers for {location_name} on {observation_date}."
            )

        iso_date = f"{observation_date[:4]}-{observation_date[4:6]}-{observation_date[6:8]}"
        return TerrazardMapConfig(
            title=f"TerraZard flood polygons — {location_name} ({iso_date})",
            view_state=self._view_state_from_stats(stats, coords, bbox),
            vector_layers=vector_layers,
            reference_layers=default_terrazard_reference_layers(),
            stats={
                "observation_date": observation_date,
                "model_id": validated_model,
                "water_count": stats.water_count,
                "cloud_count": stats.cloud_count,
                "total_polygons": stats.total_polygons,
            },
            bbox=bbox,
        )

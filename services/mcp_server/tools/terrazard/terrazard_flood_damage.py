"""MCP tool for TerraZard flood damage using BDTOPO land exposure."""

from __future__ import annotations

from core.logger import get_logger
from mcp_singleton import mcp
from tools.terrazard.damage_service import FloodDamageService
from tools.terrazard.map_artifact_builder import build_damage_exposure_map_artifact
from tools.terrazard.repository import HazardMaskRepository
from tools.terrazard.spatial import (
    handle_terrazard_error,
    normalize_terrazard_date,
    resolve_from_bbox,
)
from utils.contracts import ToolArtifacts, ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_flood_damage_tool"


def _build_exposure_artifacts(
    *,
    observation_date: str,
    model_id: str,
    bbox: list[float],
    coords,
    location_name: str,
    total_damage_eur: float,
    building_count: int,
    total_exposed_area_m2: float,
    total_flooded_area_m2: float,
    touched_buildings: dict | None = None,
) -> ToolArtifacts:
    """Best-effort map artifact; never fails the numeric damage response."""
    try:
        map_stats = HazardMaskRepository().get_map_stats(
            observation_date, model_id, bbox
        )
        return build_damage_exposure_map_artifact(
            observation_date=observation_date,
            model_id=model_id,
            bbox=bbox,
            coords=coords,
            location_name=location_name,
            map_stats=map_stats,
            total_damage_eur=total_damage_eur,
            building_count=building_count,
            total_exposed_area_m2=total_exposed_area_m2,
            total_flooded_area_m2=total_flooded_area_m2,
            touched_buildings=touched_buildings,
        )
    except Exception as exc:
        logger.warning("Could not build flood damage exposure map: %s", exc)
        return ToolArtifacts()


@mcp.tool()
def get_terrazard_flood_damage_tool(
    observation_date: str,
    bbox: list[float],
    model_id: str | None = None,
    country: str = "France",
    year: int | None = None,
    continent: str = "Europe",
) -> ToolResponse:
    """
    Estimate flood damage from TerraZard observed flood polygons and BDTOPO land use.

    TerraZard hazard polygons are nested by minimum depth (e.g. >=0 m, >=0.25 m).
    This tool derives exclusive depth bands, clips BDTOPO buildings and agricultural
    land onto each band, and applies JRC depth-damage curves by land type.

    Requires an explicit ``bbox`` ``[min_lat, max_lat, min_lon, max_lon]`` for the
    analysis area (typically a user-drawn map selection).

    On success, also returns a light vector-tile map artifact stacking TerraZard
    flood tiles with BDTOPO buildings and vegetation (tile URLs only).
    """
    try:
        normalized_date = normalize_terrazard_date(
            observation_date, field_name="observation_date"
        )
        coords, resolved_bbox, resolved_name = resolve_from_bbox(bbox)
        estimate = FloodDamageService().estimate(
            observation_date=normalized_date,
            bbox=resolved_bbox,
            location_name=resolved_name,
            model_id=model_id,
            country=country,
            year=year,
            continent=continent,
        )

        artifacts = _build_exposure_artifacts(
            observation_date=estimate.observation_date,
            model_id=estimate.model_id,
            bbox=resolved_bbox,
            coords=coords,
            location_name=resolved_name,
            total_damage_eur=estimate.total_damage_eur,
            building_count=estimate.building_count,
            total_exposed_area_m2=estimate.total_exposed_area_m2,
            total_flooded_area_m2=estimate.total_flooded_area_m2,
            touched_buildings=estimate.touched_buildings,
        )

        return ToolResponse(
            tool_name=TOOL_NAME,
            message=estimate.message,
            city=resolved_name,
            coordinates=coords,
            artifacts=artifacts,
            data={
                "observation_date": estimate.observation_date,
                "model_id": estimate.model_id,
                "country": estimate.country,
                "year": estimate.year,
                "total_damage_eur": estimate.total_damage_eur,
                "total_exposed_area_m2": estimate.total_exposed_area_m2,
                "total_flooded_area_m2": estimate.total_flooded_area_m2,
                "building_count": estimate.building_count,
                "depth_bands": estimate.depth_bands,
                "by_asset_class": estimate.by_asset_class,
                "by_depth_band": estimate.by_depth_band,
                "exposure_rows": estimate.exposure_rows,
                "touched_buildings": estimate.touched_buildings,
                "caveats": estimate.caveats,
                "bbox": resolved_bbox,
            },
            error=False,
        )

    except Exception as exc:
        known = handle_terrazard_error(TOOL_NAME, exc)
        if known is not None:
            return known

        logger.error("Unexpected error in TerraZard flood damage tool: %s", exc)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"Internal error estimating TerraZard flood damage: {exc}",
            error=True,
        )

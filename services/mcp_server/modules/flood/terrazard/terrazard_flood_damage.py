"""MCP tool for TerraZard flood damage using BDTOPO land exposure."""

from __future__ import annotations

from geopy.distance import geodesic

from core.logger import get_logger
from modules.flood.terrazard.damage_service import FloodDamageService
from modules.flood.terrazard.map_artifact_builder import build_damage_exposure_map_artifact
from modules.flood.terrazard.repository import HazardMaskRepository
from modules.flood.terrazard.spatial import (
    handle_terrazard_error,
    parse_terrazard_date,
    resolve_from_bbox,
)
from utils.contracts import BoundingBox, ToolArtifacts, ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_flood_damage_tool"
BBOX_MAX_SIDE_KM = 1000.0


def _bbox_side_lengths_km(bbox: list[float]) -> tuple[float, float]:
    """Return ``(width_km, height_km)`` for ``[min_lat, max_lat, min_lon, max_lon]``."""
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    mid_lat = (min_lat + max_lat) / 2.0
    mid_lon = (min_lon + max_lon) / 2.0
    height_km = geodesic((min_lat, mid_lon), (max_lat, mid_lon)).kilometers
    width_km = geodesic((mid_lat, min_lon), (mid_lat, max_lon)).kilometers
    return width_km, height_km


def is_bbox_within_limit(
    bbox: list[float], *, max_side_km: float = BBOX_MAX_SIDE_KM
) -> bool:
    """True when both bbox sides are at most ``max_side_km`` (default 1000 km)."""
    width_km, height_km = _bbox_side_lengths_km(bbox)
    return width_km <= max_side_km and height_km <= max_side_km


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


def get_terrazard_flood_damage_tool(
    observation_date: str,
    bbox: BoundingBox,
    # model_id: str | None = None,
    country: str = "France",
    # year: int | None = None,
    continent: str = "Europe",
) -> ToolResponse:
    f"""
    Estimate flood damage from TerraZard observed flood polygons and BDTOPO land use.

    TerraZard hazard polygons are nested by minimum depth (e.g. >=0 m, >=0.25 m).
    This tool derives exclusive depth bands, clips BDTOPO buildings and agricultural
    land onto each band, and applies JRC depth-damage curves by land type.

    Requires an explicit ``bbox`` object with named fields
    ``min_lat``, ``max_lat``, ``min_lon``, ``max_lon`` (WGS84 degrees) for the
    analysis area (typically a user-drawn map selection).
    The bounding box can be retrieved by using the bounding box input.
    If the bounding box is not available, call the bounding box input to get the bounding box.

    On success, also returns a light vector-tile map artifact stacking TerraZard
    flood tiles with BDTOPO buildings and vegetation (tile URLs only).

    this tool is only available for France.
    The calculation is heavy and takes time, the bouding box should not be larger than {BBOX_MAX_SIDE_KM:.0f}km x {BBOX_MAX_SIDE_KM:.0f}km.
    the smaller the better
    """

    if country.lower() != "france":
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"This tool is only available for France. Got {country}.",
            error=True,
        )

    bbox_list = bbox.as_list()
    if not is_bbox_within_limit(bbox_list):
        width_km, height_km = _bbox_side_lengths_km(bbox_list)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=(
                f"The bounding box should not be larger than "
                f"{BBOX_MAX_SIDE_KM:.0f}km x {BBOX_MAX_SIDE_KM:.0f}km. "
                f"Got {width_km:.1f}km x {height_km:.1f}km."
            ),
            error=True,
        )

    try:
        obs_date = parse_terrazard_date(
            observation_date, field_name="observation_date"
        )
        coords, resolved_bbox, resolved_name = resolve_from_bbox(bbox_list)
        estimate = FloodDamageService().estimate(
            observation_date=obs_date,
            bbox=resolved_bbox,
            location_name=resolved_name,
            # model_id=model_id,
            country=country,
            # year=year,
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

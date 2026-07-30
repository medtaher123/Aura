"""MCP tool for TerraZard flood damage using BDTOPO land exposure."""

from __future__ import annotations

from core.logger import get_logger
from mcp_singleton import mcp
from tools.terrazard.damage_service import FloodDamageService
from tools.terrazard.spatial import (
    handle_location_ambiguity,
    handle_terrazard_error,
    normalize_terrazard_date,
    resolve_spatial_context,
)
from utils.contracts import ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_flood_damage_tool"


@mcp.tool()
def get_terrazard_flood_damage_tool(
    observation_date: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    bbox: list[float] | None = None,
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

    Prefer an explicit ``bbox`` ``[min_lat, max_lat, min_lon, max_lon]`` when the
    user selected a map area; otherwise fall back to ``location`` or ``lat``/``lon``.
    """
    try:
        normalized_date = normalize_terrazard_date(
            observation_date, field_name="observation_date"
        )
        coords, resolved_bbox, resolved_name = resolve_spatial_context(
            location, lat, lon, bbox=bbox
        )
        estimate = FloodDamageService().estimate(
            observation_date=normalized_date,
            bbox=resolved_bbox,
            location_name=resolved_name,
            model_id=model_id,
            country=country,
            year=year,
            continent=continent,
        )

        return ToolResponse(
            tool_name=TOOL_NAME,
            message=estimate.message,
            city=resolved_name,
            coordinates=coords,
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
                "caveats": estimate.caveats,
                "bbox": resolved_bbox,
            },
            error=False,
        )

    except Exception as exc:
        ambiguous = handle_location_ambiguity(
            tool_name=TOOL_NAME,
            error=exc,
            location=location,
            extra_data={"observation_date": observation_date},
        )
        if ambiguous is not None:
            return ambiguous

        known = handle_terrazard_error(TOOL_NAME, exc)
        if known is not None:
            return known

        logger.error("Unexpected error in TerraZard flood damage tool: %s", exc)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"Internal error estimating TerraZard flood damage: {exc}",
            error=True,
        )

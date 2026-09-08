"""MCP tool for TerraZard available observation dates."""

from __future__ import annotations

from core.logger import get_logger
from modules.flood.terrazard.map_artifact_builder import build_location_map_artifact
from modules.flood.terrazard.repository import HazardMaskRepository
from modules.flood.terrazard.spatial import (
    handle_location_ambiguity,
    handle_terrazard_error,
    resolve_spatial_context,
    validate_dates,
)
from utils.contracts import ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_available_dates_tool"

def get_terrazard_available_dates_tool(
    start_date: str,
    end_date: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> ToolResponse:
    """
    Retrieve available satellite observation dates and water polygon counts
    for a specific location and date range in the TerraZard system.
    """
    try:
        start_date, end_date = validate_dates(start_date, end_date)
        coords, bbox, resolved_name = resolve_spatial_context(location, lat, lon)
        available_days = HazardMaskRepository().get_date_counts(bbox, start_date, end_date)

        message = (
            f"Found {len(available_days)} observation date(s) for {resolved_name} "
            f"between {start_date} and {end_date}."
        )

        return ToolResponse(
            tool_name=TOOL_NAME,
            message=message,
            artifacts=build_location_map_artifact(coords, bbox, resolved_name),
            start_date=start_date,
            end_date=end_date,
            city=resolved_name,
            coordinates=coords,
            data={"available_days": available_days, "bbox": bbox},
            error=False,
        )

    except Exception as exc:
        ambiguous = handle_location_ambiguity(
            tool_name=TOOL_NAME,
            error=exc,
            location=location,
            extra_data={"start_date": start_date, "end_date": end_date},
        )
        if ambiguous is not None:
            return ambiguous

        known = handle_terrazard_error(TOOL_NAME, exc)
        if known is not None:
            return known

        logger.error("Unexpected error in TerraZard dates tool: %s", exc)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"Internal error accessing TerraZard data: {exc}",
            error=True,
        )

"""MCP tool for composite TerraZard flood briefings."""

from __future__ import annotations

from core.logger import get_logger
from mcp_singleton import mcp
from tools.terrazard.briefing_service import BriefingService
from tools.terrazard.spatial import (
    handle_location_ambiguity,
    handle_terrazard_error,
    resolve_spatial_context,
    validate_dates,
)
from utils.contracts import ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_flood_briefing_tool"


@mcp.tool()
def get_terrazard_flood_briefing_tool(
    start_date: str,
    end_date: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    observation_date: str | None = None,
    model_id: str | None = None,
    include_map: bool = True,
) -> ToolResponse:
    """
    Build a composite TerraZard flood briefing for the agent.

    Searches a date range, selects the best observation date (or uses observation_date),
    and returns severity, depth profile, extent, temporal anomaly context, and optional map.
    """
    normalized_observation_date: str | None = None
    try:
        start_date, end_date = validate_dates(start_date, end_date)
        if observation_date:
            from tools.terrazard.spatial import normalize_terrazard_date

            normalized_observation_date = normalize_terrazard_date(
                observation_date, field_name="observation_date"
            )

        coords, bbox, resolved_name = resolve_spatial_context(location, lat, lon)
        briefing = BriefingService().build(
            start_date=start_date,
            end_date=end_date,
            bbox=bbox,
            coords=coords,
            location_name=resolved_name,
            observation_date=normalized_observation_date,
            model_id=model_id,
            include_map=include_map,
        )

        return ToolResponse(
            tool_name=TOOL_NAME,
            message=briefing.message,
            artifacts=briefing.artifacts,
            start_date=start_date,
            end_date=end_date,
            city=resolved_name,
            coordinates=coords,
            data={
                "agent_briefing": briefing.agent_briefing,
                "recommended_date": briefing.recommended_date,
                "available_dates": briefing.available_dates,
                "bbox": bbox,
            },
            error=False,
        )

    except Exception as exc:
        ambiguous = handle_location_ambiguity(
            tool_name=TOOL_NAME,
            error=exc,
            location=location,
            extra_data={
                "start_date": start_date,
                "end_date": end_date,
                "observation_date": observation_date,
            },
        )
        if ambiguous is not None:
            return ambiguous

        known = handle_terrazard_error(TOOL_NAME, exc)
        if known is not None:
            return known

        logger.error("Unexpected error in TerraZard flood briefing tool: %s", exc)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"Internal error accessing TerraZard data: {exc}",
            error=True,
        )

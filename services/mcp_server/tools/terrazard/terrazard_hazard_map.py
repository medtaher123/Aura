"""MCP tool for single-date TerraZard hazard polygon map artifacts."""

from __future__ import annotations

from config import get_config
from core.logger import get_logger
from mcp_singleton import mcp
from tools.terrazard.map_artifact_builder import build_vector_tile_map_artifact
from tools.terrazard.map_service import TerrazardMapService
from tools.terrazard.spatial import (
    handle_location_ambiguity,
    handle_terrazard_error,
    resolve_spatial_context,
    validate_observation_date,
)
from utils.contracts import ToolResponse

logger = get_logger(__name__)

TOOL_NAME = "get_terrazard_hazard_map_tool"


def _resolve_model_id(model_id: str | None) -> str:
    return (model_id or get_config().terrazard_default_model).strip()


@mcp.tool()
def get_terrazard_hazard_map_tool(
    observation_date: str,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    model_id: str | None = _resolve_model_id(None),
) -> ToolResponse:
    """
    Return a vector-tile map artifact for TerraZard hazard polygons on a single date.

    observation_date accepts YYYYMMDD or YYYY-MM-DD (e.g. 20240315 or 2024-03-15).
    The artifact contains map parameters (view_state, tile URLs, style presets) rather
    than full polygon geometry. Polygons are rendered client-side from pg_tileserv MVT tiles.
    """
    try:
        observation_date = validate_observation_date(observation_date)
        resolved_model = _resolve_model_id(model_id)

        coords, bbox, resolved_name = resolve_spatial_context(location, lat, lon)
        map_config = TerrazardMapService().build_single_date_map(
            observation_date=observation_date,
            model_id=resolved_model,
            bbox=bbox,
            coords=coords,
            location_name=resolved_name,
        )

        iso_date = (
            f"{observation_date[:4]}-{observation_date[4:6]}-{observation_date[6:8]}"
        )
        message = (
            f"TerraZard hazard map for {resolved_name} on {iso_date}: "
            f"{map_config.stats['water_count']} flood polygon(s), "
            f"{map_config.stats['cloud_count']} cloud polygon(s)."
        )

        return ToolResponse(
            tool_name=TOOL_NAME,
            message=message,
            artifacts=build_vector_tile_map_artifact(map_config),
            start_date=observation_date,
            end_date=observation_date,
            city=resolved_name,
            coordinates=coords,
            data={
                "observation_date": observation_date,
                "model_id": resolved_model,
                "stats": map_config.stats,
                "bbox": bbox,
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

        logger.error("Unexpected error in TerraZard hazard map tool: %s", exc)
        return ToolResponse(
            tool_name=TOOL_NAME,
            message=f"Internal error accessing TerraZard data: {exc}",
            error=True,
        )

"""Hazards MCP module: fire, disaster events, CEMS, CLMS."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule
from core.requirements import ConfigRequirement

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


class HazardsModule(BaseModule):
    name = "hazards"
    version = "1.0.0"
    requirements = [
        ConfigRequirement(
            name="map_key",
            config_attr="map_key",
            required=False,
            label="NASA FIRMS map key",
        ),
    ]

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.hazards.cems_rapid_mapping_events import (
            cems_rapid_mapping_events_tool,
        )
        from modules.hazards.clms_burnt_area_impact import clms_burnt_area_impact_tool
        from modules.hazards.clms_land_cover_exposure import (
            clms_land_cover_exposure_tool,
        )
        from modules.hazards.disaster_detection import query_disaster_events_tool
        from modules.hazards.fire_detection import detect_fire_tool

        for fn in (
            detect_fire_tool,
            query_disaster_events_tool,
            cems_rapid_mapping_events_tool,
            clms_burnt_area_impact_tool,
            clms_land_cover_exposure_tool,
        ):
            mcp.add_tool(fn)

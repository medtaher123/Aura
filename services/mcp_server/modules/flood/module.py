"""Flood MCP module: TerraZard, GeoServer risk, damage, streamflow, drought."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule
from core.requirements import (
    ConfigRequirement,
    ConnectionRequirement,
    ModuleRequirement,
    http_probe,
    sqlalchemy_probe,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


class FloodModule(BaseModule):
    name = "flood"
    version = "1.0.0"
    requirements = [
        ModuleRequirement(name="geospatial", required=True, label="Geospatial module"),
        ConnectionRequirement(
            name="terrazard_database",
            config_attr="terrazard_database_url",
            probe=sqlalchemy_probe("terrazard_database_url"),
            required=True,
            label="TerraZard Postgres",
        ),
        ConnectionRequirement(
            name="geoserver",
            config_attr="geoserver_base_url",
            probe=http_probe("geoserver_base_url", path="/"),
            required=False,
            label="GeoServer",
        ),
        ConfigRequirement(
            name="opentopo_api_key",
            config_attr="opentopo_api_key",
            required=False,
            label="OpenTopography API key",
        ),
        ConfigRequirement(
            name="terrazard_tiles",
            config_attr="terrazard_tile_server_url",
            required=False,
            label="TerraZard tile server URL",
        ),
    ]

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.flood.flood_damage_city import flood_damage_city_tool
        from modules.flood.flood_depth_damage import flood_depth_damage_tool
        from modules.flood.floods_and_droughts import drought_flood_risk_tool
        from modules.flood.geoserver import geoserver_risk_mask_tool
        from modules.flood.streamflow import streamflow_forecast_tool
        from modules.flood.terrazard.terrazard_available_dates import (
            get_terrazard_available_dates_tool,
        )
        from modules.flood.terrazard.terrazard_flood_briefing import (
            get_terrazard_flood_briefing_tool,
        )
        from modules.flood.terrazard.terrazard_flood_damage import (
            get_terrazard_flood_damage_tool,
        )
        from modules.flood.terrazard.terrazard_hazard_map import (
            get_terrazard_hazard_map_tool,
        )
        from modules.flood.water_ingress import estimate_surface_water_ingress_tool

        for fn in (
            #get_terrazard_available_dates_tool,
            #get_terrazard_hazard_map_tool,
            get_terrazard_flood_briefing_tool,
            get_terrazard_flood_damage_tool,
            geoserver_risk_mask_tool,
            estimate_surface_water_ingress_tool,
            flood_depth_damage_tool,
            flood_damage_city_tool,
            streamflow_forecast_tool,
            drought_flood_risk_tool,
        ):
            self.add_tool(mcp, fn)

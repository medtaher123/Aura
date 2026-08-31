"""Geospatial MCP module: BDTOPO PostGIS tools and OSM infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule
from core.requirements import (
    ConfigRequirement,
    ConnectionRequirement,
    postgres_probe,
)

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


class GeospatialModule(BaseModule):
    name = "geospatial"
    version = "1.0.0"
    requirements = [
        ConnectionRequirement(
            name="bdtopo_database",
            config_attr="bdtopo_database_url",
            probe=postgres_probe("bdtopo_database_url"),
            required=True,
            label="BDTOPO PostGIS",
        ),
        ConfigRequirement(
            name="bdtopo_tiles",
            config_attr="bdtopo_tile_server_url",
            required=False,
            label="BDTOPO tile server URL",
        ),
        ConfigRequirement(
            name="athena_osm",
            config_attr="athena_output",
            required=False,
            label="Athena OSM output",
        ),
    ]

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.geospatial.bdtopo import bdtopo_query_tool
        from modules.geospatial.bdtopo_change import bdtopo_change_snapshot_tool
        from modules.geospatial.bdtopo_explain import bdtopo_thematic_explain_tool
        from modules.geospatial.bdtopo_intersection import bdtopo_intersection_tool
        from modules.geospatial.bdtopo_quality import bdtopo_coverage_quality_tool
        from modules.geospatial.bdtopo_visualize import bdtopo_visualize_tool
        from modules.geospatial.infrastructure import infrastructure_query_tool

        for fn in (
            bdtopo_query_tool,
            bdtopo_intersection_tool,
            bdtopo_coverage_quality_tool,
            bdtopo_change_snapshot_tool,
            bdtopo_thematic_explain_tool,
            bdtopo_visualize_tool,
            infrastructure_query_tool,
        ):
            self.add_tool(mcp, fn)

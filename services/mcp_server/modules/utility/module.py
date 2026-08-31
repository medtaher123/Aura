"""Utility MCP module: general-purpose and meta tools."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


class UtilityModule(BaseModule):
    name = "utility"
    version = "1.0.0"
    requirements = []

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.utility.geographic_info import geo_info_tool
        from modules.utility.itinerary import get_route_info
        from modules.utility.simple_tools import calculator, get_date, get_time
        from modules.utility.tools_info import tools_info_tool
        from modules.utility.web_search import web_search_tool

        for fn in (
            get_time,
            get_date,
            calculator,
            tools_info_tool,
            web_search_tool,
            geo_info_tool,
            get_route_info,
        ):
            self.add_tool(mcp, fn)

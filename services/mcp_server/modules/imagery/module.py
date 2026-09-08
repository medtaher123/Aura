"""Imagery MCP module: STAC catalog and Maxar open data."""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.base import BaseModule
from core.requirements import ConnectionRequirement, http_probe

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


class ImageryModule(BaseModule):
    name = "imagery"
    version = "1.0.0"
    requirements = [
        ConnectionRequirement(
            name="maxar_stac",
            config_attr="maxar_stac_catalog_url",
            probe=http_probe("maxar_stac_catalog_url"),
            required=False,
            label="Maxar STAC catalog",
        ),
    ]

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.imagery.maxar_open_data import maxar_open_data_imagery_tool
        from modules.imagery.tools_stac import query_stac_catalog

        for fn in (query_stac_catalog, maxar_open_data_imagery_tool):
            self.add_tool(mcp, fn)

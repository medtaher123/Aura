"""Geospatial MCP module: BDTOPO PostGIS tools and OSM infrastructure."""

from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg

from core.base import BaseModule
from core.logger import get_logger
from core.requirements import (
    ConfigRequirement,
    ConnectionRequirement,
    postgres_probe,
)
from modules.geospatial.bdtopo_common import resolve_database_url

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from core.context import SharedContext


logger = get_logger(__name__)
_BATIMENT_CLEABS_INDEX = "idx_batiment_cleabs"
_BATIMENT_CLEABS_INDEX_DDL = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
    f"{_BATIMENT_CLEABS_INDEX} ON bdtopo_raw.batiment (cleabs)"
)
_BATIMENT_ANALYZE_SQL = "ANALYZE bdtopo_raw.batiment"


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

    async def initialize(self, context: SharedContext) -> None:
        database_url = resolve_database_url()
        if not database_url:
            return

        try:
            with psycopg.connect(database_url, autocommit=True) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM pg_indexes
                        WHERE schemaname = 'bdtopo_raw'
                          AND tablename = 'batiment'
                          AND indexname = %s
                        LIMIT 1
                        """,
                        (_BATIMENT_CLEABS_INDEX,),
                    )
                    if cursor.fetchone():
                        return

                    logger.info(
                        "Creating missing BDTOPO index %s on bdtopo_raw.batiment(cleabs)",
                        _BATIMENT_CLEABS_INDEX,
                    )
                    cursor.execute(_BATIMENT_CLEABS_INDEX_DDL)
                    cursor.execute(_BATIMENT_ANALYZE_SQL)
        except Exception as exc:  # noqa: BLE001 - startup should remain resilient
            logger.warning(
                "Failed to ensure BDTOPO cleabs index during geospatial initialization: %s",
                exc,
            )

    def register_tools(self, mcp: MCPServer, context: SharedContext) -> None:
        from modules.geospatial.bdtopo import bdtopo_query_tool
        from modules.geospatial.bdtopo_change import bdtopo_change_snapshot_tool
        from modules.geospatial.bdtopo_explain import bdtopo_thematic_explain_tool
        from modules.geospatial.bdtopo_intersection import bdtopo_intersection_tool
        from modules.geospatial.bdtopo_quality import bdtopo_coverage_quality_tool
        from modules.geospatial.bdtopo_visualize import bdtopo_visualize_tool
        from modules.geospatial.infrastructure import (
            bdtopo_buildings_by_cleabs_tool,
            infrastructure_query_tool,
        )

        for fn in (
            bdtopo_query_tool,
            bdtopo_intersection_tool,
            bdtopo_coverage_quality_tool,
            bdtopo_change_snapshot_tool,
            bdtopo_thematic_explain_tool,
            bdtopo_visualize_tool,
            bdtopo_buildings_by_cleabs_tool,
            infrastructure_query_tool,
        ):
            self.add_tool(mcp, fn)

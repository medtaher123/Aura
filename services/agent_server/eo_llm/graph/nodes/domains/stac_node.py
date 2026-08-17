"""STAC domain node."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext, omit_none


class StacNode(ToolPlanDomainNode):
    domain_name = "stac"
    status_message = "Searching the satellite catalog..."
    tools = [
        "query_stac_catalog",
        "maxar_open_data_imagery_tool",
    ]

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        return {
            "query_stac_catalog": omit_none(
                {
                    **ctx.known_coords(),
                    "city": ctx.display_name or None,
                    "limit_per_day": 2,
                }
            ),
            "maxar_open_data_imagery_tool": omit_none(
                {
                    "country": ctx.country_name or None,
                    "year": datetime.utcnow().year,
                }
            ),
        }


stac_node = StacNode()

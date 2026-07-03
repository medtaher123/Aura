"""STAC domain node."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eo_llm.graph.nodes.domain_base import ToolPlanDomainNode
from eo_llm.graph.nodes.helpers import LocationContext


class StacNode(ToolPlanDomainNode):
    @property
    def domain_name(self) -> str:
        return "stac"

    @property
    def missing_location_message(self) -> str:
        return "Missing resolved lat/lon; STAC tool not called."

    def build_runtime_args(self, ctx: LocationContext) -> dict[str, dict[str, Any]]:
        lat = float(ctx.lat)  # type: ignore[arg-type]
        lon = float(ctx.lon)  # type: ignore[arg-type]
        return {
            "query_stac_catalog": {
                "lat": lat,
                "lon": lon,
                "city": ctx.display_name or None,
                "limit_per_day": 2,
            },
            "maxar_open_data_imagery_tool": {
                "country": ctx.country_name or None,
                "year": datetime.utcnow().year,
            },
        }


stac_node = StacNode()

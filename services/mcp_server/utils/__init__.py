"""
MCP Server Utilities

Shared utilities for tools
These utilities are only used by tools and can be safely included in MCP server.
"""

from .bbox_service import (
    LocationAmbiguousError,
    LocationCandidate,
    get_city_bbox,
    get_city_candidates,
)
from .map_view_service import (
    view_state_from_bbox,
    view_state_from_points,
    bbox_from_points,
)

__all__ = [
    # bbox_service exports
    "LocationAmbiguousError",
    "LocationCandidate",
    "get_city_bbox",
    "get_city_candidates",
    # map_view_service exports
    "view_state_from_bbox",
    "view_state_from_points",
    "bbox_from_points",
]

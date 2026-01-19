"""
MCP Tools Registry - FastMCP SDK

Tools are automatically registered via @mcp.tool() decorators.
This __init__.py is retained for backwards compatibility but is no longer
required for tool registration with FastMCP.
"""

from tools.simple_tools import get_time, get_date, calculator
from tools.hazard_detection import query_hazards_tool
from tools.fire_detection import detect_fire_tool
from tools.disaster_detection import query_disaster_events_tool
from tools.water_ingress import estimate_surface_water_ingress_tool
from tools.tools_stac import query_stac_catalog
from tools.itinerary import get_route_info
from tools.risk_geoserver import geoserver_risk_mask_tool
from tools.weather import weather_tool
from tools.geographic_info import geo_info_tool


__all__ = [
    "query_hazards_tool",
    "detect_fire_tool",
    "query_disaster_events_tool",
    "estimate_surface_water_ingress_tool",
    "query_stac_catalog",
    "get_route_info",
    "geoserver_risk_mask_tool",
    "weather_tool",
    "geo_info_tool",
    "get_time",
    "get_date",
    "calculator",
]

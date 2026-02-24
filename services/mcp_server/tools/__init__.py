"""
MCP Tools Registry - FastMCP SDK

Tools are automatically registered via @mcp.tool() decorators.
This __init__.py is retained for backwards compatibility but is no longer
required for tool registration with FastMCP.
"""

from tools.simple_tools import get_time, get_date, calculator
from tools.fire_detection import detect_fire_tool
from tools.disaster_detection import query_disaster_events_tool
from tools.water_ingress import estimate_surface_water_ingress_tool
from tools.tools_stac import query_stac_catalog
from tools.itinerary import get_route_info
from tools.risk_geoserver import geoserver_risk_mask_tool
from tools.weather import weather_tool
from tools.geographic_info import geo_info_tool
from tools.flood_depth_damage import flood_depth_damage_tool
from tools.streamflow import streamflow_forecast_tool
from tools.floods_and_droughts import drought_flood_risk_tool
from tools.nasa_power import nasa_power_daily_tool, nasa_power_hourly_tool
from tools.infrastructure import infrastructure_query_tool
from tools.tools_info import tools_info_tool

__all__ = [
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
    "streamflow_forecast_tool",
    "drought_flood_risk_tool",
    "nasa_power_hourly_tool",
    "nasa_power_daily_tool",
    "infrastructure_query_tool",
    "tools_info_tool",
    "flood_depth_damage_tool",
]

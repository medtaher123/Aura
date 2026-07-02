"""
Tools Information Tool for MCP Server

Provides information about available tools, their capabilities, data sources, and example use cases.
This tool helps users understand what tools are available and how to use them.
"""

from mcp_singleton import mcp
from utils.contracts import ToolResponse
from core.logger import get_logger

logger = get_logger(__name__)

# Tools catalog with detailed information
TOOLS_CATALOG = {
    "detect_fire_tool": {
        "name": "Fire Detection Tool",
        "purpose": "Detect and analyze fire events using archived and live NASA FIRMS data",
        "data_sources": [
            "NASA FIRMS API (https://firms.modaps.eosdis.nasa.gov) for recent fire data (last 7 days)",
            "S3 buckets for archived CSV files of fire events"
        ],
        "capabilities": [
            "Detect fires in a specific location within a given date range",
            "Search within a radius (in kilometers) around a location",
            "Analyze fire intensity and patterns",
            "Generate fire maps and visualizations"
        ],
        "example_questions": [
            "Are there fires in Potsdam in summer 2025?",
            "Show me fires in Berlin 2024 within 200km",
            "How many fires were there in Fos-sur-Mer in 2024?"
        ],
        "parameters": {
            "start_date": "Start date for fire search (YYYY-MM-DD)",
            "end_date": "End date for fire search (YYYY-MM-DD)",
            "location": "City or location name",
            "radius_km": "Optional search radius in kilometers"
        }
    },
    "query_disaster_events_tool": {
        "name": "Disaster Events Detection Tool",
        "purpose": "Search for natural and technological disasters in a country for a given date range",
        "data_sources": [
            "GDACS EMDAT API (https://www.gdacs.org/gdacsapi/api/Emdat) for disaster event data",
            "Nominatim for geocoding locations"
        ],
        "capabilities": [
            "Query disasters by type: flood, storm, earthquake, extreme temperature, drought, industrial accident, transport",
            "Filter by country and date range",
            "Get detailed disaster information (deaths, affected population, etc.)"
        ],
        "example_questions": [
            "Show me storm events in Germany between 2010 and 2025",
            "Are there any extreme temperatures or storms in Tunis last summer?",
            "What disasters happened in Japan in 2024?"
        ],
        "parameters": {
            "start_date": "Start date (YYYY-MM-DD)",
            "end_date": "End date (YYYY-MM-DD)",
            "country_name": "Country name",
            "location": "Optional specific location",
            "disaster_type": "List of disaster types (e.g., ['storm', 'drought'])"
        }
    },
    "weather_tool": {
        "name": "Weather Tool",
        "purpose": "Retrieve current weather and forecasts for a city using Open-Meteo API",
        "data_sources": [
            "Open-Meteo API (https://open-meteo.com/) for weather data",
            "Nominatim for geocoding"
        ],
        "capabilities": [
            "Get current weather conditions",
            "Multi-day weather forecasts (up to several days)",
            "Temperature, wind speed, precipitation information",
            "Support for both city names and coordinates"
        ],
        "example_questions": [
            "What is the weather forecast for New York now?",
            "Meteo Dresden hier?",
            "What's the weather at 48.8566, 2.3522?"
        ],
        "parameters": {
            "city_name": "Name of the city (optional if lat/lon provided)",
            "forecast_days": "Number of days to show forecasts for (default 5)",
            "lat": "Optional latitude",
            "lon": "Optional longitude"
        }
    },
    "query_stac_catalog": {
        "name": "STAC Catalog Query Tool",
        "purpose": "Query the STAC EarthSearch catalog for satellite images",
        "data_sources": [
            "STAC EarthSearch API (https://earth-search.aws.element84.com/v1)",
            "Satellite imagery: Sentinel-1, Sentinel-2, MODIS, VIIRS, etc."
        ],
        "capabilities": [
            "Search satellite imagery by location and date range",
            "Filter by cloud cover",
            "Get image thumbnails and metadata",
            "Support multiple satellite collections"
        ],
        "example_questions": [
            "Show me Sentinel-2 images of Casablanca in September 2025",
            "Get satellite images near Berlin in 2024"
        ],
        "parameters": {
            "city": "City name",
            "start_date": "Start date (YYYY-MM-DD)",
            "end_date": "End date (YYYY-MM-DD)",
            "collection": "Satellite collection (e.g., 'sentinel-2-l2a')"
        }
    },
    "geoserver_risk_mask_tool": {
        "name": "GeoServer Risk Mask Tool",
        "purpose": "Query a GeoServer instance for risk/geospatial layers",
        "data_sources": [
            "GeoServer (URL and layer configurable via config)",
            "Geospatial risk data for various hazard types"
        ],
        "capabilities": [
            "Retrieve risk masks for floods, fires, landslides, etc.",
            "Generate risk visualizations and maps",
            "Filter by risk type and location"
        ],
        "example_questions": [
            "Show me the flood mask in geoserver for Casablanca",
            "What is the landslide risk in this area?"
        ],
        "parameters": {
            "risk_type": "Type of risk (e.g., 'flood', 'fire', 'landslide')",
            "location": "Location name",
            "render_mode": "Rendering mode (default: 'auto')"
        }
    },
    "get_route_info": {
        "name": "Itinerary/Route Tool",
        "purpose": "Geocode places and compute driving routes between locations",
        "data_sources": [
            "Nominatim (https://nominatim.openstreetmap.org/) for geocoding",
            "OSRM Project Routing API (http://router.project-osrm.org/) for route computation"
        ],
        "capabilities": [
            "Calculate driving routes between two locations",
            "Get step-by-step directions",
            "Generate route maps",
            "Calculate distance and estimated time"
        ],
        "example_questions": [
            "Compute an itinerary from Paris to Lyon",
            "What's the route from Berlin to Munich?"
        ],
        "parameters": {
            "source": "Starting location",
            "destination": "Destination location"
        }
    },
    "estimate_surface_water_ingress_tool": {
        "name": "Surface Water Ingress Tool",
        "purpose": "Analyze surface water ingress (flooding) using elevation and raster data",
        "data_sources": [
            "OpenTopography GlobalDEM API for SRTMGL3 elevation data",
            "S3/local raster files for DEM analysis",
            "Nominatim for geocoding"
        ],
        "capabilities": [
            "Identify water accumulation points",
            "Analyze flood risk based on elevation",
            "Generate risk maps and mitigation recommendations"
        ],
        "example_questions": [
            "What are the main water accumulation points in Paris?",
            "Estimate surface water ingress risk in Versailles"
        ],
        "parameters": {
            "location_input": "Location name or coordinates"
        }
    },
    "streamflow_forecast_tool": {
        "name": "Streamflow/River Discharge Forecast Tool",
        "purpose": "Provide river discharge forecasts and flood risk analysis using GEOGLOWS ECMWF",
        "data_sources": [
            "GEOGLOWS ECMWF global streamflow forecasting system",
            "S3 buckets: geoglows-v2 (retrospective), geoglows-v2-forecasts (ensemble forecasts)",
            "ArcGIS REST API for river reach identification"
        ],
        "capabilities": [
            "15-day streamflow forecasts",
            "Flood threshold analysis and return periods",
            "River reach identification",
            "Discharge graphs and maps"
        ],
        "example_questions": [
            "Show me streamflow forecast for the Seine River near Paris",
            "What's the flood risk for the Nile?",
            "Get river discharge forecast for river_id 760021611"
        ],
        "parameters": {
            "river_name": "River name with optional location",
            "reach_id": "Optional GEOGLOWS river reach ID (COMID)"
        }
    },
    "drought_flood_risk_tool": {
        "name": "Drought and Flood Risk Analysis Tool",
        "purpose": "Analyze drought and flood risk using global hazard maps",
        "data_sources": [
            "Global Drought and Flood Catalogue (GDFC) Hazard Maps",
            "AWS OpenData S3 bucket: global-drought-flood-catalogue",
            "NetCDF files with long-term (1950-2016) hazard data"
        ],
        "capabilities": [
            "Drought frequency analysis",
            "Pluvial flood frequency analysis",
            "Historical hazard patterns",
            "Return period calculations"
        ],
        "example_questions": [
            "What's the drought risk in this area?",
            "Analyze flood risk for this location"
        ],
        "parameters": {
            "location": "Location to analyze",
            "hazard_type": "Type of hazard ('drought' or 'flood')"
        }
    },
    "nasa_power_daily_tool": {
        "name": "NASA POWER Daily Data Tool",
        "purpose": "Query NASA POWER API for daily climate/energy data at a point",
        "data_sources": [
            "NASA POWER API (https://power.larc.nasa.gov/api/temporal/daily/point)",
            "NASA Prediction Of Worldwide Energy Resources database"
        ],
        "capabilities": [
            "Daily time series for climate/energy variables",
            "Solar irradiance, temperature, wind speed, precipitation",
            "Multi-year trends and long-term aggregates",
            "Support for renewable energy (RE) and agricultural (AG) communities"
        ],
        "example_questions": [
            "Show me the temperature trend in Paris from 2020 to 2024",
            "Get daily solar data for Berlin last year"
        ],
        "parameters": {
            "location": "Location name or coordinates",
            "start_date": "Start date (YYYY-MM-DD)",
            "end_date": "End date (YYYY-MM-DD)",
            "parameters": "List of NASA POWER parameters (e.g., ['T2M', 'PRECTOTCORR'])",
            "community": "Data community ('re' or 'ag')",
            "units": "Unit system (default: 'metric')",
            "time_standard": "Time standard (default: 'utc')"
        }
    },
    "nasa_power_hourly_tool": {
        "name": "NASA POWER Hourly Data Tool",
        "purpose": "Query NASA POWER API for hourly climate/energy data at a point",
        "data_sources": [
            "NASA POWER API (https://power.larc.nasa.gov/api/temporal/hourly/point)",
            "NASA Prediction Of Worldwide Energy Resources database"
        ],
        "capabilities": [
            "Hourly time series for climate/energy variables",
            "Hourly profiles and peak time analysis",
            "Within-day extremes and diurnal patterns",
            "Solar irradiance, wind speed, temperature by hour"
        ],
        "example_questions": [
            "Hourly solar irradiance last week in Tunis?",
            "Show me hourly wind data for yesterday in Berlin"
        ],
        "parameters": {
            "location": "Location name or coordinates",
            "start_date": "Start date (YYYY-MM-DD)",
            "end_date": "End date (YYYY-MM-DD)",
            "parameters": "List of NASA POWER parameters (e.g., ['ALLSKY_SFC_SW_DWN'])",
            "community": "Data community ('re' or 'ag')",
            "units": "Unit system (default: 'metric')",
            "time_standard": "Time standard (default: 'utc')"
        }
    },
    "infrastructure_query_tool": {
        "name": "Infrastructure Query Tool",
        "purpose": "Query OpenStreetMap (OSM) infrastructure near a location using AWS Athena and display results on a map",
        "data_sources": [
            "AWS Athena with OSM tables",
            "S3 bucket for Athena query results",
            "OpenStreetMap infrastructure data"
        ],
        "capabilities": [
            "Query infrastructure by type (amenity, building, landuse)",
            "Count and categorize infrastructure features within a radius",
            "Return a zoomed map and plot matching infrastructure points",
            "Support location name or lat/lon coordinates"
        ],
        "example_questions": [
            "What infrastructure is near Paris?",
            "How many hospitals are near Paris within 250 km?",
            "Show me schools near Berlin within 20 km"
        ],
        "parameters": {
            "location": "Location to query",
            "lat": "Optional latitude (if not using location name)",
            "lon": "Optional longitude (if not using location name)",
            "radius_km": "Search radius in kilometers (default: 50)",
            "infrastructure_types": "Types of infrastructure to query (e.g., ['hospital', 'school'])"
        }
    },
    "bdtopo_query_tool": {
        "name": "BDTOPO PostGIS Query Tool",
        "purpose": "Run low-latency spatial queries against curated/raw BDTOPO layers with structured summaries and map artifacts",
        "data_sources": [
            "IGN BDTOPO full-France GeoPackage downloads (file-based, no API)",
            "PostGIS curated views built from BDTOPO ingestion pipeline",
            "Raw BDTOPO tables for capability-specific enrichment and fallbacks"
        ],
        "capabilities": [
            "Administrative lookup at a coordinate (name, INSEE, population, postal code when available)",
            "Nearest transport feature search with mobility attributes (nature, lanes, speed, restrictions)",
            "Regulated-zone and zoning proximity checks with fallback when curated view is empty",
            "Named-place proximity search enriched with toponym nature/importance",
            "Returns renderable map artifact specs and direct map URLs (OSM + IGN)"
        ],
        "example_questions": [
            "At 48.8566, 2.3522, what commune is this point in and what is its INSEE code?",
            "Find nearest transport segments within 3000m and summarize by transport nature.",
            "Are there regulated zones near this location? If none in curated view, use zoning fallback.",
            "List named places within 2km and include their nature and importance."
        ],
        "parameters": {
            "query_type": "admin_lookup | nearest_transport | regulated_zones | named_places",
            "lat": "Latitude in decimal degrees",
            "lon": "Longitude in decimal degrees",
            "radius_m": "Radius in meters for proximity queries",
            "limit": "Max rows to return (1-50)"
        }
    },
    "bdtopo_intersection_tool": {
        "name": "BDTOPO Intersection Tool",
        "purpose": "Check intersections between roads and regulated/zoning features from BDTOPO raw layers",
        "data_sources": [
            "PostGIS raw BDTOPO transport layer (troncon_de_route)",
            "PostGIS raw BDTOPO regulated/zoning layers (parc_ou_reserve, zone_d_activite_ou_d_interet)"
        ],
        "capabilities": [
            "Point-radius based road/regulation intersection checks",
            "Road-name based intersection checks with optional administrative hint",
            "Distance and type summaries for intersections",
            "Renderable map artifacts and map URLs"
        ],
        "example_questions": [
            "Do roads near this point intersect regulated areas?",
            "For road name 'Avenue des Champs-Elysees', what regulated zones are intersected?"
        ],
        "parameters": {
            "input_mode": "point | road_name",
            "lat": "Latitude (for point mode)",
            "lon": "Longitude (for point mode)",
            "radius_m": "Search radius in meters (point mode)",
            "road_name": "Road name pattern (road_name mode)",
            "admin_hint": "Optional city/admin hint to disambiguate road names",
            "limit": "Max rows to return (1-100)"
        }
    },
    "bdtopo_coverage_quality_tool": {
        "name": "BDTOPO Coverage Quality Tool",
        "purpose": "Evaluate BDTOPO thematic coverage and naming completeness on an area",
        "data_sources": [
            "PostGIS raw BDTOPO thematic tables",
            "Nominatim geocoding for place-name extents"
        ],
        "capabilities": [
            "Coverage diagnostics for point radius, place name, or bbox",
            "Per-indicator feature counts and named-ratio metrics",
            "Sparse-theme detection for data-quality triage"
        ],
        "example_questions": [
            "How complete is BDTOPO coverage around this point?",
            "Run a coverage quality check for Paris."
        ],
        "parameters": {
            "input_mode": "point | place_name | bbox",
            "lat": "Latitude (point mode)",
            "lon": "Longitude (point mode)",
            "radius_m": "Search radius in meters (point mode)",
            "place_name": "Location name to geocode (place_name mode)",
            "bbox": "Bounding box [min_lon,min_lat,max_lon,max_lat] (bbox mode)"
        }
    },
    "bdtopo_change_snapshot_tool": {
        "name": "BDTOPO Change Snapshot Tool",
        "purpose": "Compare BDTOPO feature coverage between two editions on a spatial extent",
        "data_sources": [
            "PostGIS raw BDTOPO tables with edition_date lineage",
            "bdtopo_meta.ingestion_log for edition availability"
        ],
        "capabilities": [
            "Cross-edition count deltas by key thematic tables",
            "Validation of available editions before comparison",
            "Area-based change summaries for screening and monitoring"
        ],
        "example_questions": [
            "What changed between 2025-12-15 and 2026-03-15 in this area?",
            "Compare transport and regulated feature counts across editions."
        ],
        "parameters": {
            "baseline_edition": "Baseline edition date (YYYY-MM-DD)",
            "target_edition": "Target edition date (YYYY-MM-DD)",
            "input_mode": "point | place_name | bbox",
            "lat": "Latitude (point mode)",
            "lon": "Longitude (point mode)",
            "radius_m": "Search radius in meters (point mode)",
            "place_name": "Location name to geocode (place_name mode)",
            "bbox": "Bounding box [min_lon,min_lat,max_lon,max_lat] (bbox mode)"
        }
    },
    "bdtopo_thematic_explain_tool": {
        "name": "BDTOPO Thematic Explain Tool",
        "purpose": "Generate evidence-based thematic explanations (screening, mobility, compliance) from BDTOPO signals",
        "data_sources": [
            "PostGIS raw BDTOPO administrative, transport, regulated, place, and hydro layers",
            "Nominatim geocoding for place-name extents"
        ],
        "capabilities": [
            "Objective-driven explanation profiles",
            "Structured evidence list with source references",
            "Compact scoring/signal summaries with artifact outputs"
        ],
        "example_questions": [
            "Explain this location for site screening using BDTOPO.",
            "Give me a compliance-focused explanation around these coordinates."
        ],
        "parameters": {
            "objective": "site_screening | mobility_risk | compliance | general",
            "input_mode": "point | place_name | bbox",
            "lat": "Latitude (point mode)",
            "lon": "Longitude (point mode)",
            "radius_m": "Search radius in meters (point mode)",
            "place_name": "Location name to geocode (place_name mode)",
            "bbox": "Bounding box [min_lon,min_lat,max_lon,max_lat] (bbox mode)"
        }
    },
    "geo_info_tool": {
        "name": "Geographic Information Tool",
        "purpose": "Retrieve information about countries and cities",
        "data_sources": [
            "restcountries.com for country information",
            "Nominatim for city information",
            "Wikidata for city population and metadata"
        ],
        "capabilities": [
            "Get country details (capital, population, area, region, languages, currency)",
            "Get city information (population, coordinates, country)",
            "Geographic metadata and facts"
        ],
        "example_questions": [
            "Tell me about France",
            "What is the population of Berlin?"
        ],
        "parameters": {
            "query_type": "Type of query ('country' or 'city')",
            "name": "Name of country or city"
        }
    },
    "get_time": {
        "name": "Current Time Tool",
        "purpose": "Get the current time in human-readable format",
        "data_sources": ["System clock"],
        "capabilities": ["Return current time"],
        "example_questions": ["What time is it?", "What's the current time?"],
        "parameters": {}
    },
    "get_date": {
        "name": "Current Date Tool",
        "purpose": "Get the current date in human-readable format",
        "data_sources": ["System clock"],
        "capabilities": ["Return today's date"],
        "example_questions": ["What's today's date?", "What is the date today?"],
        "parameters": {}
    },
    "calculator": {
        "name": "Calculator Tool",
        "purpose": "Evaluate simple arithmetic expressions",
        "data_sources": ["Python eval"],
        "capabilities": ["Basic arithmetic operations (+, -, *, /, %)"],
        "example_questions": ["Calculate 23 * 7", "What is 100 / 5?"],
        "parameters": {
            "expression": "Arithmetic expression to evaluate"
        }
    },
    "flood_depth_damage_tool": {
        "name": "Flood Depth-Damage Tool",
        "purpose": "Estimate flood damage using global depth-damage curves and max damage tables",
        "data_sources": [
            "Global flood depth-damage functions dataset (JRC, 2017)",
            "Country-level max damage values by asset class"
        ],
        "capabilities": [
            "Estimate flood damage for a given depth and asset class",
            "Support for residential, commercial, industrial, agriculture, infrastructure, and transport",
            "Continent-specific damage curves",
            "Year-adjusted damage values using global multipliers (2010-2030)"
        ],
        "example_questions": [
            "Estimate flood damage for 2m depth in Germany for residential buildings",
            "What is the flood damage for commercial buildings in France at 1.5m?"
        ],
        "parameters": {
            "country": "Country name or ISO code",
            "depth_m": "Flood depth in meters (0-6)",
            "asset_class": "Asset class (residential, commercial, industrial, agriculture, infrastructure, transport)",
            "continent": "Optional continent for curve selection",
            "basis": "Optional basis for max damage (building, structure, content, land_use, object)",
            "year": "Year for global multiplier (default: current year)"
        }
    }
}

# Tool categories for better organization
TOOL_CATEGORIES = {
    "Fire & Disasters": ["detect_fire_tool", "query_disaster_events_tool"],
    "Weather & Climate": ["weather_tool", "nasa_power_daily_tool", "nasa_power_hourly_tool", "drought_flood_risk_tool"],
    "Water & Flooding": ["streamflow_forecast_tool", "estimate_surface_water_ingress_tool", "flood_depth_damage_tool"],
    "Satellite Imagery": ["query_stac_catalog"],
    "Risk Analysis": ["geoserver_risk_mask_tool"],
    "Infrastructure & Geography": [
        "infrastructure_query_tool",
        "bdtopo_query_tool",
        "bdtopo_intersection_tool",
        "bdtopo_coverage_quality_tool",
        "bdtopo_change_snapshot_tool",
        "bdtopo_thematic_explain_tool",
        "geo_info_tool",
        "get_route_info",
    ],
    "Utilities": ["get_time", "get_date", "calculator"]
}


def _is_scoped_tools_query(query: str) -> bool:
    """True when the user asks about tools for a specific topic, not the full catalog."""
    q = f" {(query or '').lower().strip()} "
    scoped_markers = (
        " about ",
        " for ",
        " related to ",
        " involving ",
        " that can ",
        " that help ",
        " to detect ",
        " to help ",
        " can detect ",
        " can help ",
        " with ",
    )
    return any(marker in q for marker in scoped_markers)


def _should_list_all_catalog(*, query: str | None, list_all: bool) -> bool:
    """Return True only for unscoped 'show me everything' tool-discovery requests."""
    if list_all:
        return True
    if not query:
        return False
    if _is_scoped_tools_query(query):
        return False
    q = query.lower().strip()
    catalog_markers = (
        "list all",
        "all tools",
        "available tools",
        "what tools",
        "which tools",
        "tools do you have",
        "what can you do",
        "your capabilities",
        "show me your tools",
        "show me the tools",
    )
    return any(marker in q for marker in catalog_markers)


@mcp.tool()
def tools_info_tool(
    query: str | None = None,
    tool_name: str | None = None,
    category: str | None = None,
    list_all: bool = False
) -> ToolResponse:
    """
    Get information about available tools, their capabilities, data sources, and example use cases.
    
    This tool helps users understand what tools are available and how to use them.
    
    Args:
        query: Natural language question about tools (e.g., "what tools can detect fires?")
        tool_name: Specific tool name to get detailed information about
        category: Tool category to list (e.g., "Weather & Climate", "Fire & Disasters")
        list_all: If True, list all available tools with brief descriptions
    
    Examples:
        - "What tools are available?"
        - "How does the fire detection tool work?"
        - "What data sources does the weather tool use?"
        - "Show me all weather-related tools"
        - "What questions can I ask the disaster events tool?"
    """
    
    try:
        # Case 1: List all tools
        if _should_list_all_catalog(query=query, list_all=list_all):
            output_lines = ["📋 **Available Tools:**\n"]
            
            for category_name, tool_list in TOOL_CATEGORIES.items():
                output_lines.append(f"\n**{category_name}:**")
                for tool_id in tool_list:
                    if tool_id in TOOLS_CATALOG:
                        tool_info = TOOLS_CATALOG[tool_id]
                        output_lines.append(f"  • `{tool_id}`: {tool_info['purpose']}")
            
            output_lines.append("\n\n💡 **Tip:** Ask for details about a specific tool using its name!")
            
            return ToolResponse(
                tool_name="tools_info_tool",
                message="\n".join(output_lines),
                data={
                    "total_tools": len(TOOLS_CATALOG),
                    "categories": list(TOOL_CATEGORIES.keys()),
                    "tools": list(TOOLS_CATALOG.keys())
                },
                error=False
            )
        
        # Case 2: Get info about specific tool
        if tool_name:
            # Normalize tool name (remove _tool suffix if present for matching)
            search_name = tool_name.lower().strip()
            
            # Find matching tool
            matched_tool = None
            for tool_id in TOOLS_CATALOG.keys():
                if search_name in tool_id.lower() or tool_id.lower() in search_name:
                    matched_tool = tool_id
                    break
            
            if not matched_tool:
                return ToolResponse(
                    tool_name="tools_info_tool",
                    message=f"❌ Tool '{tool_name}' not found. Use `list_all=True` to see all available tools.",
                    data={"available_tools": list(TOOLS_CATALOG.keys())},
                    error=True
                )
            
            tool_info = TOOLS_CATALOG[matched_tool]
            
            output_lines = [
                f"🔧 **{tool_info['name']}** (`{matched_tool}`)\n",
                f"**Purpose:** {tool_info['purpose']}\n",
                "**Data Sources:**"
            ]
            for source in tool_info['data_sources']:
                output_lines.append(f"  • {source}")
            
            output_lines.append("\n**Capabilities:**")
            for cap in tool_info['capabilities']:
                output_lines.append(f"  • {cap}")
            
            if tool_info.get('parameters'):
                output_lines.append("\n**Parameters:**")
                for param, desc in tool_info['parameters'].items():
                    output_lines.append(f"  • `{param}`: {desc}")
            
            output_lines.append("\n**Example Questions:**")
            for example in tool_info['example_questions']:
                output_lines.append(f"  • \"{example}\"")
            
            return ToolResponse(
                tool_name="tools_info_tool",
                message="\n".join(output_lines),
                data={
                    "tool_id": matched_tool,
                    "tool_info": tool_info
                },
                error=False
            )
        
        # Case 3: List tools by category
        if category:
            category_normalized = category.strip()
            
            # Find matching category (case-insensitive partial match)
            matched_category = None
            for cat_name in TOOL_CATEGORIES.keys():
                if category_normalized.lower() in cat_name.lower():
                    matched_category = cat_name
                    break
            
            if not matched_category:
                return ToolResponse(
                    tool_name="tools_info_tool",
                    message=f"❌ Category '{category}' not found. Available categories: {', '.join(TOOL_CATEGORIES.keys())}",
                    data={"available_categories": list(TOOL_CATEGORIES.keys())},
                    error=True
                )
            
            output_lines = [f"📂 **{matched_category} Tools:**\n"]
            
            for tool_id in TOOL_CATEGORIES[matched_category]:
                if tool_id in TOOLS_CATALOG:
                    tool_info = TOOLS_CATALOG[tool_id]
                    output_lines.append(f"\n**{tool_info['name']}** (`{tool_id}`)")
                    output_lines.append(f"  {tool_info['purpose']}")
                    output_lines.append(f"  Example: \"{tool_info['example_questions'][0]}\"")
            
            return ToolResponse(
                tool_name="tools_info_tool",
                message="\n".join(output_lines),
                data={
                    "category": matched_category,
                    "tools": TOOL_CATEGORIES[matched_category]
                },
                error=False
            )
        
        # Case 4: Natural language query
        if query:
            query_lower = query.lower()
            
            # Search for relevant tools based on keywords in query
            relevant_tools = []
            
            for tool_id, tool_info in TOOLS_CATALOG.items():
                # Check if query keywords match tool purpose, capabilities, or examples
                search_text = (
                    tool_info['purpose'] + " " +
                    " ".join(tool_info['capabilities']) + " " +
                    " ".join(tool_info['example_questions'])
                ).lower()
                
                # Extract keywords from query (filter out common words)
                common_words = {"what", "how", "can", "does", "the", "a", "an", "is", "are", "for", "to", "in", "on", "at", "about", "tell", "me", "show", "get", "find"}
                query_keywords = [w for w in query_lower.split() if w not in common_words and len(w) > 2]
                
                # Check if any keyword matches
                matches = sum(1 for keyword in query_keywords if keyword in search_text)
                if matches > 0:
                    relevant_tools.append((tool_id, tool_info, matches))
            
            # Sort by relevance
            relevant_tools.sort(key=lambda x: x[2], reverse=True)
            
            if not relevant_tools:
                return ToolResponse(
                    tool_name="tools_info_tool",
                    message=f"❓ No tools found matching '{query}'. Try asking about specific capabilities like 'fire detection', 'weather', 'satellite images', etc.",
                    data={"query": query, "available_categories": list(TOOL_CATEGORIES.keys())},
                    error=False
                )
            
            output_lines = [f"🔍 **Tools matching '{query}':**\n"]
            
            # Show top 5 most relevant tools
            for tool_id, tool_info, score in relevant_tools[:5]:
                output_lines.append(f"\n**{tool_info['name']}** (`{tool_id}`)")
                output_lines.append(f"  {tool_info['purpose']}")
                output_lines.append(f"  Example: \"{tool_info['example_questions'][0]}\"")
            
            if len(relevant_tools) > 5:
                output_lines.append(f"\n\n... and {len(relevant_tools) - 5} more tools. Use `list_all=True` to see all.")
            
            return ToolResponse(
                tool_name="tools_info_tool",
                message="\n".join(output_lines),
                data={
                    "query": query,
                    "relevant_tools": [t[0] for t in relevant_tools],
                    "match_count": len(relevant_tools)
                },
                error=False
            )
        
        # Default: Show help message
        return ToolResponse(
            tool_name="tools_info_tool",
            message=(
                "🤖 **Tools Information Assistant**\n\n"
                "I can help you understand what tools are available and how to use them!\n\n"
                "**How to use:**\n"
                "  • List all tools: Use `list_all=True` or ask 'What tools are available?'\n"
                "  • Get tool details: Use `tool_name='detect_fire_tool'` or ask 'How does the fire detection tool work?'\n"
                "  • Browse by category: Use `category='Weather & Climate'`\n"
                "  • Search by query: Use `query='fire detection'` or ask 'What tools can detect fires?'\n\n"
                "**Available categories:**\n" +
                "\n".join([f"  • {cat}" for cat in TOOL_CATEGORIES.keys()]) +
                "\n\n💡 **Try asking:** 'Show me all weather tools' or 'How does the fire detection tool work?'"
            ),
            data={
                "total_tools": len(TOOLS_CATALOG),
                "categories": list(TOOL_CATEGORIES.keys())
            },
            error=False
        )
    
    except Exception as e:
        logger.error(f"Error in tools_info_tool: {str(e)}")
        return ToolResponse(
            tool_name="tools_info_tool",
            message=f"❌ An error occurred: {str(e)}",
            data={"error_details": str(e)},
            error=True
        )

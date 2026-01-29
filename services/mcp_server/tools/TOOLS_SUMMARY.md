# MCP Server Tools Summary

This document summarizes each tool in the `services/mcp_server/tools/` directory, including their purpose, the data sources/APIs/S3 buckets they use, and what those sources contain.

---

## 0. tools_info.py (NEW)
**Purpose:**
- Provides information about available tools, their capabilities, data sources, and example use cases.
- Helps users discover what tools are available and how to use them.
- Acts as a meta-tool that documents the entire tool ecosystem.

**Data Sources:**
- Internal catalog of all registered tools and their metadata
- No external APIs required

**What It Contains:**
- Tool descriptions, purposes, and capabilities
- Data sources used by each tool
- Example questions for each tool
- Tool parameters and their descriptions
- Tool categorization (Fire & Disasters, Weather & Climate, etc.)

**Example Questions:**
- "What tools are available?"
- "How does the fire detection tool work?"
- "What data sources does the weather tool use?"
- "Show me all weather-related tools"
- "What questions can I ask the disaster events tool?"

---

## 1. disaster_detection.py
**Purpose:**
- Search for natural & technological disasters (flood, storm, earthquake, extreme temperature, drought, industrial accident, transport) in a country and for a given date or date range.

**Data Sources:**
- [GDACS EMDAT API](https://www.gdacs.org/gdacsapi/api/Emdat/getemdatbyiso3?iso3=XXX): Returns disaster event data by country ISO3 code.
- [Nominatim](https://nominatim.openstreetmap.org/): Used for geocoding locations.

**What They Contain:**
- EMDAT: Disaster events with type, location, date, deaths, affected, etc.
- Nominatim: Geocoding for city/country names to coordinates.

---

## 2. fire_detection.py
**Purpose:**
- Detect and analyze fire events using archived and live data.

**Data Sources:**
- NASA FIRMS API (https://firms.modaps.eosdis.nasa.gov/api/area/csv/): For recent fire data (last 7 days).
- S3 buckets (configurable, e.g., `fire_archive_dir`): For archived CSV files of fire events.

**What They Contain:**
- Fire event data (location, time, intensity, etc.) from NASA VIIRS/NOAA20 NRT and archives.

---

## 3. floods_and_droughts.py
**Purpose:**
- Analyze drought and flood risk using global hazard maps.

**Data Sources:**
- Global Drought and Flood Catalogue (GDFC) Hazard Maps (public AWS OpenData S3 bucket):
	- Drought: `s3://global-drought-flood-catalogue/Hazard-Maps/Drought-Frequency/`
	- Flood: `s3://global-drought-flood-catalogue/Hazard-Maps/Pluvial-Frequency/`

**What They Contain:**
- NetCDF files with long-term (1950–2016) hazard frequency and return period data for droughts and pluvial floods.

---

## 4. geographic_info.py
**Purpose:**
- Retrieve information about countries and cities.

**Data Sources:**
- [restcountries.com](https://restcountries.com/): Country info.
- [Nominatim](https://nominatim.openstreetmap.org/): City info.
- [Wikidata](https://www.wikidata.org/): City population and metadata.

**What They Contain:**
- Country: Name, capital, population, area, region, languages, currency, flag.
- City: Name, population, coordinates, country, etc.

---

## 5. infrastructure.py
**Purpose:**
- Query OpenStreetMap (OSM) data for infrastructure near a location using AWS Athena.

**Data Sources:**
- AWS Athena (OSM tables)
- S3 bucket for Athena query results

**What They Contain:**
- OSM infrastructure features (amenity, building, landuse) and their counts/types near a location.

---

## 6. itinerary.py
**Purpose:**
- Geocode places and compute driving routes between locations.

**Data Sources:**
- [Nominatim](https://nominatim.openstreetmap.org/): Geocoding.
- [OSRM Project Routing API](http://router.project-osrm.org/): Driving route computation.

**What They Contain:**
- Geocoded coordinates, driving routes, step-by-step directions.

---

## 7. nasa_power.py
**Purpose:**
- Query NASA POWER API for climate/energy data (solar, wind, temperature, etc.) at a point.

**Data Sources:**
- [NASA POWER API](https://power.larc.nasa.gov/api/temporal/hourly/point) and [https://power.larc.nasa.gov/api/temporal/daily/point](https://power.larc.nasa.gov/api/temporal/daily/point):
	- Official NASA Prediction Of Worldwide Energy Resources (POWER) endpoints.

**What They Contain:**
- Hourly/daily time series for climate/energy variables at a given location (solar irradiance, wind speed, temperature, precipitation, etc.).

---

## 8. risk_geoserver.py
**Purpose:**
- Query a GeoServer instance for risk/geospatial layers.

**Data Sources:**
- GeoServer (URL and layer configurable via config)

**What They Contain:**
- Geospatial risk data (e.g., polygons, attributes) for a region or filtered by risk type, model, etc.

---


## 9. streamflow.py
**Purpose:**
- Provide river discharge forecasts and flood risk analysis using GEOGLOWS ECMWF global streamflow forecasting system.

**Data Sources:**
- GEOGLOWS ECMWF global streamflow forecasting system:
	- S3 buckets: `geoglows-v2` (retrospective return periods), `geoglows-v2-forecasts` (ensemble forecasts)
	- [ArcGIS REST API](https://livefeeds3.arcgis.com/arcgis/rest/services/GEOGLOWS/GlobalWaterModel_Medium/MapServer/0): For river reach identification and geometry.

**What They Contain:**
- Streamflow forecasts, flood thresholds (return periods), river reach metadata, and river geometries.

---

## 10. tools_stac.py
**Purpose:**
- Query the STAC EarthSearch catalog for satellite images.

**Data Sources:**
- [STAC EarthSearch API](https://earth-search.aws.element84.com/v1):
	- Provides access to satellite imagery metadata and thumbnails for Sentinel-1, Sentinel-2, MODIS, VIIRS, etc.

**What They Contain:**
- Satellite imagery metadata, cloud cover, and thumbnails for selected collections and date ranges.

---

## 11. water_ingress.py
**Purpose:**
- Analyze surface water ingress (flooding) using elevation and raster data.

**Data Sources:**
- [OpenTopography GlobalDEM API](https://portal.opentopography.org/API/globaldem): For SRTMGL3 elevation data (API key required)
- S3/local raster files (for DEM and analysis outputs)
- [Nominatim](https://nominatim.openstreetmap.org/): Geocoding

**What They Contain:**
- Elevation rasters (GeoTIFF), water ingress risk analysis, geocoded locations, and mitigation recommendations.

---

## 12. weather.py
**Purpose:**
- Retrieve current weather and forecasts for a city using Open-Meteo API.

**Data Sources:**
- [Open-Meteo API](https://open-meteo.com/)
- [Nominatim](https://nominatim.openstreetmap.org/): Geocoding

**What They Contain:**
- Current weather, multi-day forecasts, geocoded city info.

---


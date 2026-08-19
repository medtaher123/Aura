from __future__ import annotations

from typing import Any, Optional

import requests
from core.logger import get_logger
from config import get_config
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from shapely.geometry import shape

from utils.bbox_service import LocationAmbiguousError, get_city_bbox, reverse_geocode
from utils.map_view_service import view_state_from_bbox

logger = get_logger(__name__)
config = get_config()
# Use centralized config for GeoServer settings
GEOSERVER_BASE_URL = config.geoserver_base_url.rstrip("/")
DEFAULT_LAYER_NAME = config.geoserver_risk_layer

def _bbox_from_point(lat: float, lon: float, span_deg: float = 0.2) -> list[float]:
    half = span_deg / 2
    min_lat = max(-90.0, lat - half)
    max_lat = min(90.0, lat + half)
    min_lon = max(-180.0, lon - half)
    max_lon = min(180.0, lon + half)
    return [min_lon, min_lat, max_lon, max_lat]

def _cql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def _build_cql_filter(filters: dict[str, Any]) -> str:
    clauses: list[str] = []

    risk_type = filters.get("risk_type")
    if isinstance(risk_type, str) and risk_type.strip():
        # Normalize risk_type: "flood" maps to "water" in the database
        normalized_risk = risk_type.strip().lower()
        if normalized_risk == "flood":
            normalized_risk = "water"
        clauses.append(f"risk_type = {_cql_quote(normalized_risk)}")

    # Filter by location_city column
    # Use resolved_location (from OSM token lookup) if available, otherwise use location
    location = filters.get("resolved_location") or filters.get("location")
    if isinstance(location, str) and location.strip():
        loc = location.strip()
        # Skip if still an OSM ID token (shouldn't happen after resolution)
        if not loc.startswith("@osm_id:") and not loc.startswith("@place_id:"):
            # Extract just the city name (first part before comma)
            city_name = loc.split(",")[0].strip()
            if city_name:
                clauses.append(f"strToLowerCase(location_city) LIKE {_cql_quote('%' + city_name.lower() + '%')}")

    region = filters.get("region")
    if isinstance(region, str) and region.strip():
        clauses.append(f"region = {_cql_quote(region.strip())}")

    model_name = filters.get("model_name")
    if isinstance(model_name, str) and model_name.strip():
        clauses.append(f"model_name = {_cql_quote(model_name.strip())}")

    model_version = filters.get("model_version")
    if isinstance(model_version, str) and model_version.strip():
        clauses.append(f"model_version = {_cql_quote(model_version.strip())}")

    min_conf = filters.get("min_confidence")
    if isinstance(min_conf, (int, float)):
        clauses.append(f"confidence >= {float(min_conf)}")

    min_area = filters.get("min_area_m2")
    if isinstance(min_area, (int, float)):
        clauses.append(f"area_m2 >= {float(min_area)}")

    # Filter by observation_date (format in DB: "2024-08-26Z")
    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    if isinstance(start_date, str) and start_date.strip():
        # observation_date format is "YYYY-MM-DDZ", so append Z if not present
        start_val = start_date.strip()[:10]  # Take just YYYY-MM-DD
        clauses.append(f"observation_date >= {_cql_quote(start_val + 'Z')}")
    if isinstance(end_date, str) and end_date.strip():
        end_val = end_date.strip()[:10]  # Take just YYYY-MM-DD
        clauses.append(f"observation_date <= {_cql_quote(end_val + 'Z')}")

    bbox = filters.get("bbox")
    if (
        isinstance(bbox, list)
        and len(bbox) == 4
        and all(isinstance(x, (int, float)) for x in bbox)
    ):
        minx, miny, maxx, maxy = bbox  # minx=min_lon, miny=min_lat, maxx=max_lon, maxy=max_lat
        # GeoServer EPSG:4326 expects lat/lon order: (min_lat, min_lon, max_lat, max_lon)
        clauses.append(f"BBOX(geom, {miny}, {minx}, {maxy}, {maxx})")

    return " AND ".join(clauses)

def _ensure_bbox(filters: dict[str, Any]) -> None:
    if isinstance(filters.get("bbox"), list) and len(filters["bbox"]) == 4:
        return
    lat = filters.get("lat")
    lon = filters.get("lon")
    if lat is not None and lon is not None:
        try:
            filters["bbox"] = _bbox_from_point(float(lat), float(lon))
            return
        except Exception:
            pass
    location = filters.get("location")
    if not isinstance(location, str) or not location.strip():
        return

    bbox_raw, lat, lon, resolved_name = get_city_bbox(location.strip(), require_confirmation=True)
    
    # Store resolved display name for city filtering (works even with OSM ID tokens)
    if resolved_name and resolved_name != location.strip():
        filters["resolved_location"] = resolved_name
        logger.info(f"Resolved location '{location}' to '{resolved_name}'")
    if bbox_raw and len(bbox_raw) == 4:
        try:
            min_lat = float(bbox_raw[0])
            max_lat = float(bbox_raw[1])
            min_lon = float(bbox_raw[2])
            max_lon = float(bbox_raw[3])
            
            # Add padding to expand bbox (0.05 degrees ≈ 5km buffer)
            BBOX_PADDING = 0.05
            min_lat -= BBOX_PADDING
            max_lat += BBOX_PADDING
            min_lon -= BBOX_PADDING
            max_lon += BBOX_PADDING
            
            filters["bbox"] = [min_lon, min_lat, max_lon, max_lat]
        except Exception:
            return

def _wfs_get_features(
    *,
    base_url: str,
    type_name: str,
    cql_filter: str | None,
    limit: int = 500,
    timeout_s: int = 20,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": type_name,
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "count": int(limit),
    }
    if cql_filter:
        params["cql_filter"] = cql_filter

    r = requests.get(f"{base_url}/wfs", params=params, timeout=timeout_s)
    r.raise_for_status()
    return r.json()

def _summarize_features(feature_collection: dict[str, Any]) -> dict[str, Any]:
    features = feature_collection.get("features") or []
    if not isinstance(features, list):
        features = []

    count = len(features)
    total_area = 0.0
    confidences: list[float] = []
    bounds: Optional[list[float]] = None  # [minx, miny, maxx, maxy]

    for f in features:
        props = (f or {}).get("properties") or {}
        area = props.get("area_m2")
        if isinstance(area, (int, float)):
            total_area += float(area)

        conf = props.get("confidence")
        if isinstance(conf, (int, float)):
            confidences.append(float(conf))

        geom = (f or {}).get("geometry")
        if geom:
            try:
                b = shape(geom).bounds  # (minx, miny, maxx, maxy)
                if bounds is None:
                    bounds = [b[0], b[1], b[2], b[3]]
                else:
                    bounds[0] = min(bounds[0], b[0])
                    bounds[1] = min(bounds[1], b[1])
                    bounds[2] = max(bounds[2], b[2])
                    bounds[3] = max(bounds[3], b[3])
            except Exception:
                pass

    avg_conf = (sum(confidences) / len(confidences)) if confidences else None
    return {
        "feature_count": count,
        "total_area_m2": total_area if count else 0.0,
        "avg_confidence": avg_conf,
        "bounds": bounds,
    }

def _view_state_from_bounds(bounds: Optional[list[float]]) -> dict[str, float]:
    if bounds and len(bounds) == 4:
        minx, miny, maxx, maxy = bounds
        coords = ToolCoordinates(lat=(miny + maxy) / 2, lon=(minx + maxx) / 2)
        return view_state_from_bbox(coords, padding=0.12, min_zoom=2.0, max_zoom=10.5)
    return {"latitude": 36.8, "longitude": 10.2, "zoom": 8}

def geoserver_risk_mask_tool(
    layer_name: str | None = None,
    risk_type: str | None = None,
    region: str | None = None,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    bbox: list[float] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    min_confidence: float | None = None,
    min_area_m2: float | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    limit: int = 500,
    render_mode: str = "auto",
) -> ToolResponse:
    """Query GeoServer risk polygons with filters (WFS) and display them as a mask on a map (WMS or GeoJSON).

    Use this tool when the user asks to show/visualize risk masks or polygons from GeoServer, especially when they mention
    filtering by risk type (water, flood), location, date range, confidence, or area.

    Example tool call:
    - geoserver_risk_mask_tool(risk_type="flood", location="Tunis")
    - geoserver_risk_mask_tool(risk_type="flood", lat=36.8065, lon=10.1815)
    """
    try:
        if end_date is None and isinstance(start_date, str) and start_date.strip():
            end_date = start_date

        filters: dict[str, Any] = {
            "layer_name": layer_name or DEFAULT_LAYER_NAME,
            "risk_type": risk_type,
            "region": region,
            "location": location,
            "lat": lat,
            "lon": lon,
            "bbox": bbox,
            "start_date": start_date,
            "end_date": end_date,
            "min_confidence": min_confidence,
            "min_area_m2": min_area_m2,
            "model_name": model_name,
            "model_version": model_version,
            "limit": limit or 500,
            "render_mode": render_mode or "auto",
        }

        if isinstance(filters.get("bbox"), list) and len(filters["bbox"]) == 4:
            try:
                filters["bbox"] = [float(x) for x in filters["bbox"]]
            except Exception:
                filters["bbox"] = None

        try:
            _ensure_bbox(filters)
        except LocationAmbiguousError as e:
            return ToolResponse(
                tool_name="geoserver_risk_mask_tool",
                message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
                city=location,
                data={
                    "needs_location_confirmation": True,
                    "location_query": e.query,
                    "candidates": e.candidates,
                    "resume_patch": {"field": "location"},
                },
                error=False,
            )

        if not filters.get("location") and isinstance(filters.get("lat"), (int, float)) and isinstance(filters.get("lon"), (int, float)):
            try:
                rev = reverse_geocode(float(filters["lat"]), float(filters["lon"]))
                filters["location"] = rev.get("city") or rev.get("country")
            except Exception:
                filters["location"] = f"{float(filters['lat']):.4f}, {float(filters['lon']):.4f}"
        cql = _build_cql_filter(filters)
        layer_name = str(filters["layer_name"])
        limit = int(filters.get("limit") or 500)

        feature_collection = _wfs_get_features(
            base_url=GEOSERVER_BASE_URL,
            type_name=layer_name,
            cql_filter=cql or None,
            limit=limit,
        )
        summary = _summarize_features(feature_collection)
        bounds = summary.get("bounds")

        # Fallback bounds from bbox filter if WFS returns no geometry bounds
        if (
            not bounds
            and isinstance(filters.get("bbox"), list)
            and len(filters["bbox"]) == 4
        ):
            b = filters["bbox"]
            bounds = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]

        map_spec = {
            "title": "GeoServer risk polygons",
            "view_state": _view_state_from_bounds(bounds),
            "tooltip": {
                "text": "Risk: {risk_type}\nRegion: {region}\nConfidence: {confidence}\nArea (m²): {area_m2}",
            },
            "layers": [
                {
                    "type": "GeoJsonLayer",
                    "data": feature_collection,
                    "stroked": True,
                    "filled": True,
                    "get_fill_color": [255, 0, 0, 110],
                    "get_line_color": [255, 0, 0, 200],
                    "line_width_min_pixels": 1,
                    "pickable": True,
                    "auto_highlight": True,
                }
            ],
        }

        return ToolResponse(
            tool_name="geoserver_risk_mask_tool",
            message="GeoServer risk mask generated.",
            artifacts=ToolArtifacts(maps=[map_spec], thumbnails=[], urls=[]),
            start_date=filters.get("start_date"),
            end_date=filters.get("end_date"),
            city=filters.get("location"),
            data={
                "layer": layer_name,
                "cql_filter": cql,
                "filters": filters,
                "feature_count": summary.get("feature_count"),
                "total_area_m2": summary.get("total_area_m2"),
                "avg_confidence": summary.get("avg_confidence"),
                "geoserver": {
                    "base_url": GEOSERVER_BASE_URL,
                    "wms_url": f"{GEOSERVER_BASE_URL}/wms",
                    "wfs_url": f"{GEOSERVER_BASE_URL}/wfs",
                },
            },
            error=False,
        )

    except Exception as e:
        logger.error(f"GeoServer risk mask tool error: {e}", exc_info=True)
        return ToolResponse(
            tool_name="geoserver_risk_mask_tool",
            message=f"GeoServer tool error: {str(e)}",
            error=True,
        )

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import folium
import requests
from langchain.tools import tool
from langchain_ollama import OllamaLLM
from shapely.geometry import shape

from .tools_geocode import get_city_bbox


GEOSERVER_BASE_URL = os.getenv(
    "GEOSERVER_BASE_URL",
    "http://geoserver-alb-556624184.eu-west-3.elb.amazonaws.com/geoserver",
).rstrip("/")

DEFAULT_LAYER_NAME = os.getenv("GEOSERVER_RISK_LAYER", "georisk:predictions")

MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    if isinstance(text, dict):
        return text
    cleaned = re.sub(r"^```[a-zA-Z0-9]*|```$", "", str(text).strip())
    cleaned = cleaned.replace("Null", "null").replace("NULL", "null")
    cleaned = cleaned.replace("True", "true").replace("False", "false")
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def _cql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _build_cql_filter(filters: dict[str, Any]) -> str:
    clauses: list[str] = []

    risk_type = filters.get("risk_type")
    if isinstance(risk_type, str) and risk_type.strip():
        clauses.append(f"risk_type = {_cql_quote(risk_type.strip())}")

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

    start_date = filters.get("start_date")
    end_date = filters.get("end_date")
    if isinstance(start_date, str) and start_date.strip():
        start_iso = start_date.strip()
        if len(start_iso) == 10:
            start_iso = start_iso + "T00:00:00Z"
        clauses.append(f"inference_date >= {_cql_quote(start_iso)}")
    if isinstance(end_date, str) and end_date.strip():
        end_iso = end_date.strip()
        if len(end_iso) == 10:
            end_iso = end_iso + "T23:59:59Z"
        clauses.append(f"inference_date <= {_cql_quote(end_iso)}")

    bbox = filters.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(x, (int, float)) for x in bbox):
        minx, miny, maxx, maxy = bbox
        clauses.append(f"BBOX(geom, {minx}, {miny}, {maxx}, {maxy})")

    return " AND ".join(clauses)


def _ensure_bbox(filters: dict[str, Any]) -> None:
    if isinstance(filters.get("bbox"), list) and len(filters["bbox"]) == 4:
        return
    location = filters.get("location")
    if not isinstance(location, str) or not location.strip():
        return

    bbox_result = get_city_bbox(location.strip())
    if bbox_result and len(bbox_result) == 5:
        min_lon, min_lat, max_lon, max_lat, _ = bbox_result
        if None not in (min_lon, min_lat, max_lon, max_lat):
            filters["bbox"] = [float(min_lon), float(min_lat), float(max_lon), float(max_lat)]


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


def _make_map(
    *,
    base_url: str,
    layer_name: str,
    cql_filter: str | None,
    bounds: Optional[list[float]],
    feature_collection: dict[str, Any],
    render_mode: str = "auto",
) -> str:
    if bounds and len(bounds) == 4:
        minx, miny, maxx, maxy = bounds
        center_lat = (miny + maxy) / 2
        center_lon = (minx + maxx) / 2
        zoom_start = 10
    else:
        center_lat, center_lon, zoom_start = 36.8, 10.2, 8

    fmap = folium.Map(location=[center_lat, center_lon], zoom_start=zoom_start)

    features = feature_collection.get("features") or []
    use_geojson = render_mode == "geojson" or (render_mode == "auto" and isinstance(features, list) and len(features) <= 200)

    if use_geojson and isinstance(features, list) and features:
        def _style(feature: dict[str, Any]):
            props = feature.get("properties") or {}
            conf = props.get("confidence")
            opacity = 0.6
            if isinstance(conf, (int, float)):
                opacity = max(0.2, min(0.9, float(conf)))
            return {"color": "#ff0000", "weight": 2, "fillColor": "#ff0000", "fillOpacity": opacity}

        folium.GeoJson(
            feature_collection,
            name="Risk polygons (WFS)",
            style_function=_style,
            tooltip=folium.GeoJsonTooltip(fields=["risk_type", "region", "confidence", "area_m2"], aliases=["risk_type", "region", "confidence", "area_m2"], sticky=False),
        ).add_to(fmap)
    else:
        extra = {"transparent": True}
        if cql_filter:
            extra["CQL_FILTER"] = cql_filter

        folium.raster_layers.WmsTileLayer(
            url=f"{base_url}/wms",
            layers=layer_name,
            fmt="image/png",
            transparent=True,
            name="Risk mask (WMS)",
            attr="GeoServer",
            **extra,
        ).add_to(fmap)

    if bounds and len(bounds) == 4:
        # Fit to bounds: folium expects [[south, west], [north, east]]
        fmap.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

    folium.LayerControl().add_to(fmap)

    filename = f"RiskMask_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    out_path = MAPS_DIR / filename
    fmap.save(out_path)
    return out_path.name


@tool("geoserver_risk_mask_tool", return_direct=True)
def geoserver_risk_mask_tool(query_text: str) -> dict[str, Any]:
    """Query GeoServer risk polygons with filters (WFS) and display them as a mask on a map (WMS or GeoJSON).

    Use this tool when the user asks to show/visualize risk masks or polygons from GeoServer, especially when they mention
    filtering by risk type, region, confidence, inference date range, or area.

    Example user inputs:
    - "Show flood risk mask in Tunis with confidence > 0.7"
    - "Display fire predictions in Sfax for last week"
    - "Show polygons for region Ariana between 2025-12-01 and 2025-12-10"
    """
    try:
        system_prompt = """
You extract GeoServer filtering parameters from a user request.

Return ONLY valid JSON with these keys:
{
  "layer_name": "string or null",
  "risk_type": "string or null",
  "region": "string or null",
  "location": "string or null",
  "bbox": [min_lon, min_lat, max_lon, max_lat] or null,
  "start_date": "YYYY-MM-DD or ISO timestamp or null",
  "end_date": "YYYY-MM-DD or ISO timestamp or null",
  "min_confidence": number or null,
  "min_area_m2": number or null,
  "model_name": "string or null",
  "model_version": "string or null",
  "limit": number or null,
  "render_mode": "auto" or "wms" or "geojson" or null
}

Rules:
- If bbox is provided in the text, parse it.
- If a city/location is mentioned but no bbox, set "location" and leave bbox null.
- If only one date is mentioned, set both start_date and end_date to it.
- If risk type is mentioned (flood/fire/etc), put it in risk_type.
- Do not add extra keys.
"""

        llm = OllamaLLM(model="mistral", temperature=0.1, system_prompt=system_prompt)
        extracted_raw = llm.invoke(f'User input: "{query_text}"\nJSON:')
        extracted = _parse_llm_json(extracted_raw) or {}

        filters: dict[str, Any] = {
            "layer_name": extracted.get("layer_name") or DEFAULT_LAYER_NAME,
            "risk_type": extracted.get("risk_type"),
            "region": extracted.get("region"),
            "location": extracted.get("location"),
            "bbox": extracted.get("bbox"),
            "start_date": extracted.get("start_date"),
            "end_date": extracted.get("end_date"),
            "min_confidence": extracted.get("min_confidence"),
            "min_area_m2": extracted.get("min_area_m2"),
            "model_name": extracted.get("model_name"),
            "model_version": extracted.get("model_version"),
            "limit": extracted.get("limit") or 500,
            "render_mode": extracted.get("render_mode") or "auto",
        }

        _ensure_bbox(filters)
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
        if not bounds and isinstance(filters.get("bbox"), list) and len(filters["bbox"]) == 4:
            b = filters["bbox"]
            bounds = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]

        map_file = _make_map(
            base_url=GEOSERVER_BASE_URL,
            layer_name=layer_name,
            cql_filter=cql or None,
            bounds=bounds,
            feature_collection=feature_collection,
            render_mode=str(filters.get("render_mode") or "auto").lower(),
        )

        return {
            "message": "GeoServer risk mask generated.",
            "layer": layer_name,
            "cql_filter": cql,
            "feature_count": summary.get("feature_count"),
            "total_area_m2": summary.get("total_area_m2"),
            "avg_confidence": summary.get("avg_confidence"),
            "map_file": map_file,
            "geoserver": {
                "base_url": GEOSERVER_BASE_URL,
                "wms_url": f"{GEOSERVER_BASE_URL}/wms",
                "wfs_url": f"{GEOSERVER_BASE_URL}/wfs",
            },
            "error": False,
        }

    except Exception as e:
        return {
            "error": True,
            "message": f"GeoServer tool error: {str(e)}",
        }

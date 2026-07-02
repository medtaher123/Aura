"""Lightweight Nominatim search for the LangGraph layer (no mcp_server import path issues)."""

from __future__ import annotations

import time
from typing import Any

import requests

USER_AGENT = "eo-llm-graph/0.1 (location gate)"


def _parse_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        south, north, west, east = (float(x) for x in raw_bbox)
    except (TypeError, ValueError):
        return None
    return [min(south, north), max(south, north), min(west, east), max(west, east)]


def _normalize(item: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    display_name = str(item.get("display_name") or fallback_name)
    name = display_name.split(",")[0].strip() or fallback_name
    lat_raw, lon_raw = item.get("lat"), item.get("lon")
    try:
        lat = float(lat_raw) if lat_raw is not None else None
    except (TypeError, ValueError):
        lat = None
    try:
        lon = float(lon_raw) if lon_raw is not None else None
    except (TypeError, ValueError):
        lon = None
    bbox = _parse_bbox(item.get("boundingbox"))
    return {
        "display_name": display_name,
        "name": name,
        "lat": lat,
        "lon": lon,
        "bbox": bbox,
        "class": item.get("class"),
        "type": item.get("type"),
        "addresstype": item.get("addresstype"),
        "place_id": item.get("place_id"),
        "osm_id": item.get("osm_id"),
        "osm_type": item.get("osm_type"),
    }


def search_location_candidates(place_query: str, *, limit: int = 8) -> list[dict[str, Any]]:
    """Return Nominatim candidates with lat/lon (same general shape as MCP get_city_candidates)."""
    q = (place_query or "").strip()
    if not q:
        return []

    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": q, "format": "json", "limit": int(limit)}
    for attempt in range(3):
        try:
            r = requests.get(
                url, params=params, headers={"User-Agent": USER_AGENT}, timeout=12
            )
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list) or not data:
                return []
            out = [_normalize(item, q) for item in data if isinstance(item, dict)]
            return [c for c in out if c.get("lat") is not None and c.get("lon") is not None]
        except (requests.RequestException, ValueError):
            if attempt < 2:
                time.sleep(1)
    return []

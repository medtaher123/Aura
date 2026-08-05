"""Helpers for proactive location attach (Nominatim search)."""

from __future__ import annotations

from typing import Any

import requests

from src.clients.agent_ws_client import get_osm_type_prefix

USER_AGENT = "metaplanet-streamlit/0.1 (composer location attach)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def _parse_bbox(raw_bbox: Any) -> list[float] | None:
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        return None
    try:
        south, north, west, east = (float(x) for x in raw_bbox)
    except (TypeError, ValueError):
        return None
    return [min(south, north), max(south, north), min(west, east), max(west, east)]


def search_location_candidates(
    place_query: str, *, limit: int = 8
) -> list[dict[str, Any]]:
    """Return Nominatim candidates shaped like agent_server geocode results."""
    q = (place_query or "").strip()
    if not q:
        return []

    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": q, "format": "json", "limit": int(limit)},
            headers={"User-Agent": USER_AGENT},
            timeout=12.0,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    if not isinstance(data, list):
        return []

    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        display_name = str(item.get("display_name") or q)
        try:
            lat = float(item["lat"]) if item.get("lat") is not None else None
            lon = float(item["lon"]) if item.get("lon") is not None else None
        except (TypeError, ValueError, KeyError):
            continue
        if lat is None or lon is None:
            continue
        out.append(
            {
                "display_name": display_name,
                "name": display_name.split(",")[0].strip() or q,
                "lat": lat,
                "lon": lon,
                "bbox": _parse_bbox(item.get("boundingbox")),
                "place_id": item.get("place_id"),
                "osm_id": item.get("osm_id"),
                "osm_type": item.get("osm_type"),
                "class": item.get("class"),
                "type": item.get("type"),
                "addresstype": item.get("addresstype"),
            }
        )
    return out


def location_result_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    """Build a LocationResult-shaped dict for chat_request.user_inputs."""
    osm_type = candidate.get("osm_type")
    osm_type_str = str(osm_type) if osm_type is not None else ""
    return {
        "name": str(
            candidate.get("display_name") or candidate.get("name") or "Unknown"
        ),
        "coordinates": [float(candidate["lat"]), float(candidate["lon"])],
        "place_id": candidate.get("place_id"),
        "osm_id": candidate.get("osm_id"),
        "osm_type": osm_type if osm_type in ("relation", "way", "node") else None,
        "osm_type_prefix": get_osm_type_prefix(osm_type_str) or None,
    }

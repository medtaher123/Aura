"""Helpers for the Streamlit bounding-box user input collector."""

from __future__ import annotations

from typing import Any


def geojson_feature_to_bbox(feature: dict[str, Any] | None) -> list[float] | None:
    """Convert a Folium Draw rectangle GeoJSON feature to ``[min_lat, max_lat, min_lon, max_lon]``."""
    if not isinstance(feature, dict):
        return None
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") != "Polygon":
        return None
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return None
    ring = coords[0]
    if not isinstance(ring, list) or len(ring) < 3:
        return None

    lons: list[float] = []
    lats: list[float] = []
    for pt in ring:
        if not isinstance(pt, (list, tuple)) or len(pt) < 2:
            continue
        try:
            lon = float(pt[0])
            lat = float(pt[1])
        except (TypeError, ValueError):
            continue
        lons.append(lon)
        lats.append(lat)
    if not lons or not lats:
        return None
    return [min(lats), max(lats), min(lons), max(lons)]


def bbox_from_folium_draw_output(map_out: dict[str, Any] | None) -> list[float] | None:
    """Pick the latest drawn rectangle from an ``st_folium`` return value."""
    if not isinstance(map_out, dict):
        return None
    bbox = geojson_feature_to_bbox(map_out.get("last_active_drawing"))
    if bbox is not None:
        return bbox
    drawings = map_out.get("all_drawings")
    if not isinstance(drawings, list):
        return None
    for feature in reversed(drawings):
        bbox = geojson_feature_to_bbox(feature)
        if bbox is not None:
            return bbox
    return None


def bounding_box_attachment(bbox: list[float]) -> dict[str, Any]:
    """Build a ``type=bounding_box`` attachment for chat_request / chat_resume."""
    min_lat, max_lat, min_lon, max_lon = (float(x) for x in bbox)
    return {
        "type": "bounding_box",
        "area": {
            "kind": "bounding_box",
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
    }

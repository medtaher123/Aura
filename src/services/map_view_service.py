"""Map view helpers.

This service centralizes logic for deriving a map view_state (lat/lon/zoom)
from either a bounding box or a set of points.

The goal is to avoid hard-coded zoom levels inside tools.

Conventions:
- bbox is expected as [min_lat, max_lat, min_lon, max_lon] (compatible with bbox_service).
"""

from __future__ import annotations

import math
from typing import Any, Iterable


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(x: Any) -> float | None:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def bbox_from_points(points: list[dict[str, Any]]) -> list[float] | None:
    """Compute bbox [min_lat, max_lat, min_lon, max_lon] from point dicts."""
    if not isinstance(points, list) or not points:
        return None

    lats: list[float] = []
    lons: list[float] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        # Support common coordinate key variants.
        lat = _safe_float(p.get("lat"))
        if lat is None:
            lat = _safe_float(p.get("latitude"))

        lon = _safe_float(p.get("lon"))
        if lon is None:
            lon = _safe_float(p.get("longitude"))
        if lat is None or lon is None:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        lats.append(lat)
        lons.append(lon)

    if not lats or not lons:
        return None

    return [min(lats), max(lats), min(lons), max(lons)]


def view_state_from_bbox(
    bbox: list[float],
    *,
    padding: float = 0.15,
    min_zoom: float = 2.0,
    max_zoom: float = 10.5,
) -> dict[str, float]:
    """Derive a map view_state from bbox.

    Uses a simple, renderer-agnostic approximation for zoom based on angular span.

    Args:
        bbox: [min_lat, max_lat, min_lon, max_lon]
        padding: relative padding around bbox (0.15 = +15% span)
        min_zoom/max_zoom: clamp range

    Returns:
        {"latitude": center_lat, "longitude": center_lon, "zoom": zoom}
    """
    if not isinstance(bbox, list) or len(bbox) != 4:
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}

    try:
        min_lat, max_lat, min_lon, max_lon = (float(x) for x in bbox)
    except Exception:
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}

    min_lat, max_lat = (min(min_lat, max_lat), max(min_lat, max_lat))
    min_lon, max_lon = (min(min_lon, max_lon), max(min_lon, max_lon))

    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0

    lat_span = max(0.0, max_lat - min_lat)
    lon_span = max(0.0, max_lon - min_lon)

    # Apply padding.
    pad = 1.0 + max(0.0, float(padding))
    lat_span *= pad
    lon_span *= pad

    # Avoid division by zero; treat single-point bbox as a close zoom.
    span = max(lat_span, lon_span, 1e-6)

    # Approximate: at zoom=0 the world is ~360 degrees wide.
    raw_zoom = math.log2(360.0 / span)
    print('I am in view_state_from_bbox, and raw_zoom is:', raw_zoom)

    zoom = _clamp(raw_zoom, float(min_zoom), float(max_zoom))
    print('I am in view_state_from_bbox, and zoom is:', zoom)
    return {"latitude": float(center_lat), "longitude": float(center_lon), "zoom": float(zoom)}


def view_state_from_points(
    points: list[dict[str, Any]],
    *,
    padding: float = 0.15,
    min_zoom: float = 2.0,
    max_zoom: float = 10.5,
) -> dict[str, float]:
    """Derive view_state from points by computing bbox first."""
    bbox = bbox_from_points(points)
    if bbox is None:
        print('I am in view_state_from_points and bbox is None, and zoom is:', min_zoom)
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}
    
    print('I am in view_state_from_points and bbox is:', bbox)
    return view_state_from_bbox(bbox, padding=padding, min_zoom=min_zoom, max_zoom=max_zoom)

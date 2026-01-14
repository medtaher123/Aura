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

    return {'lat': sum(lats) / len(lats), 'lon': sum(lons) / len(lons)}  # center point


import math

def view_state_from_bbox(
    coords: dict[str, float],
    *,
    padding: float = 0.15,
    min_zoom: float = 5.0,
    max_zoom: float = 10.5,
    radius: float | None = None,
) -> dict[str, float]:
    """Derive a map view_state from bbox.
    """
    # Use coords instead of bbox
    print('radius is:', radius)
    if not isinstance(coords, dict):
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}

    try:
        center_lat = float(coords["lat"])
        center_lon = float(coords["lon"])
    except Exception:
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}

    # --- create a virtual bbox around the point ---
    # controls how "wide" the initial view is (city-level)
    base_span = radius/100 if radius is not None else 1.5  # degrees (~20km), adjust if needed

    min_lat = center_lat - base_span / 2
    max_lat = center_lat + base_span / 2
    min_lon = center_lon - base_span / 2
    max_lon = center_lon + base_span / 2

    lat_span = max_lat - min_lat
    lon_span = max_lon - min_lon

    # Apply padding
    pad = 1.0 + max(0.0, padding)
    lat_span *= pad
    lon_span *= pad

    # Prevent zero-span
    lat_span = max(lat_span, 1e-6)
    lon_span = max(lon_span, 1e-6)

    lat_rad = math.radians(center_lat)
    lon_span_corrected = lon_span * math.cos(lat_rad)

    # World extents
    zoom_lat = math.log2(180.0 / lat_span)
    zoom_lon = math.log2(360.0 / lon_span_corrected)

    raw_zoom = min(zoom_lat, zoom_lon)
    print('I am in view_state_from_bbox and raw_zoom is:', raw_zoom)
    zoom = max(min(raw_zoom, max_zoom), min_zoom)
    print('I am in view_state_from_bbox and calculated zoom is:', zoom)
    return {
        "latitude": center_lat,
        "longitude": center_lon,
        "zoom": float(zoom),
    }



def view_state_from_points(
    points: list[dict[str, Any]],
    *,
    padding: float = 0.15,
    min_zoom: float = 5.0,
    max_zoom: float = 10.5,
    radius: float | None = None,
) -> dict[str, float]:
    """Derive view_state from points by computing bbox first."""
    coords = bbox_from_points(points)
    if coords is None:
        print('I am in view_state_from_points and bbox is None, and zoom is:', min_zoom)
        return {"latitude": 0.0, "longitude": 0.0, "zoom": float(min_zoom)}
    
    print('I am in view_state_from_points and coords is:', coords)
    return view_state_from_bbox(coords, padding=padding, min_zoom=min_zoom, max_zoom=max_zoom,radius=radius)

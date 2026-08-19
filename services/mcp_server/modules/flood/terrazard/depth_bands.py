"""Hazard depth polygons and exclusive depth-band metadata for TerraZard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from modules.flood.terrazard.utils import execute_read_query

# Open-ended cap for the deepest nested depth threshold (metres).
_OPEN_ENDED_DEPTH_MAX_M = 100.0

@dataclass(frozen=True)
class HazardDepthPolygon:
    """Raw nested TerraZard flood polygon (minimum depth threshold)."""

    depth_min_m: float
    geojson: dict[str, Any]

@dataclass(frozen=True)
class DepthBand:
    """Exclusive depth interval used in damage aggregation.

    Geometries are no longer materialised as difference rings; flooded area is
    filled from the TerraZard depth raster.
    """

    depth_min_m: float
    depth_max_m: float
    representative_depth_m: float
    flooded_area_m2: float = 0.0

_HAZARD_POLYGONS_QUERY = """
WITH envelope AS (
    SELECT ST_Transform(
        ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
        COALESCE(
            (SELECT ST_SRID(geometry)
             FROM hazard_masks
             WHERE observation_date = :observation_date
               AND model_id = :model_id
               AND class = 1
             LIMIT 1),
            4326
        )
    ) AS geom
)
SELECT
    h.depth_min,
    ST_AsGeoJSON(ST_MakeValid(ST_Transform(h.geometry, 4326))) AS geojson
FROM hazard_masks h, envelope e
WHERE h.observation_date = :observation_date
  AND h.model_id = :model_id
  AND h.class = 1
  AND COALESCE(h.is_permanent, false) = false
  AND h.depth_min IS NOT NULL
  AND ST_Intersects(h.geometry, e.geom);
"""

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _parse_geojson(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None

def build_depth_band_defs(depth_mins: list[float]) -> list[DepthBand]:
    """Build exclusive depth-band definitions from nested minimum-depth levels.

    TerraZard polygons nest by ``depth_min`` (deeper thresholds sit inside
    shallower ones). Exclusive bands are consecutive intervals between sorted
    unique thresholds; flooded areas are filled later by the depth raster.
    """
    unique = sorted({round(float(value), 6) for value in depth_mins})
    if not unique:
        return []

    bands: list[DepthBand] = []
    for index, depth_min in enumerate(unique):
        depth_max = (
            unique[index + 1] if index + 1 < len(unique) else _OPEN_ENDED_DEPTH_MAX_M
        )
        representative = min(max((depth_min + depth_max) / 2.0, depth_min), 6.0)
        bands.append(
            DepthBand(
                depth_min_m=depth_min,
                depth_max_m=depth_max,
                representative_depth_m=representative,
                flooded_area_m2=0.0,
            )
        )
    return bands

def fetch_hazard_depth_polygons(
    *,
    observation_date: str,
    model_id: str,
    bbox: list[float],
) -> list[HazardDepthPolygon]:
    """Fetch nested hazard polygons as GeoJSON (EPSG:4326) inside the AOI.

    Lightweight spatial filter only — no ``ST_Difference``. Exclusive depth
    bands are derived later via raster map algebra (pixel-wise maximum nested
    ``depth_min``).
    """
    params = {
        "observation_date": observation_date,
        "model_id": model_id,
        "min_lat": float(bbox[0]),
        "max_lat": float(bbox[1]),
        "min_lon": float(bbox[2]),
        "max_lon": float(bbox[3]),
    }
    rows = execute_read_query(_HAZARD_POLYGONS_QUERY, params)
    polygons: list[HazardDepthPolygon] = []
    for row in rows:
        depth_min = _safe_float(row.get("depth_min"))
        geometry = _parse_geojson(row.get("geojson"))
        if depth_min is None or geometry is None:
            continue
        polygons.append(HazardDepthPolygon(depth_min_m=depth_min, geojson=geometry))
    return polygons

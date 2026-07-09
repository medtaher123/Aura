"""PostGIS repository for TerraZard hazard_masks queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tools.terrazard.utils import execute_read_query


@dataclass(frozen=True)
class MapStats:
    total_polygons: int
    water_count: int
    cloud_count: int
    avg_lat: float | None
    avg_lon: float | None


def _bbox_params(bbox: list[float]) -> dict[str, float]:
    return {
        "min_lat": float(bbox[0]),
        "max_lat": float(bbox[1]),
        "min_lon": float(bbox[2]),
        "max_lon": float(bbox[3]),
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


class HazardMaskRepository:
    """Read-only access to hazard_masks metadata."""

    _DATE_COUNTS_QUERY = """
        SELECT observation_date, COUNT(*) AS polygon_count
        FROM hazard_masks
        WHERE observation_date >= :start_date
          AND observation_date <= :end_date
          AND ST_Intersects(
              geometry,
              ST_Transform(
                  ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
                  ST_SRID(geometry)
              )
          )
        GROUP BY observation_date
        ORDER BY observation_date ASC;
    """

    _MAP_STATS_QUERY = """
        SELECT
            COUNT(*) AS total_polygons,
            SUM(CASE WHEN class = 1 THEN 1 ELSE 0 END) AS water_count,
            SUM(CASE WHEN class = -1 THEN 1 ELSE 0 END) AS cloud_count,
            AVG(ST_Y(ST_Centroid(geometry))) AS avg_lat,
            AVG(ST_X(ST_Centroid(geometry))) AS avg_lon
        FROM hazard_masks
        WHERE observation_date = :observation_date
          AND model_id = :model_id
          AND COALESCE(is_permanent, false) = false
          AND ST_Intersects(
              geometry,
              ST_Transform(
                  ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
                  ST_SRID(geometry)
              )
          );
    """

    def get_date_counts(
        self, bbox: list[float], start_date: str, end_date: str
    ) -> list[dict[str, Any]]:
        params = {
            "start_date": start_date,
            "end_date": end_date,
            **_bbox_params(bbox),
        }
        rows = execute_read_query(self._DATE_COUNTS_QUERY, params)
        return [
            {
                "date": row["observation_date"],
                "polygon_count": _safe_int(row.get("polygon_count")),
                "status": (
                    "Data available"
                    if _safe_int(row.get("polygon_count")) > 0
                    else "No data"
                ),
            }
            for row in rows
        ]

    def get_map_stats(
        self, observation_date: str, model_id: str, bbox: list[float]
    ) -> MapStats:
        params = {
            "observation_date": observation_date,
            "model_id": model_id,
            **_bbox_params(bbox),
        }
        rows = execute_read_query(self._MAP_STATS_QUERY, params)
        if not rows:
            return MapStats(0, 0, 0, None, None)

        row = rows[0]
        return MapStats(
            total_polygons=_safe_int(row.get("total_polygons")),
            water_count=_safe_int(row.get("water_count")),
            cloud_count=_safe_int(row.get("cloud_count")),
            avg_lat=_safe_float(row.get("avg_lat")),
            avg_lon=_safe_float(row.get("avg_lon")),
        )

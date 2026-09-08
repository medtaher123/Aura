"""PostGIS repository for TerraZard hazard_masks queries."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from modules.flood.terrazard.utils import execute_read_query

@dataclass(frozen=True)
class MapStats:
    total_polygons: int
    water_count: int
    cloud_count: int
    avg_lat: float | None
    avg_lon: float | None

@dataclass(frozen=True)
class WaterDateCount:
    date: str
    water_count: int
    cloud_count: int

@dataclass(frozen=True)
class DepthProfile:
    min_depth_m: float | None
    max_depth_m: float | None
    median_depth_m: float | None
    avg_depth_m: float | None
    buckets: list[dict[str, int | str]]

@dataclass(frozen=True)
class AreaStats:
    water_area_m2: float
    cloud_area_m2: float

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

@lru_cache(maxsize=64)
def _fetch_map_stats_cached(
    observation_date: str,
    model_id: str,
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
) -> MapStats:
    """Cached hazard map stats for identical date / model / bbox arguments."""
    rows = execute_read_query(
        _MAP_STATS_QUERY,
        {
            "observation_date": observation_date,
            "model_id": model_id,
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
    )
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

    _MAP_STATS_QUERY = _MAP_STATS_QUERY

    _WATER_DATE_COUNTS_QUERY = """
        SELECT
            observation_date,
            SUM(
                CASE
                    WHEN class = 1 AND COALESCE(is_permanent, false) = false THEN 1
                    ELSE 0
                END
            ) AS water_count,
            SUM(CASE WHEN class = -1 THEN 1 ELSE 0 END) AS cloud_count
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
        HAVING SUM(
            CASE
                WHEN class = 1 AND COALESCE(is_permanent, false) = false THEN 1
                ELSE 0
            END
        ) > 0
        ORDER BY observation_date ASC;
    """

    _DEPTH_SUMMARY_QUERY = """
        SELECT
            MIN(depth_min) AS min_depth_m,
            MAX(depth_min) AS max_depth_m,
            AVG(depth_min) AS avg_depth_m,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY depth_min) AS median_depth_m
        FROM hazard_masks
        WHERE observation_date = :observation_date
          AND model_id = :model_id
          AND class = 1
          AND COALESCE(is_permanent, false) = false
          AND ST_Intersects(
              geometry,
              ST_Transform(
                  ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
                  ST_SRID(geometry)
              )
          );
    """

    _DEPTH_BUCKETS_QUERY = """
        SELECT
            CASE
                WHEN depth_min < 0.25 THEN '0-0.25'
                WHEN depth_min < 0.5 THEN '0.25-0.5'
                WHEN depth_min < 1.0 THEN '0.5-1.0'
                WHEN depth_min < 1.5 THEN '1.0-1.5'
                WHEN depth_min < 2.0 THEN '1.5-2.0'
                WHEN depth_min < 2.5 THEN '2.0-2.5'
                WHEN depth_min < 3.0 THEN '2.5-3.0'
                WHEN depth_min < 4.0 THEN '3.0-4.0'
                WHEN depth_min < 5.0 THEN '4.0-5.0'
                ELSE '5.0+'
            END AS depth_m,
            COUNT(*) AS polygon_count
        FROM hazard_masks
        WHERE observation_date = :observation_date
          AND model_id = :model_id
          AND class = 1
          AND COALESCE(is_permanent, false) = false
          AND ST_Intersects(
              geometry,
              ST_Transform(
                  ST_MakeEnvelope(:min_lon, :min_lat, :max_lon, :max_lat, 4326),
                  ST_SRID(geometry)
              )
          )
        GROUP BY 1
        ORDER BY MIN(depth_min);
    """

    _AREA_STATS_QUERY = """
        SELECT
            COALESCE(
                SUM(
                    CASE
                        WHEN class = 1 AND COALESCE(is_permanent, false) = false
                        THEN ST_Area(geometry::geography)
                        ELSE 0
                    END
                ),
                0
            ) AS water_area_m2,
            COALESCE(
                SUM(CASE WHEN class = -1 THEN ST_Area(geometry::geography) ELSE 0 END),
                0
            ) AS cloud_area_m2
        FROM hazard_masks
        WHERE observation_date = :observation_date
          AND model_id = :model_id
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

    def get_water_date_counts(
        self, bbox: list[float], start_date: str, end_date: str
    ) -> list[WaterDateCount]:
        params = {
            "start_date": start_date,
            "end_date": end_date,
            **_bbox_params(bbox),
        }
        rows = execute_read_query(self._WATER_DATE_COUNTS_QUERY, params)
        return [
            WaterDateCount(
                date=str(row["observation_date"]),
                water_count=_safe_int(row.get("water_count")),
                cloud_count=_safe_int(row.get("cloud_count")),
            )
            for row in rows
        ]

    def get_depth_profile(
        self, observation_date: str, model_id: str, bbox: list[float]
    ) -> DepthProfile | None:
        params = {
            "observation_date": observation_date,
            "model_id": model_id,
            **_bbox_params(bbox),
        }
        try:
            summary_rows = execute_read_query(self._DEPTH_SUMMARY_QUERY, params)
            bucket_rows = execute_read_query(self._DEPTH_BUCKETS_QUERY, params)
        except Exception:
            return None

        if not summary_rows:
            return None

        summary = summary_rows[0]
        buckets = [
            {
                "depth_m": str(row.get("depth_m", "")),
                "polygon_count": _safe_int(row.get("polygon_count")),
            }
            for row in bucket_rows
        ]
        return DepthProfile(
            min_depth_m=_safe_float(summary.get("min_depth_m")),
            max_depth_m=_safe_float(summary.get("max_depth_m")),
            median_depth_m=_safe_float(summary.get("median_depth_m")),
            avg_depth_m=_safe_float(summary.get("avg_depth_m")),
            buckets=buckets,
        )

    def get_area_stats(
        self, observation_date: str, model_id: str, bbox: list[float]
    ) -> AreaStats:
        params = {
            "observation_date": observation_date,
            "model_id": model_id,
            **_bbox_params(bbox),
        }
        rows = execute_read_query(self._AREA_STATS_QUERY, params)
        if not rows:
            return AreaStats(0.0, 0.0)

        row = rows[0]
        return AreaStats(
            water_area_m2=float(_safe_float(row.get("water_area_m2")) or 0.0),
            cloud_area_m2=float(_safe_float(row.get("cloud_area_m2")) or 0.0),
        )

    def get_map_stats(
        self, observation_date: str, model_id: str, bbox: list[float]
    ) -> MapStats:
        return _fetch_map_stats_cached(
            observation_date,
            model_id,
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )

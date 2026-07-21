"""Shared helpers for BDTOPO PostGIS tools."""

from __future__ import annotations

import json
import os
from decimal import Decimal
from typing import Any

import psycopg
import psycopg.sql
from psycopg.rows import DictRow, dict_row

from config import get_config
from utils.bbox_service import get_city_bbox
from utils.contracts import ToolArtifacts, ToolCoordinates

SafeQuery = psycopg.sql.Composable | str


def resolve_database_url() -> str:
    config = get_config()
    return config.bdtopo_database_url or os.getenv("BDTOPO_DATABASE_URL", "").strip()


def run_query(
    sql_query: SafeQuery, params: tuple[Any, ...] = ()
) -> list[dict[str, Any]]:
    """Run a SQL query and return the results as a list of dictionaries."""
    config = get_config()
    database_url = resolve_database_url()
    if not database_url:
        raise ValueError(
            "BDTOPO database is not configured. Set BDTOPO_DATABASE_URL to enable this tool."
        )

    statement_timeout_ms = max(config.bdtopo_query_timeout_seconds, 1) * 1000
    connection = psycopg.Connection[DictRow]
    with connection.connect(database_url, row_factory=dict_row) as db_connection:
        with db_connection.cursor() as cursor:
            cursor.execute(
                psycopg.sql.SQL("SET statement_timeout = {}").format(
                    psycopg.sql.Literal(statement_timeout_ms)
                )
            )
            cursor.execute(sql_query, params)  # type: ignore[arg-type]
            return [dict(row) for row in cursor.fetchall()]


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    return value


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: _json_safe(value) for key, value in row.items()} for row in rows]


def top_values(
    rows: list[dict[str, Any]], key: str, max_items: int = 5
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        counts[value_str] = counts.get(value_str, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:max_items]
    return [{"value": value, "count": count} for value, count in ordered]


def distance_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    distances = [
        float(row["distance_m"]) for row in rows if row.get("distance_m") is not None
    ]
    if not distances:
        return {
            "nearest_distance_m": None,
            "farthest_distance_m": None,
            "avg_distance_m": None,
        }
    return {
        "nearest_distance_m": round(min(distances), 1),
        "farthest_distance_m": round(max(distances), 1),
        "avg_distance_m": round(sum(distances) / len(distances), 1),
    }


def _strip_z_from_coordinates(value: Any) -> Any:
    if isinstance(value, list):
        if value and all(isinstance(item, (int, float)) for item in value):
            return value[:2]
        return [_strip_z_from_coordinates(item) for item in value]
    return value


def _force_2d_geometry(geometry: dict[str, Any]) -> dict[str, Any]:
    geometry_2d = dict(geometry)
    if "coordinates" in geometry_2d:
        geometry_2d["coordinates"] = _strip_z_from_coordinates(
            geometry_2d.get("coordinates")
        )
    if isinstance(geometry_2d.get("geometries"), list):
        geometry_2d["geometries"] = [
            _force_2d_geometry(item) if isinstance(item, dict) else item
            for item in geometry_2d["geometries"]
        ]
    return geometry_2d


def to_feature_collection(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    for row in rows:
        geom_geojson = row.get("geom_geojson")
        if not geom_geojson:
            continue
        geometry: Any = geom_geojson
        if isinstance(geom_geojson, str):
            try:
                geometry = json.loads(geom_geojson)
            except json.JSONDecodeError:
                continue
        if not isinstance(geometry, dict):
            continue
        geometry = _force_2d_geometry(geometry)
        properties = {
            key: _json_safe(value)
            for key, value in row.items()
            if key != "geom_geojson"
        }
        # Normalize common tooltip fields across heterogeneous query outputs.
        # Some tools return road_label/zone_source/etc. instead of label/source_table.
        label_candidates = (
            "label",
            "road_label",
            "zone_label",
            "nom_officiel",
            "object_id",
            "road_id",
            "zone_id",
            "table",
            "metric_key",
            "signal",
        )
        source_candidates = (
            "source_table",
            "zone_source",
            "source",
            "table",
            "metric_key",
            "signal",
        )
        canonical_label = next(
            (
                str(value).strip()
                for key in label_candidates
                if (value := properties.get(key)) is not None and str(value).strip()
            ),
            "",
        )
        canonical_source = next(
            (
                str(value).strip()
                for key in source_candidates
                if (value := properties.get(key)) is not None and str(value).strip()
            ),
            "",
        )
        if canonical_label:
            properties["label"] = canonical_label
        if canonical_source:
            properties["source_table"] = canonical_source
        feature: dict[str, Any] = {
            "type": "Feature",
            "geometry": geometry,
            "properties": properties,
        }
        # Deck/pydeck tooltip interpolation can vary by layer/data path.
        # Mirror simple properties to top-level for robust "{label}" style access.
        for key, value in properties.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                feature[key] = value
        features.append(feature)
    return {"type": "FeatureCollection", "features": features}


def map_urls(coords: ToolCoordinates) -> list[str]:
    return [
        (
            f"https://www.openstreetmap.org/?mlat={coords.lat}&mlon={coords.lon}"
            f"#map=13/{coords.lat}/{coords.lon}"
        ),
        f"https://macarte.ign.fr/carte/1X3jxe/Carte-ouverte?lon={coords.lon}&lat={coords.lat}&zoom=13",
    ]


def build_map_artifacts(
    *,
    title: str,
    coords: ToolCoordinates,
    radius_m: int | None,
    rows: list[dict[str, Any]],
    bbox: list[float] | None = None,
    fill_color: list[int] | None = None,
) -> ToolArtifacts:
    feature_collection = to_feature_collection(rows)
    map_spec: dict[str, Any] = {
        "title": title,
        "view_state": {
            "latitude": coords.lat,
            "longitude": coords.lon,
            "zoom": 13,
        },
        "tooltip": {
            "text": "Label: {label}\nSource: {source_table}\nDistance (m): {distance_m}"
        },
        "layers": [],
    }
    if radius_m is not None:
        map_spec["query_point"] = {
            "lat": coords.lat,
            "lon": coords.lon,
            "radius_m": radius_m,
        }
    if bbox:
        map_spec["bbox"] = bbox

    if feature_collection["features"]:
        map_spec["layers"].append(
            {
                "type": "GeoJsonLayer",
                "data": feature_collection,
                "stroked": True,
                "filled": True,
                "get_fill_color": fill_color or [33, 150, 243, 90],
                "get_line_color": [33, 150, 243, 220],
                "line_width_min_pixels": 1,
                "pickable": True,
                "auto_highlight": True,
            }
        )

    return ToolArtifacts(maps=[map_spec], thumbnails=[], urls=map_urls(coords))


def resolve_area_context(
    *,
    input_mode: str,
    lat: float | None,
    lon: float | None,
    radius_m: int,
    place_name: str | None = None,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    mode = (input_mode or "point").strip().lower()

    if mode == "point":
        if lat is None or lon is None:
            raise ValueError("Point mode requires lat and lon.")
        return {
            "mode": "point",
            "coords": ToolCoordinates(lat=float(lat), lon=float(lon)),
            "radius_m": max(int(radius_m or 1), 1),
            "bbox": None,
            "place_label": None,
        }

    if mode == "place_name":
        if not place_name or not place_name.strip():
            raise ValueError("place_name mode requires a non-empty place_name.")
        raw_bbox, raw_lat, raw_lon, resolved_name = get_city_bbox(
            place_name.strip()
        )
        if not raw_bbox or len(raw_bbox) != 4 or raw_lat is None or raw_lon is None:
            raise ValueError(f"Could not resolve place_name '{place_name}'.")
        south, north, west, east = (float(value) for value in raw_bbox)
        min_lat = min(south, north)
        max_lat = max(south, north)
        min_lon = min(west, east)
        max_lon = max(west, east)
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        return {
            "mode": "bbox",
            "coords": ToolCoordinates(lat=center_lat, lon=center_lon),
            "radius_m": max(int(radius_m or 1), 1),
            "bbox": [min_lon, min_lat, max_lon, max_lat],
            "place_label": resolved_name,
        }

    if mode == "bbox":
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise ValueError(
                "bbox mode requires bbox=[min_lon,min_lat,max_lon,max_lat]."
            )
        min_lon, min_lat, max_lon, max_lat = (float(value) for value in bbox)
        center_lat = (min_lat + max_lat) / 2
        center_lon = (min_lon + max_lon) / 2
        return {
            "mode": "bbox",
            "coords": ToolCoordinates(lat=center_lat, lon=center_lon),
            "radius_m": max(int(radius_m or 1), 1),
            "bbox": [min_lon, min_lat, max_lon, max_lat],
            "place_label": None,
        }

    raise ValueError("Unsupported input_mode. Use one of: point, place_name, bbox.")


def qualified_identifier(dotted_name: str) -> psycopg.sql.Composed:
    """Turn ``"schema.table"`` or ``"column"`` into safe SQL identifiers."""
    parts = dotted_name.split(".")
    return psycopg.sql.SQL(".").join(psycopg.sql.Identifier(p) for p in parts)


def area_filter(
    *,
    geom_col: str,
    context: dict[str, Any],
) -> tuple[psycopg.sql.Composed, tuple[Any, ...]]:
    col = qualified_identifier(geom_col)
    if context["mode"] == "bbox":
        min_lon, min_lat, max_lon, max_lat = context["bbox"]
        return (
            psycopg.sql.SQL(
                "ST_Intersects({col}, ST_MakeEnvelope(%s, %s, %s, %s, 4326))"
            ).format(
                col=col,
            ),
            (min_lon, min_lat, max_lon, max_lat),
        )
    coords = context["coords"]
    radius_m = context["radius_m"]
    return (
        psycopg.sql.SQL(
            "ST_DWithin({col}::geography, ST_SetSRID(ST_Point(%s, %s), 4326)::geography, %s)"
        ).format(col=col),
        (coords.lon, coords.lat, radius_m),
    )

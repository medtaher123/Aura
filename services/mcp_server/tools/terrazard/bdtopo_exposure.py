"""Fetch BDTOPO building and agricultural footprints for flood-damage rasterization."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import psycopg.sql

from tools.bdtopo_common import normalize_rows, run_query

BDTOPO_USAGE_TO_ASSET: dict[str, str] = {
    "résidentiel": "residential",
    "residentiel": "residential",
    "commercial et services": "commercial",
    "industriel": "industrial",
    "annexe": "residential",
    "religieux": "commercial",
    "sportif": "commercial",
    "indifférenciée": "residential",
    "indifferenciee": "residential",
}

BDTOPO_VEGETATION_TO_ASSET: dict[str, str] = {
    "terre labourée": "agriculture",
    "terre labouree": "agriculture",
    "vigne": "agriculture",
    "prairie": "agriculture",
    "lande": "agriculture",
    "friche": "agriculture",
    "verger": "agriculture",
    "peupleraie": "agriculture",
}


@dataclass(frozen=True)
class ExposureSlice:
    """Exposed footprint area for one land type inside one flood depth band.

    Downstream damage estimation multiplies ``area_m2`` by a JRC depth-damage
    curve looked up with ``asset_class`` and ``representative_depth_m``.
    """

    source: str
    """Qualified BDTOPO table, e.g. ``bdtopo_raw.batiment``."""

    land_type: str
    """Raw BDTOPO usage/nature label (before asset-class mapping)."""

    asset_class: str
    """Damage curve key: residential, commercial, industrial, or agriculture."""

    depth_min_m: float
    depth_max_m: float
    representative_depth_m: float
    area_m2: float
    """Sum of exposed raster cell areas in square metres."""

    feature_count: int
    """Approximate count of distinct BDTOPO features contributing pixels."""


@dataclass(frozen=True)
class BdtopoFeature:
    """Single BDTOPO footprint used as rasterization input."""

    source: str
    land_type: str
    asset_class: str
    feature_id: int
    geojson: dict[str, Any]


@dataclass(frozen=True)
class ExposureLayer:
    """Config for one BDTOPO asset table to load inside the AOI.

    Add a new layer here (and append it to ``EXPOSURE_LAYERS``) when supporting
    another asset type—roads, infrastructure, etc.—without changing query logic.
    """

    table: str
    """Unqualified table name in ``schema`` (e.g. ``batiment``)."""

    alias: str
    """SQL table alias used in the fetch query."""

    land_type_columns: tuple[str, ...]
    """Candidate columns for grouping (first existing column wins)."""

    map_asset: Callable[[str | None], str | None]
    """Map a land-type label to a damage ``asset_class``.

    Return ``None`` to skip unmapped labels (e.g. non-agricultural vegetation).
    """

    schema: str = "bdtopo_raw"

    @property
    def source(self) -> str:
        """Qualified table name stored on each feature / exposure slice."""
        return f"{self.schema}.{self.table}"


def _normalize_land_label(value: str | None) -> str:
    """Lowercase and collapse whitespace so accented labels match lookup keys."""
    return " ".join((value or "").strip().lower().split())


def map_usage_to_asset(usage: str | None) -> str:
    """Map a BDTOPO building usage label to a JRC damage asset class.

    Unknown usages default to ``residential`` so buildings are never dropped
    from the damage estimate.
    """
    normalized = _normalize_land_label(usage)
    return BDTOPO_USAGE_TO_ASSET.get(normalized, "residential")


def map_vegetation_to_asset(nature: str | None) -> str | None:
    """Map a BDTOPO vegetation nature to ``agriculture``, or ``None`` to skip.

    Only agricultural land-cover classes contribute to vegetation damage;
    forests and other natures are ignored.
    """
    normalized = _normalize_land_label(nature)
    return BDTOPO_VEGETATION_TO_ASSET.get(normalized)


EXPOSURE_LAYERS: tuple[ExposureLayer, ...] = (
    ExposureLayer(
        table="batiment",
        alias="b",
        land_type_columns=("usage_1", "usage1", "nature"),
        map_asset=map_usage_to_asset,
    ),
    ExposureLayer(
        table="zone_de_vegetation",
        alias="v",
        land_type_columns=("nature", "nature_detaillee"),
        map_asset=map_vegetation_to_asset,
    ),
)
"""Default BDTOPO layers used by flood-damage exposure collection."""


@lru_cache(maxsize=32)
def _detect_column(table_name: str, candidates: tuple[str, ...]) -> str | None:
    """Return the first candidate column that exists on ``bdtopo_raw.<table>``."""
    rows = run_query(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'bdtopo_raw'
          AND table_name = %s
        """,
        (table_name,),
    )
    columns = {str(row["column_name"]).lower(): str(row["column_name"]) for row in rows}
    for candidate in candidates:
        if candidate in columns:
            return columns[candidate]
    return None


@lru_cache(maxsize=32)
def _geometry_metadata(table_name: str) -> tuple[str, int] | None:
    """Return ``(geometry_column, srid)`` for ``bdtopo_raw.<table>``."""
    rows = run_query(
        """
        SELECT f_geometry_column, srid
        FROM public.geometry_columns
        WHERE f_table_schema = 'bdtopo_raw'
          AND f_table_name = %s
        LIMIT 1
        """,
        (table_name,),
    )
    if not rows:
        return None
    srid = int(rows[0]["srid"] or 4326)
    if srid <= 0:
        srid = 4326
    return str(rows[0]["f_geometry_column"]), srid


@dataclass(frozen=True)
class _ResolvedLayer:
    """Exposure layer with geometry / land-type columns resolved once."""

    layer: ExposureLayer
    geom_col: str
    srid: int
    land_type_col: str | None


def _resolve_layer(layer: ExposureLayer) -> _ResolvedLayer | None:
    """Resolve and cache schema details needed to query ``layer``."""
    meta = _geometry_metadata(layer.table)
    if not meta:
        return None
    geom_col, srid = meta
    return _ResolvedLayer(
        layer=layer,
        geom_col=geom_col,
        srid=srid,
        land_type_col=_detect_column(layer.table, layer.land_type_columns),
    )


def _aoi_envelope_params(
    bbox: list[float], srid: int
) -> tuple[float, float, float, float, int]:
    """Project TerraZard bbox into the table CRS for an index-friendly envelope.

    Returns ``(minx, miny, maxx, maxy, srid)`` suitable for ``ST_MakeEnvelope``.
    """
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    if srid == 4326:
        return min_lon, min_lat, max_lon, max_lat, srid

    from rasterio.warp import transform_bounds

    minx, miny, maxx, maxy = transform_bounds(
        "EPSG:4326",
        f"EPSG:{srid}",
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        densify_pts=21,
    )
    return minx, miny, maxx, maxy, srid


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


def _land_type_sql_filter(
    resolved: _ResolvedLayer,
) -> tuple[psycopg.sql.Composable, tuple[Any, ...]]:
    """Push vegetation nature filtering into SQL to avoid scanning forests/etc."""
    if (
        resolved.layer.table != "zone_de_vegetation"
        or not resolved.land_type_col
        or resolved.layer.map_asset is not map_vegetation_to_asset
    ):
        return psycopg.sql.SQL(""), ()

    natures = tuple(sorted(BDTOPO_VEGETATION_TO_ASSET.keys()))
    return (
        psycopg.sql.SQL(
            " AND lower(btrim({alias}.{col}::text)) = ANY(%s)"
        ).format(
            alias=psycopg.sql.Identifier(resolved.layer.alias),
            col=psycopg.sql.Identifier(resolved.land_type_col),
        ),
        (list(natures),),
    )


def _fetch_layer_features(
    resolved: _ResolvedLayer,
    bbox: list[float],
    *,
    feature_id_offset: int,
) -> list[BdtopoFeature]:
    """Fetch AOI-clipped BDTOPO footprints using a GiST-friendly envelope filter.

    # TODO: Pre-compute and store static BDTOPO asset raster grids upfront (e.g. COG/GeoTIFF) to avoid converting vector data to raster on-the-fly.
    """
    layer = resolved.layer
    land_type_expr = (
        psycopg.sql.SQL("{alias}.{col}").format(
            alias=psycopg.sql.Identifier(layer.alias),
            col=psycopg.sql.Identifier(resolved.land_type_col),
        )
        if resolved.land_type_col
        else psycopg.sql.SQL("'unknown'")
    )
    geom_ident = psycopg.sql.Identifier(resolved.geom_col)
    alias = psycopg.sql.Identifier(layer.alias)
    minx, miny, maxx, maxy, srid = _aoi_envelope_params(bbox, resolved.srid)
    nature_filter, nature_params = _land_type_sql_filter(resolved)
    # ~2 m in projected CRS; ~2e-5 deg ≈ 2 m at mid-latitudes for EPSG:4326.
    simplify_tol = 2.0 if srid != 4326 else 0.00002

    rows = normalize_rows(
        run_query(
            psycopg.sql.SQL(
                """
                WITH aoi AS (
                    SELECT ST_MakeEnvelope(%s, %s, %s, %s, %s) AS geom
                ),
                clipped AS (
                    SELECT
                        {land_type}::text AS land_type,
                        ST_SimplifyPreserveTopology(
                            ST_CollectionExtract(
                                ST_MakeValid(
                                    ST_Intersection({alias}.{geom}, aoi.geom)
                                ),
                                3
                            ),
                            %s
                        ) AS geom
                    FROM {schema}.{table} {alias}
                    CROSS JOIN aoi
                    WHERE {alias}.{geom} && aoi.geom
                      AND ST_Intersects({alias}.{geom}, aoi.geom)
                      {nature_filter}
                )
                SELECT
                    land_type,
                    ST_AsGeoJSON(ST_Transform(geom, 4326), 6) AS geojson
                FROM clipped
                WHERE geom IS NOT NULL
                  AND NOT ST_IsEmpty(geom)
                """
            ).format(
                land_type=land_type_expr,
                schema=psycopg.sql.Identifier(layer.schema),
                table=psycopg.sql.Identifier(layer.table),
                alias=alias,
                geom=geom_ident,
                nature_filter=nature_filter,
            ),
            (minx, miny, maxx, maxy, srid, simplify_tol, *nature_params),
        )
    )

    features: list[BdtopoFeature] = []
    for index, row in enumerate(rows, start=1):
        land_type = str(row.get("land_type") or "unknown")
        asset_class = layer.map_asset(land_type)
        if not asset_class:
            continue
        geometry = _parse_geojson(row.get("geojson"))
        if geometry is None:
            continue
        features.append(
            BdtopoFeature(
                source=layer.source,
                land_type=land_type,
                asset_class=asset_class,
                feature_id=feature_id_offset + index,
                geojson=geometry,
            )
        )
    return features


def fetch_bdtopo_features(
    bbox: list[float],
    layers: tuple[ExposureLayer, ...] = EXPOSURE_LAYERS,
) -> list[BdtopoFeature]:
    """Load BDTOPO footprints inside the AOI for on-the-fly rasterization.

    ``bbox`` is TerraZard order ``[min_lat, max_lat, min_lon, max_lon]``.
    Geometries are returned in EPSG:4326; the raster engine reprojects them
    onto the shared damage grid.
    """
    # TODO: Pre-compute and store static BDTOPO asset raster grids upfront (e.g. COG/GeoTIFF) to avoid converting vector data to raster on-the-fly.
    resolved_layers = [
        resolved
        for layer in layers
        if (resolved := _resolve_layer(layer)) is not None
    ]
    features: list[BdtopoFeature] = []
    feature_id_offset = 0
    for resolved in resolved_layers:
        layer_features = _fetch_layer_features(
            resolved,
            bbox,
            feature_id_offset=feature_id_offset,
        )
        features.extend(layer_features)
        if layer_features:
            feature_id_offset = max(item.feature_id for item in layer_features)
    return features

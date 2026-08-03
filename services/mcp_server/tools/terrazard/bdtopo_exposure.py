"""Fetch BDTOPO footprints and measure exposure via TerraZard depth-raster zonal stats."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import numpy as np
import psycopg.sql
from rasterio import features as rio_features
from rasterio.warp import transform_bounds, transform_geom

from tools.bdtopo_common import normalize_rows, run_query
from tools.terrazard.depth_bands import DepthBand
from tools.terrazard.depth_raster import DepthRaster

# Cap GeoJSON of flood-touched buildings returned in the tool payload.
_MAX_TOUCHED_BUILDINGS = 500
# ~2 m simplify in projected CRS; ~2e-5 deg ≈ 2 m at mid-latitudes for EPSG:4326.
_SIMPLIFY_TOLERANCE_M = 2.0
_SIMPLIFY_TOLERANCE_DEG = 0.00002


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
    land_type: str
    asset_class: str
    depth_min_m: float
    depth_max_m: float
    representative_depth_m: float
    area_m2: float
    """Sum of exposed raster cell areas in square metres."""

    feature_count: int
    """Count of distinct BDTOPO features contributing pixels."""


@dataclass(frozen=True)
class BdtopoFeature:
    """Single BDTOPO footprint used for zonal stats against the depth raster."""

    source: str
    land_type: str
    asset_class: str
    feature_id: int
    geojson: dict[str, Any]


@dataclass(frozen=True)
class ExposureLayer:
    """Config for one BDTOPO asset table to load inside the AOI."""

    table: str
    alias: str
    land_type_columns: tuple[str, ...]
    map_asset: Callable[[str | None], str | None]
    schema: str = "bdtopo_raw"

    @property
    def source(self) -> str:
        return f"{self.schema}.{self.table}"


def _normalize_land_label(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def map_usage_to_asset(usage: str | None) -> str:
    normalized = _normalize_land_label(usage)
    return BDTOPO_USAGE_TO_ASSET.get(normalized, "residential")


def map_vegetation_to_asset(nature: str | None) -> str | None:
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


@lru_cache(maxsize=32)
def _detect_column(table_name: str, candidates: tuple[str, ...]) -> str | None:
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
    layer: ExposureLayer
    geom_col: str
    srid: int
    land_type_col: str | None


def _resolve_layer(layer: ExposureLayer) -> _ResolvedLayer | None:
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
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    if srid == 4326:
        return min_lon, min_lat, max_lon, max_lat, srid

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
    """Fetch AOI-clipped BDTOPO footprints as EPSG:4326 GeoJSON."""
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
    simplify_tol = (
        _SIMPLIFY_TOLERANCE_M if srid != 4326 else _SIMPLIFY_TOLERANCE_DEG
    )

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
    """Load BDTOPO footprints inside the AOI for depth-raster zonal stats."""
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


@dataclass(frozen=True)
class ZonalExposureResult:
    exposure_slices: list[ExposureSlice]
    touched_buildings: dict[str, Any]


def _feature_band_areas(
    feature: BdtopoFeature,
    depth_raster: DepthRaster,
) -> dict[int, float]:
    """Return band_index → exposed area_m2 for one footprint."""
    try:
        geom_2154 = transform_geom(
            "EPSG:4326",
            depth_raster.crs.to_string(),
            feature.geojson,
        )
    except Exception:
        return {}

    mask = rio_features.geometry_mask(
        [geom_2154],
        out_shape=depth_raster.out_shape,
        transform=depth_raster.transform,
        invert=True,
        all_touched=False,
    )
    if not np.any(mask):
        return {}

    pixels = depth_raster.band_index[mask]
    flooded = pixels[pixels > 0]
    if flooded.size == 0:
        return {}

    areas: dict[int, float] = {}
    for band_i, count in zip(*np.unique(flooded, return_counts=True), strict=True):
        areas[int(band_i)] = float(count) * depth_raster.cell_area_m2
    return areas


def empty_touched_buildings() -> dict[str, Any]:
    """Empty FeatureCollection used when there is nothing to expose."""
    return {"type": "FeatureCollection", "features": []}


def collect_bdtopo_exposure(
    depth_raster: DepthRaster,
    features: list[BdtopoFeature],
    *,
    max_touched_buildings: int = _MAX_TOUCHED_BUILDINGS,
) -> ZonalExposureResult:
    """Measure BDTOPO exposure by zonal stats on the TerraZard depth raster.

    Returns aggregated ``ExposureSlice`` rows plus a capped FeatureCollection of
    flood-touched building footprints.
    """
    bands = depth_raster.depth_bands
    if not bands or not features:
        return ZonalExposureResult(
            exposure_slices=[],
            touched_buildings=empty_touched_buildings(),
        )

    # key: (source, land_type, asset_class, band_index) → area_m2, feature_ids
    area_buckets: dict[tuple[str, str, str, int], float] = {}
    feature_buckets: dict[tuple[str, str, str, int], set[int]] = {}
    touched: list[tuple[float, BdtopoFeature, dict[int, float]]] = []

    for feature in features:
        band_areas = _feature_band_areas(feature, depth_raster)
        if not band_areas:
            continue
        total_area = sum(band_areas.values())
        if feature.source.endswith(".batiment"):
            touched.append((total_area, feature, band_areas))

        for band_i, area_m2 in band_areas.items():
            key = (feature.source, feature.land_type, feature.asset_class, band_i)
            area_buckets[key] = area_buckets.get(key, 0.0) + area_m2
            feature_buckets.setdefault(key, set()).add(feature.feature_id)

    slices: list[ExposureSlice] = []
    for (source, land_type, asset_class, band_i), area_m2 in area_buckets.items():
        if band_i < 1 or band_i > len(bands) or area_m2 <= 0:
            continue
        band = bands[band_i - 1]
        key = (source, land_type, asset_class, band_i)
        slices.append(
            ExposureSlice(
                source=source,
                land_type=land_type,
                asset_class=asset_class,
                depth_min_m=band.depth_min_m,
                depth_max_m=band.depth_max_m,
                representative_depth_m=band.representative_depth_m,
                area_m2=float(area_m2),
                feature_count=len(feature_buckets.get(key, set())),
            )
        )

    touched.sort(key=lambda item: item[0], reverse=True)
    touched_features: list[dict[str, Any]] = []
    for total_area, feature, band_areas in touched[:max_touched_buildings]:
        # Deepest intersecting band for tooltip / properties.
        deepest_i = max(band_areas)
        band = bands[deepest_i - 1]
        touched_features.append(
            {
                "type": "Feature",
                "geometry": feature.geojson,
                "properties": {
                    "source": feature.source,
                    "land_type": feature.land_type,
                    "asset_class": feature.asset_class,
                    "depth_min_m": band.depth_min_m,
                    "depth_max_m": band.depth_max_m,
                    "representative_depth_m": band.representative_depth_m,
                    "intersection_area_m2": round(total_area, 1),
                },
            }
        )

    return ZonalExposureResult(
        exposure_slices=slices,
        touched_buildings={
            "type": "FeatureCollection",
            "features": touched_features,
        },
    )

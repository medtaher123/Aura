"""In-memory raster map algebra for TerraZard flood damage.
Rasterizes TerraZard hazard depth polygons and BDTOPO asset footprints onto a
shared equal-area grid (EPSG:2154), then aggregates exposed cell areas by
depth band and land type. EUR damage is applied downstream via JRC curves.
"""
from __future__ import annotations
import gc
import math
from dataclasses import dataclass
from typing import Any
import numpy as np
from rasterio import features as rio_features
from rasterio.crs import CRS
from rasterio.transform import Affine, from_origin
from rasterio.warp import transform_bounds, transform_geom
from tools.terrazard.bdtopo_exposure import BdtopoFeature, ExposureSlice
from tools.terrazard.depth_bands import DepthBand, HazardDepthPolygon, build_depth_band_defs
GRID_CRS = CRS.from_epsg(2154)
SOURCE_CRS = "EPSG:4326"
DEFAULT_RESOLUTION_M = 5.0
MAX_GRID_PIXELS = 20_000_000
ASSET_CODES: dict[str, int] = {
    "residential": 1,
    "commercial": 2,
    "industrial": 3,
    "agriculture": 4,
}
CODE_TO_ASSET: dict[int, str] = {code: name for name, code in ASSET_CODES.items()}
SOURCE_BUILDING = 1
SOURCE_VEGETATION = 2
@dataclass(frozen=True)
class RasterGrid:
    """Aligned AOI grid shared by hazard and asset rasters."""
    transform: Affine
    width: int
    height: int
    resolution_m: float
    crs: CRS = GRID_CRS

    @property
    def out_shape(self) -> tuple[int, int]:
        return (self.height, self.width)
    @property
    def cell_area_m2(self) -> float:
        return self.resolution_m * self.resolution_m
@dataclass(frozen=True)
class RasterDamageResult:
    """Raster exposure outputs compatible with ``FloodDamageService``."""
    depth_bands: list[DepthBand]
    exposure_rows: list[ExposureSlice]
    building_count: int
    total_flooded_area_m2: float
    resolution_m: float

def build_raster_grid(
    bbox: list[float],
    *,
    resolution_m: float = DEFAULT_RESOLUTION_M,
    max_pixels: int = MAX_GRID_PIXELS,
) -> RasterGrid:
    """Build an EPSG:2154 grid covering TerraZard bbox ``[min_lat, max_lat, min_lon, max_lon]``."""
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    left, bottom, right, top = transform_bounds(
        SOURCE_CRS,
        GRID_CRS,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        densify_pts=21,
    )
    if right <= left or top <= bottom:
        raise ValueError("Invalid AOI bounds after projection to EPSG:2154.")
    res = float(resolution_m)
    width = max(1, int(math.ceil((right - left) / res)))
    height = max(1, int(math.ceil((top - bottom) / res)))
    pixel_count = width * height
    if pixel_count > max_pixels:
        scale = math.sqrt(pixel_count / max_pixels)
        res *= scale
        width = max(1, int(math.ceil((right - left) / res)))
        height = max(1, int(math.ceil((top - bottom) / res)))
    transform = from_origin(left, top, res, res)
    return RasterGrid(
        transform=transform,
        width=width,
        height=height,
        resolution_m=res,
    )
def _reproject_geometry(geojson: dict[str, Any]) -> dict[str, Any]:
    return transform_geom(SOURCE_CRS, GRID_CRS, geojson, precision=3)


def _rasterize_values(
    shapes: list[tuple[dict[str, Any], Any]],
    grid: RasterGrid,
    *,
    dtype: Any,
    fill: int | float = 0,
) -> np.ndarray:
    if not shapes:
        return np.full(grid.out_shape, fill, dtype=dtype)
    return rio_features.rasterize(
        shapes,
        out_shape=grid.out_shape,
        transform=grid.transform,
        fill=fill,
        dtype=dtype,
        all_touched=False,
    )

def _rasterize_hazard_depth(
    polygons: list[HazardDepthPolygon],
    grid: RasterGrid,
) -> tuple[np.ndarray, list[DepthBand]]:
    """Rasterize nested min-depth polygons; pixel keeps the deepest depth_min."""
    band_defs = build_depth_band_defs([poly.depth_min_m for poly in polygons])
    if not band_defs:
        return np.zeros(grid.out_shape, dtype=np.int16), []
    ordered = sorted(polygons, key=lambda item: item.depth_min_m)
    shapes: list[tuple[dict[str, Any], float]] = []
    for poly in ordered:
        try:
            geom = _reproject_geometry(poly.geojson)
        except Exception:
            continue
        shapes.append((geom, float(poly.depth_min_m)))

    depth_min_raster = _rasterize_values(shapes, grid, dtype=np.float32, fill=0.0)
    band_index = np.zeros(grid.out_shape, dtype=np.int16)
    for band_i, band in enumerate(band_defs, start=1):
        mask = np.isclose(depth_min_raster, band.depth_min_m, atol=1e-4, rtol=0.0)
        band_index[mask] = np.int16(band_i)
    flooded_counts = np.bincount(band_index.ravel(), minlength=len(band_defs) + 1)
    cell_area = grid.cell_area_m2
    depth_bands = [
        DepthBand(
            depth_min_m=band.depth_min_m,
            depth_max_m=band.depth_max_m,
            representative_depth_m=band.representative_depth_m,
            flooded_area_m2=float(flooded_counts[index + 1]) * cell_area,
            geojson={},
        )
        for index, band in enumerate(band_defs)
    ]

    del depth_min_raster
    gc.collect()
    return band_index, depth_bands
    
def _source_code(source: str) -> int:
    if source.endswith(".batiment"):
        return SOURCE_BUILDING
    return SOURCE_VEGETATION

def _rasterize_assets(
    features: list[BdtopoFeature],
    grid: RasterGrid,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Rasterize BDTOPO features onto the shared grid.
    # TODO: Pre-compute and store static BDTOPO asset raster grids upfront (e.g. COG/GeoTIFF) to avoid converting vector data to raster on-the-fly.
    """
    land_types: list[str] = []
    land_type_to_code: dict[str, int] = {}
    def land_code(label: str) -> int:
        if label not in land_type_to_code:
            land_type_to_code[label] = len(land_types) + 1
            land_types.append(label)
        return land_type_to_code[label]
    # Vegetation first; buildings overwrite overlapping pixels.
    ordered = sorted(features, key=lambda item: _source_code(item.source))
    asset_shapes: list[tuple[dict[str, Any], int]] = []
    land_shapes: list[tuple[dict[str, Any], int]] = []
    source_shapes: list[tuple[dict[str, Any], int]] = []
    feature_shapes: list[tuple[dict[str, Any], int]] = []


    for feature in ordered:
        asset_code = ASSET_CODES.get(feature.asset_class)
        if asset_code is None:
            continue
        try:
            geom = _reproject_geometry(feature.geojson)
        except Exception:
            continue
        asset_shapes.append((geom, asset_code))
        land_shapes.append((geom, land_code(feature.land_type)))
        source_shapes.append((geom, _source_code(feature.source)))
        feature_shapes.append((geom, int(feature.feature_id)))
    asset_raster = _rasterize_values(asset_shapes, grid, dtype=np.int8, fill=0)
    land_raster = _rasterize_values(land_shapes, grid, dtype=np.int16, fill=0)
    source_raster = _rasterize_values(source_shapes, grid, dtype=np.int8, fill=0)
    feature_raster = _rasterize_values(feature_shapes, grid, dtype=np.int32, fill=0)
    return asset_raster, land_raster, source_raster, feature_raster, land_types


def estimate_damage_raster(
    *,
    hazard_polygons: list[HazardDepthPolygon],
    features: list[BdtopoFeature],
    bbox: list[float],
    resolution_m: float = DEFAULT_RESOLUTION_M,
) -> RasterDamageResult:
    """Rasterize hazard × assets on one grid and aggregate exposed areas.
    Cell damage algebra is:
    ``exposed = (depth_band > 0) & (asset > 0)`` then ``area = count * res²``.
    Unit EUR factors are applied later by ``FloodDamageService``.
    """
    grid = build_raster_grid(bbox, resolution_m=resolution_m)
    band_index, depth_bands = _rasterize_hazard_depth(hazard_polygons, grid)
    if not depth_bands:
        return RasterDamageResult(
            depth_bands=[],
            exposure_rows=[],
            building_count=0,
            total_flooded_area_m2=0.0,
            resolution_m=grid.resolution_m,
        )

    asset_raster, land_raster, source_raster, feature_raster, land_types = (
        _rasterize_assets(features, grid)
    )
    flooded = band_index > 0
    exposed = flooded & (asset_raster > 0)
    cell_area = float(grid.cell_area_m2)
    exposure_rows = _aggregate_exposure_slices(
        band_index=band_index,
        asset_raster=asset_raster,
        land_raster=land_raster,
        source_raster=source_raster,
        feature_raster=feature_raster,
        exposed=exposed,
        depth_bands=depth_bands,
        land_types=land_types,
        cell_area_m2=cell_area,
    )


    building_ids = feature_raster[exposed & (source_raster == SOURCE_BUILDING)]
    building_count = int(np.unique(building_ids[building_ids > 0]).size)
    total_flooded_area = float(np.count_nonzero(flooded)) * cell_area
    del (
        band_index,
        asset_raster,
        land_raster,
        source_raster,
        feature_raster,
        flooded,
        exposed,
    )
    gc.collect()
    return RasterDamageResult(
        depth_bands=depth_bands,
        exposure_rows=exposure_rows,
        building_count=building_count,
        total_flooded_area_m2=total_flooded_area,
        resolution_m=grid.resolution_m,
    )


def _aggregate_exposure_slices(
    *,
    band_index: np.ndarray,
    asset_raster: np.ndarray,
    land_raster: np.ndarray,
    source_raster: np.ndarray,
    feature_raster: np.ndarray,
    exposed: np.ndarray,
    depth_bands: list[DepthBand],
    land_types: list[str],
    cell_area_m2: float,
) -> list[ExposureSlice]:
    rows: list[ExposureSlice] = []
    if not np.any(exposed):
        return rows
    for band_i, band in enumerate(depth_bands, start=1):
        for land_code, land_type in enumerate(land_types, start=1):
            mask = exposed & (band_index == band_i) & (land_raster == land_code)
            if not np.any(mask):
                continue
            asset_code = int(asset_raster[mask][0])
            asset_class = CODE_TO_ASSET.get(asset_code)
            if not asset_class:
                continue
            source = (
                "bdtopo_raw.batiment"
                if int(source_raster[mask][0]) == SOURCE_BUILDING
                else "bdtopo_raw.zone_de_vegetation"
            )
            fids = feature_raster[mask]
            rows.append(
                ExposureSlice(
                    source=source,
                    land_type=land_type,
                    asset_class=asset_class,
                    depth_min_m=band.depth_min_m,
                    depth_max_m=band.depth_max_m,
                    representative_depth_m=band.representative_depth_m,
                    area_m2=int(np.count_nonzero(mask)) * cell_area_m2,
                    feature_count=int(np.unique(fids[fids > 0]).size),
                )
            )
    return rows
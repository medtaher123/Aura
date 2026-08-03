"""Rasterize nested TerraZard flood polygons onto an equal-area depth grid."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from rasterio import features as rio_features
from rasterio.crs import CRS
from rasterio.transform import Affine, from_origin
from rasterio.warp import transform_bounds, transform_geom
from shapely.geometry import mapping, shape

from tools.terrazard.depth_bands import DepthBand, HazardDepthPolygon, build_depth_band_defs

# French metric CRS for area-correct cells and metre buffers.
_GRID_CRS = CRS.from_epsg(2154)
_DEFAULT_RESOLUTION_M = 5.0
# Expand flood extent to absorb TerraZard boundary imprecision.
_DEFAULT_FLOOD_BUFFER_M = 10.0
# Soft cap on grid size; resolution is coarsened when exceeded.
_MAX_GRID_CELLS = 4_000_000


@dataclass(frozen=True)
class DepthRaster:
    """Aligned AOI grid of exclusive depth-band indices (0 = dry)."""

    band_index: np.ndarray
    depth_bands: list[DepthBand]
    transform: Affine
    crs: CRS
    resolution_m: float
    cell_area_m2: float
    flood_buffer_m: float

    @property
    def total_flooded_area_m2(self) -> float:
        return float(np.count_nonzero(self.band_index) * self.cell_area_m2)

    @property
    def out_shape(self) -> tuple[int, int]:
        return self.band_index.shape


def _choose_resolution(bbox: list[float], resolution_m: float) -> float:
    """Coarsen resolution when the AOI would exceed ``_MAX_GRID_CELLS``."""
    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    minx, miny, maxx, maxy = transform_bounds(
        "EPSG:4326",
        _GRID_CRS,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        densify_pts=21,
    )
    width_m = max(maxx - minx, resolution_m)
    height_m = max(maxy - miny, resolution_m)
    cells = (width_m / resolution_m) * (height_m / resolution_m)
    if cells <= _MAX_GRID_CELLS:
        return resolution_m
    scale = math.sqrt(cells / _MAX_GRID_CELLS)
    return max(resolution_m * scale, resolution_m)


def build_depth_raster(
    polygons: list[HazardDepthPolygon],
    bbox: list[float],
    *,
    resolution_m: float = _DEFAULT_RESOLUTION_M,
    flood_buffer_m: float = _DEFAULT_FLOOD_BUFFER_M,
) -> DepthRaster:
    """Rasterize nested min-depth polygons with an optional metre buffer.

    Polygons are painted shallow→deep so each pixel keeps the deepest nested
    ``depth_min``, yielding exclusive depth bands without ``ST_Difference``.
    """
    band_defs = build_depth_band_defs([poly.depth_min_m for poly in polygons])
    resolution = _choose_resolution(bbox, resolution_m)
    cell_area = resolution * resolution

    min_lat, max_lat, min_lon, max_lon = (float(v) for v in bbox)
    minx, miny, maxx, maxy = transform_bounds(
        "EPSG:4326",
        _GRID_CRS,
        min_lon,
        min_lat,
        max_lon,
        max_lat,
        densify_pts=21,
    )
    pad = max(flood_buffer_m, 0.0)
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad

    width = max(int(math.ceil((maxx - minx) / resolution)), 1)
    height = max(int(math.ceil((maxy - miny) / resolution)), 1)
    transform = from_origin(minx, maxy, resolution, resolution)

    if not band_defs:
        return DepthRaster(
            band_index=np.zeros((height, width), dtype=np.int16),
            depth_bands=[],
            transform=transform,
            crs=_GRID_CRS,
            resolution_m=resolution,
            cell_area_m2=cell_area,
            flood_buffer_m=flood_buffer_m,
        )

    depth_to_index = {
        round(band.depth_min_m, 6): index
        for index, band in enumerate(band_defs, start=1)
    }

    band_index = np.zeros((height, width), dtype=np.int16)
    for poly in sorted(polygons, key=lambda item: item.depth_min_m):
        index = depth_to_index.get(round(poly.depth_min_m, 6))
        if index is None:
            continue
        geom_2154 = transform_geom("EPSG:4326", _GRID_CRS.to_string(), poly.geojson)
        if flood_buffer_m > 0:
            buffered = shape(geom_2154).buffer(flood_buffer_m)
            if buffered.is_empty:
                continue
            geom_2154 = mapping(buffered)
        layer = rio_features.rasterize(
            [(geom_2154, index)],
            out_shape=(height, width),
            transform=transform,
            fill=0,
            dtype=np.int16,
        )
        band_index = np.where(layer > 0, layer, band_index)

    depth_bands = [
        DepthBand(
            depth_min_m=band.depth_min_m,
            depth_max_m=band.depth_max_m,
            representative_depth_m=band.representative_depth_m,
            flooded_area_m2=float(np.count_nonzero(band_index == index) * cell_area),
        )
        for index, band in enumerate(band_defs, start=1)
    ]

    return DepthRaster(
        band_index=band_index,
        depth_bands=depth_bands,
        transform=transform,
        crs=_GRID_CRS,
        resolution_m=resolution,
        cell_area_m2=cell_area,
        flood_buffer_m=flood_buffer_m,
    )

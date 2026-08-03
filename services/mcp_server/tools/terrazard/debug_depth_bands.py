"""Fetch TerraZard hazard polygons, rasterize with flood buffer, dump for map debugging.

Usage (from services/mcp_server):

    python -m tools.terrazard.debug_depth_bands \\
        --date 20240315 --location "Arles" --out /tmp/depth_bands.geojson

Writes nested hazard polygons (buffered for inspection) as GeoJSON.
Requires TERRAZARD_DATABASE_URL.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.ops import transform as shapely_transform

from config import get_config
from tools.terrazard.depth_bands import fetch_hazard_depth_polygons
from tools.terrazard.depth_raster import build_depth_raster
from tools.terrazard.spatial import normalize_terrazard_date, resolve_spatial_context
from tools.terrazard.tile_url_builder import HazardLayerTileBuilder
from tools.terrazard.utils import test_connection

# Distinct fills for successive depth levels (RGBA-ish hex for styling hints).
_BAND_COLORS = (
    "#c6dbef",
    "#9ecae1",
    "#6baed6",
    "#4292c6",
    "#2171b5",
    "#08519c",
    "#08306b",
    "#041c3a",
)


def _project_buffer_wgs84(geom_geojson: dict, buffer_m: float) -> dict:
    """Buffer a WGS84 geometry by metres via a local equirectangular approximation."""
    geom = shape(geom_geojson)
    if geom.is_empty or buffer_m <= 0:
        return geom_geojson
    centroid = geom.centroid
    lat_rad = math.radians(centroid.y)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = max(111_320.0 * math.cos(lat_rad), 1.0)
    to_m = lambda x, y, z=None: (x * m_per_deg_lon, y * m_per_deg_lat)
    to_deg = lambda x, y, z=None: (x / m_per_deg_lon, y / m_per_deg_lat)
    projected = shapely_transform(to_m, geom)
    buffered = projected.buffer(buffer_m)
    return mapping(shapely_transform(to_deg, buffered))


def _polygons_to_feature_collection(polygons, *, flood_buffer_m: float) -> dict:
    features = []
    sorted_polys = sorted(polygons, key=lambda p: p.depth_min_m)
    for index, poly in enumerate(sorted_polys):
        geometry = (
            _project_buffer_wgs84(poly.geojson, flood_buffer_m)
            if flood_buffer_m > 0
            else poly.geojson
        )
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "band_index": index,
                    "depth_min_m": poly.depth_min_m,
                    "label": f"≥ {poly.depth_min_m:g} m (buffered)",
                    "fill": _BAND_COLORS[index % len(_BAND_COLORS)],
                    "stroke": "#222222",
                    "fill-opacity": 0.35,
                    "flood_buffer_m": flood_buffer_m,
                },
                "geometry": geometry,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Observation date YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--location", default=None, help="Place name (e.g. Arles)")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--model-id", default="flood80")
    parser.add_argument(
        "--flood-buffer-m",
        type=float,
        default=10.0,
        help="Metre buffer applied to flood polygons (default 10)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("depth_bands.geojson"),
        help="Output FeatureCollection path",
    )
    args = parser.parse_args()

    print("TerraZard DB:", get_config().terrazard_database_url)
    if not test_connection():
        raise SystemExit("TerraZard database connection failed.")

    observation_date = normalize_terrazard_date(args.date, field_name="observation_date")
    model_id = HazardLayerTileBuilder.validate_model_id(args.model_id)
    coords, bbox, name = resolve_spatial_context(args.location, args.lat, args.lon)

    print(f"Location: {name}  coords=({coords.lat}, {coords.lon})")
    print(f"BBox [min_lat, max_lat, min_lon, max_lon]: {bbox}")
    print(f"Date={observation_date}  model={model_id}")
    print(f"Flood buffer: {args.flood_buffer_m:g} m")

    polygons = fetch_hazard_depth_polygons(
        observation_date=observation_date,
        model_id=model_id,
        bbox=bbox,
    )
    if not polygons:
        raise SystemExit("No hazard polygons returned (check date / model / bbox).")

    depth_raster = build_depth_raster(
        polygons,
        bbox,
        flood_buffer_m=args.flood_buffer_m,
    )
    bands = depth_raster.depth_bands

    print(f"\n{len(polygons)} nested hazard polygons → {len(bands)} exclusive depth bands")
    print(f"Raster resolution: {depth_raster.resolution_m:.2f} m")
    print(f"{'idx':>3}  {'min':>8}  {'max':>8}  {'repr':>8}  {'area_m2':>14}")
    for index, band in enumerate(bands):
        print(
            f"{index:3d}  {band.depth_min_m:8.3f}  {band.depth_max_m:8.3f}  "
            f"{band.representative_depth_m:8.3f}  {band.flooded_area_m2:14.1f}"
        )
    print(f"Total flooded area (buffered raster): {depth_raster.total_flooded_area_m2:,.1f} m²")

    collection = _polygons_to_feature_collection(
        polygons, flood_buffer_m=args.flood_buffer_m
    )
    args.out.write_text(json.dumps(collection), encoding="utf-8")
    print(f"\nWrote {args.out.resolve()}")
    print("Open in https://geojson.io or QGIS to inspect buffered nested polygons.")


if __name__ == "__main__":
    main()

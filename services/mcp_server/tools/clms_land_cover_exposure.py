"""
CLMS Land Cover Exposure Tool (lcm_global_10m_yearly_v1).

Computes land-cover mix percentages over an AOI using Copernicus CLMS
10m annual land-cover map and derives insurance-oriented exposure features.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests
import rasterio
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPolygon, Polygon, mapping

from ..config import get_config
from ..core.logger import get_logger
from ..mcp_singleton import mcp
from ..utils.bbox_service import get_city_candidates, reverse_geocode
from ..utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from ..utils.map_view_service import view_state_from_bbox

logger = get_logger(__name__)
config = get_config()

CLMS_CLASS_LABELS: dict[int, str] = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "herbaceous_wetland",
    60: "mangroves",
    70: "moss_lichen",
    80: "bare_sparse_vegetation",
    90: "built_up",
    100: "permanent_water_bodies",
    110: "snow_ice",
    254: "unclassifiable",
}


class CLMSInputError(ValueError):
    pass


class CLMSServiceError(RuntimeError):
    pass


class CLMSNoDataError(CLMSServiceError):
    pass


@dataclass(frozen=True)
class AOIContext:
    geometry: Polygon | MultiPolygon
    mode: str
    center_lat: float
    center_lon: float
    radius_m: int | None
    city_name: str | None
    quality_notes: list[str]


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _require_range(name: str, value: float, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise CLMSInputError(f"'{name}' must be between {lo} and {hi}.")
    return value


def _validate_thresholds(
    *,
    min_builtup_pct_for_high: float,
    min_water_wetland_pct_for_alert: float,
    min_valid_pixel_ratio: float,
) -> None:
    _require_range(
        "min_builtup_pct_for_high", float(min_builtup_pct_for_high), 0.0, 100.0
    )
    _require_range(
        "min_water_wetland_pct_for_alert",
        float(min_water_wetland_pct_for_alert),
        0.0,
        100.0,
    )
    _require_range("min_valid_pixel_ratio", float(min_valid_pixel_ratio), 0.0, 1.0)


def _estimate_bbox_area_m2(bounds: tuple[float, float, float, float]) -> float:
    minx, miny, maxx, maxy = bounds
    center_lat = (miny + maxy) / 2.0
    lat_m = 111_320.0 * max(0.0, (maxy - miny))
    lon_m = 111_320.0 * math.cos(math.radians(center_lat)) * max(0.0, (maxx - minx))
    return max(0.0, lat_m * lon_m)


def _point_radius_bbox_polygon(lat: float, lon: float, radius_m: int) -> Polygon:
    delta_lat = radius_m / 111_320.0
    delta_lon = radius_m / (111_320.0 * max(0.15, abs(math.cos(math.radians(lat)))))
    min_lon = lon - delta_lon
    max_lon = lon + delta_lon
    min_lat = lat - delta_lat
    max_lat = lat + delta_lat
    return Polygon(
        [
            (min_lon, min_lat),
            (max_lon, min_lat),
            (max_lon, max_lat),
            (min_lon, max_lat),
            (min_lon, min_lat),
        ]
    )


def _resolve_city_to_aoi(
    city_name: str,
    *,
    location_token: str | None,
    candidate_limit: int,
) -> AOIContext:
    query = location_token.strip() if isinstance(location_token, str) and location_token.strip() else city_name.strip()
    candidates = get_city_candidates(query, limit=max(2, int(candidate_limit)))
    if not candidates:
        raise CLMSInputError(
            f"No location candidates found for '{city_name}'. Provide lat/lon or polygon_wkt."
        )

    if location_token:
        chosen = candidates[0]
    elif len(candidates) > 1:
        preview = []
        for c in candidates[: max(2, int(candidate_limit))]:
            preview.append(
                {
                    "display_name": c.get("display_name"),
                    "lat": c.get("lat"),
                    "lon": c.get("lon"),
                    "bbox": c.get("bbox"),
                    "place_id": c.get("place_id"),
                    "osm_id": c.get("osm_id"),
                    "osm_type": c.get("osm_type"),
                }
            )
        raise CLMSInputError(
            "Location is ambiguous. Confirm with 'location_token' using "
            "'@place_id:<id>' or '@osm_id:<R|W|N><id>'. "
            f"Candidates: {preview}"
        )
    else:
        chosen = candidates[0]

    lat = _safe_float(chosen.get("lat"))
    lon = _safe_float(chosen.get("lon"))
    if lat is None or lon is None:
        raise CLMSInputError("Resolved city candidate has invalid coordinates.")

    bbox_raw = chosen.get("bbox")
    if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
        min_lat, max_lat, min_lon, max_lon = bbox_raw
        geometry = Polygon(
            [
                (float(min_lon), float(min_lat)),
                (float(max_lon), float(min_lat)),
                (float(max_lon), float(max_lat)),
                (float(min_lon), float(max_lat)),
                (float(min_lon), float(min_lat)),
            ]
        )
    else:
        # fallback on 5km bbox if source has no bbox
        geometry = _point_radius_bbox_polygon(lat, lon, radius_m=5_000)

    return AOIContext(
        geometry=geometry,
        mode="city_name",
        center_lat=float(lat),
        center_lon=float(lon),
        radius_m=None,
        city_name=str(chosen.get("display_name") or city_name),
        quality_notes=[],
    )


def _resolve_aoi(
    *,
    lat: float | None,
    lon: float | None,
    polygon_wkt: str | None,
    city_name: str | None,
    location_token: str | None,
    radius_m: int,
    candidate_limit: int,
) -> AOIContext:
    if isinstance(polygon_wkt, str) and polygon_wkt.strip():
        try:
            geom = shapely_wkt.loads(polygon_wkt.strip())
        except Exception as exc:
            raise CLMSInputError(f"Invalid polygon_wkt: {exc}") from exc
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise CLMSInputError("polygon_wkt must be a Polygon or MultiPolygon.")
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            raise CLMSInputError("polygon_wkt produced an empty geometry.")
        center = geom.centroid
        return AOIContext(
            geometry=geom,
            mode="polygon",
            center_lat=float(center.y),
            center_lon=float(center.x),
            radius_m=None,
            city_name=None,
            quality_notes=[],
        )

    if lat is not None or lon is not None:
        if lat is None or lon is None:
            raise CLMSInputError("Provide both lat and lon together.")
        lat_f = _require_range("lat", float(lat), -90.0, 90.0)
        lon_f = _require_range("lon", float(lon), -180.0, 180.0)
        geom = _point_radius_bbox_polygon(lat_f, lon_f, radius_m=radius_m)
        city = None
        try:
            rev = reverse_geocode(lat_f, lon_f)
            city = rev.get("city") or rev.get("country")
        except Exception:
            city = None
        return AOIContext(
            geometry=geom,
            mode="point_radius",
            center_lat=lat_f,
            center_lon=lon_f,
            radius_m=radius_m,
            city_name=city or f"{lat_f:.4f}, {lon_f:.4f}",
            quality_notes=[
                "Point+radius AOI is converted to a bounding box approximation."
            ],
        )

    if isinstance(city_name, str) and city_name.strip():
        return _resolve_city_to_aoi(
            city_name=city_name,
            location_token=location_token,
            candidate_limit=candidate_limit,
        )

    raise CLMSInputError(
        "Provide one location input: polygon_wkt, lat+lon, or city_name."
    )


def _resolve_year(requested_year: int | None) -> tuple[int, list[str]]:
    notes: list[str] = []
    now_utc = datetime.now(timezone.utc)
    latest_available = min(now_utc.year, 2026)
    earliest_available = 2020
    if requested_year is None:
        return latest_available, notes
    yr = int(requested_year)
    if yr < earliest_available or yr > latest_available:
        notes.append(
            f"Requested year {yr} is unavailable; using latest available year {latest_available}."
        )
        return latest_available, notes
    return yr, notes


def _year_fallback_sequence(
    preferred_year: int, *, earliest_year: int = 2020
) -> list[int]:
    """
    Build descending fallback sequence for annual CLMS layers.
    Example: preferred=2023 -> [2023, 2022, 2021, 2020]
    """
    base = int(preferred_year)
    floor = int(earliest_year)
    if base <= floor:
        return [floor]
    return list(range(base, floor - 1, -1))


def _oauth_token() -> str:
    direct_token = (getattr(config, "clms_cdse_access_token", "") or "").strip()
    if direct_token:
        return direct_token

    client_id = (getattr(config, "clms_cdse_client_id", "") or "").strip()
    client_secret = (getattr(config, "clms_cdse_client_secret", "") or "").strip()
    token_url = (
        getattr(config, "clms_cdse_token_url", "")
        or "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    )
    token_url = token_url.strip()

    if not client_id or not client_secret:
        raise CLMSServiceError(
            "CLMS/CDSE credentials are missing. Set CLMS_CDSE_CLIENT_ID and "
            "CLMS_CDSE_CLIENT_SECRET (or CLMS_CDSE_ACCESS_TOKEN)."
        )

    resp = requests.post(
        token_url,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        raise CLMSServiceError(
            f"Failed to obtain CDSE token (status={resp.status_code})."
        )
    payload = resp.json() if resp.content else {}
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise CLMSServiceError("CDSE token response does not contain access_token.")
    return token


def _compute_dimensions(bounds: tuple[float, float, float, float], max_pixels: int) -> tuple[int, int, float]:
    """
    Compute width/height for Process API while keeping pixel count bounded.
    Returns width, height, effective_resolution_m.
    """
    minx, miny, maxx, maxy = bounds
    center_lat = (miny + maxy) / 2.0
    width_m = max(1.0, 111_320.0 * math.cos(math.radians(center_lat)) * (maxx - minx))
    height_m = max(1.0, 111_320.0 * (maxy - miny))

    base_w = max(1, int(math.ceil(width_m / 10.0)))
    base_h = max(1, int(math.ceil(height_m / 10.0)))
    px = base_w * base_h
    if px <= max_pixels:
        res = max(width_m / base_w, height_m / base_h)
        return base_w, base_h, float(res)

    scale = math.sqrt(px / max_pixels)
    w = max(1, int(base_w / scale))
    h = max(1, int(base_h / scale))
    res = max(width_m / w, height_m / h)
    return w, h, float(res)


def _fetch_lcm10_raster(
    *,
    geometry: Polygon | MultiPolygon,
    year: int,
    width: int,
    height: int,
    token: str,
) -> tuple[Any, Any]:
    process_url = (
        getattr(config, "clms_sh_process_url", "")
        or "https://sh.dataspace.copernicus.eu/api/v1/process"
    ).strip()
    collection_id = (
        getattr(config, "clms_lcm_collection_id", "")
        or "828f6b20-8ffd-48f8-a1da-fefd271456db"
    ).strip()

    evalscript = """
//VERSION=3
function setup() {
  return {
    input: ["LCM10", "dataMask"],
    output: { bands: 2, sampleType: "UINT8" }
  };
}
function evaluatePixel(sample) {
  return [sample.LCM10, sample.dataMask];
}
""".strip()

    start = f"{year}-01-01T00:00:00Z"
    end = f"{year}-12-31T23:59:59Z"

    body = {
        "input": {
            "bounds": {"geometry": mapping(geometry)},
            "data": [
                {
                    "type": f"byoc-{collection_id}",
                    "dataFilter": {
                        "timeRange": {"from": start, "to": end},
                    },
                }
            ],
        },
        "output": {
            "width": int(width),
            "height": int(height),
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": evalscript,
    }

    resp = requests.post(
        process_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=90,
    )
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.text[:500]
        except Exception:
            detail = ""
        raise CLMSServiceError(
            f"CLMS Process API failed (status={resp.status_code}). {detail}"
        )

    with rasterio.open(io.BytesIO(resp.content)) as ds:
        lcm10 = ds.read(1)
        data_mask = ds.read(2)
    return lcm10, data_mask


def _class_percentages(
    *,
    lcm10: Any,
    data_mask: Any,
    polygon: Polygon | MultiPolygon,
    bounds: tuple[float, float, float, float],
    include_unclassified: bool,
) -> tuple[dict[str, float], dict[str, float], dict[str, int]]:
    height, width = lcm10.shape
    transform = from_bounds(*bounds, width=width, height=height)
    mask = geometry_mask(
        [mapping(polygon)],
        transform=transform,
        invert=True,
        out_shape=(height, width),
    )

    valid = (data_mask > 0) & mask
    total_pixels = int(mask.sum())
    valid_pixels = int(valid.sum())
    invalid_pixels = max(0, total_pixels - valid_pixels)

    if valid_pixels <= 0:
        raise CLMSNoDataError(
            "No valid pixels returned for this AOI/year (possibly outside coverage)."
        )

    selected = lcm10[valid]
    counts: dict[int, int] = {}
    for code in selected.tolist():
        code_i = int(code)
        counts[code_i] = counts.get(code_i, 0) + 1

    if not include_unclassified and 254 in counts:
        del counts[254]

    denom = sum(counts.values())
    if denom <= 0:
        raise CLMSServiceError("No classified pixels found after filtering.")

    by_code_pct: dict[str, float] = {}
    by_label_pct: dict[str, float] = {label: 0.0 for label in CLMS_CLASS_LABELS.values()}
    for code, count in counts.items():
        pct = round((count / denom) * 100.0, 2)
        by_code_pct[str(code)] = pct
        label = CLMS_CLASS_LABELS.get(code)
        if label:
            by_label_pct[label] = pct

    pixel_stats = {
        "total_pixels": int(total_pixels),
        "valid_pixels": int(valid_pixels),
        "valid_pixel_ratio": round(valid_pixels / max(1, total_pixels), 4),
        "invalid_pixels": int(invalid_pixels),
        "unclassified_pixels": int(counts.get(254, 0)),
    }
    return by_label_pct, by_code_pct, pixel_stats


def _derive_insurance_features(
    *,
    by_label_pct: dict[str, float],
    min_builtup_pct_for_high: float,
    min_water_wetland_pct_for_alert: float,
) -> dict[str, Any]:
    built_up = float(by_label_pct.get("built_up", 0.0))
    veg_buffer = float(
        by_label_pct.get("tree_cover", 0.0)
        + by_label_pct.get("shrubland", 0.0)
        + by_label_pct.get("grassland", 0.0)
        + by_label_pct.get("cropland", 0.0)
    )
    water_wetland = float(
        by_label_pct.get("herbaceous_wetland", 0.0)
        + by_label_pct.get("mangroves", 0.0)
        + by_label_pct.get("permanent_water_bodies", 0.0)
    )
    urban_density_score = round(_clamp(built_up / 60.0, 0.0, 1.0), 2)
    if built_up >= float(min_builtup_pct_for_high):
        exposure = "high"
    elif built_up >= 15.0:
        exposure = "moderate"
    else:
        exposure = "low"
    return {
        "urban_density_score": urban_density_score,
        "imperviousness_proxy_pct": round(built_up, 2),
        "vegetation_buffer_pct": round(veg_buffer, 2),
        "water_wetland_pct": round(water_wetland, 2),
        "water_proximity_flag": water_wetland >= float(min_water_wetland_pct_for_alert),
        "exposure_band": exposure,
    }


@mcp.tool()
def clms_land_cover_exposure_tool(
    *,
    lat: float | None = None,
    lon: float | None = None,
    polygon_wkt: str | None = None,
    city_name: str | None = None,
    location_token: str | None = None,
    radius_m: int = 50_000,
    year: int | None = None,
    include_unclassified: bool = True,
    return_map: bool = True,
    min_builtup_pct_for_high: float = 35.0,
    min_water_wetland_pct_for_alert: float = 10.0,
    min_valid_pixel_ratio: float = 0.8,
) -> ToolResponse:
    """
    Compute CLMS land-cover exposure mix and insurance-oriented indicators.

    Location input:
    - polygon_wkt (priority), OR
    - lat+lon (+radius_m), OR
    - city_name (optionally disambiguated with location_token).
    """
    try:
        radius_i = int(radius_m)
        if radius_i <= 0:
            raise CLMSInputError("'radius_m' must be > 0.")
        radius_i = int(_clamp(radius_i, 100, 100_000))

        _validate_thresholds(
            min_builtup_pct_for_high=float(min_builtup_pct_for_high),
            min_water_wetland_pct_for_alert=float(min_water_wetland_pct_for_alert),
            min_valid_pixel_ratio=float(min_valid_pixel_ratio),
        )

        aoi = _resolve_aoi(
            lat=lat,
            lon=lon,
            polygon_wkt=polygon_wkt,
            city_name=city_name,
            location_token=location_token,
            radius_m=radius_i,
            candidate_limit=int(getattr(config, "clms_city_candidates_limit", 5) or 5),
        )

        resolved_year, year_notes = _resolve_year(year)
        year_attempts = _year_fallback_sequence(resolved_year, earliest_year=2020)
        bounds = aoi.geometry.bounds  # minx,miny,maxx,maxy
        area_m2 = _estimate_bbox_area_m2(bounds)
        max_pixels = int(getattr(config, "clms_max_pixels", 4_000_000) or 4_000_000)
        width, height, eff_res_m = _compute_dimensions(bounds, max_pixels=max_pixels)

        token = _oauth_token()
        by_label_pct: dict[str, float] | None = None
        by_code_pct: dict[str, float] | None = None
        pixel_stats: dict[str, int | float] | None = None
        effective_year: int | None = None

        for candidate_year in year_attempts:
            try:
                lcm10, data_mask = _fetch_lcm10_raster(
                    geometry=aoi.geometry,
                    year=int(candidate_year),
                    width=width,
                    height=height,
                    token=token,
                )
                by_label_pct, by_code_pct, pixel_stats = _class_percentages(
                    lcm10=lcm10,
                    data_mask=data_mask,
                    polygon=aoi.geometry,
                    bounds=bounds,
                    include_unclassified=bool(include_unclassified),
                )
                effective_year = int(candidate_year)
                break
            except CLMSNoDataError:
                continue

        if (
            by_label_pct is None
            or by_code_pct is None
            or pixel_stats is None
            or effective_year is None
        ):
            raise CLMSServiceError(
                "No valid pixels returned for this AOI across attempted years: "
                f"{year_attempts}."
            )

        quality_notes = list(aoi.quality_notes) + list(year_notes)
        if effective_year != resolved_year:
            quality_notes.append(
                f"Requested year {resolved_year} had no valid pixels; fallback year "
                f"{effective_year} was used."
            )
        if pixel_stats["valid_pixel_ratio"] < float(min_valid_pixel_ratio):
            quality_notes.append(
                f"Valid pixel ratio ({pixel_stats['valid_pixel_ratio']}) is below the configured minimum ({min_valid_pixel_ratio})."
            )
        quality_notes.extend(
            [
                "Dataset is marked beta in official CLMS documentation.",
                "Land-cover is annual context data; it is not an event-level hazard intensity layer.",
            ]
        )

        insurance = _derive_insurance_features(
            by_label_pct=by_label_pct,
            min_builtup_pct_for_high=float(min_builtup_pct_for_high),
            min_water_wetland_pct_for_alert=float(min_water_wetland_pct_for_alert),
        )

        msg = (
            f"CLMS land-cover exposure for {aoi.city_name or 'AOI'} ({effective_year}): "
            f"built_up={insurance['imperviousness_proxy_pct']}%, "
            f"vegetation={insurance['vegetation_buffer_pct']}%, "
            f"water/wetland={insurance['water_wetland_pct']}%, "
            f"exposure_band={insurance['exposure_band']}."
        )

        coords = ToolCoordinates(lat=float(aoi.center_lat), lon=float(aoi.center_lon))
        view_state = view_state_from_bbox(
            coords, padding=0.12, min_zoom=4.0, max_zoom=11.0, radius=None
        )
        maps = []
        if return_map:
            maps.append(
                {
                    "title": "CLMS land-cover exposure AOI",
                    "view_state": view_state,
                    "layers": [
                        {
                            "type": "GeoJsonLayer",
                            "data": {
                                "type": "FeatureCollection",
                                "features": [
                                    {
                                        "type": "Feature",
                                        "geometry": mapping(aoi.geometry),
                                        "properties": {
                                            "exposure_band": insurance["exposure_band"],
                                            "built_up": insurance["imperviousness_proxy_pct"],
                                            "water_wetland": insurance["water_wetland_pct"],
                                            "vegetation": insurance["vegetation_buffer_pct"],
                                        },
                                    }
                                ],
                            },
                            "stroked": True,
                            "filled": True,
                            "get_fill_color": [0, 100, 200, 70],
                            "get_line_color": [0, 100, 200, 200],
                            "line_width_min_pixels": 1,
                            "pickable": True,
                        }
                    ],
                    "tooltip": {
                        "text": "Exposure: {exposure_band}\nBuilt-up: {built_up}%\nWater/wetland: {water_wetland}%\nVegetation: {vegetation}%"
                    },
                }
            )

        return ToolResponse(
            tool_name="clms_land_cover_exposure_tool",
            message=msg,
            city=aoi.city_name,
            coordinates=coords,
            artifacts=ToolArtifacts(maps=maps, thumbnails=[], urls=[]),
            data={
                "source": {
                    "service": "CLMS",
                    "dataset_identifier": "lcm_global_10m_yearly_v1",
                    "collection_id": str(
                        getattr(config, "clms_lcm_collection_id", "")
                        or "828f6b20-8ffd-48f8-a1da-fefd271456db"
                    ),
                    "band": "LCM10",
                    "year_used": int(effective_year),
                    "status": "beta",
                },
                "aoi": {
                    "input_mode": aoi.mode,
                    "lat": float(aoi.center_lat),
                    "lon": float(aoi.center_lon),
                    "radius_m": aoi.radius_m,
                    "area_m2_est": round(area_m2, 2),
                    "bounds_wgs84": [float(x) for x in bounds],
                },
                "pixel_stats": pixel_stats,
                "land_cover_mix_pct": by_label_pct,
                "class_code_pct": by_code_pct,
                "insurance_features": insurance,
                "thresholds_used": {
                    "min_builtup_pct_for_high": float(min_builtup_pct_for_high),
                    "min_water_wetland_pct_for_alert": float(
                        min_water_wetland_pct_for_alert
                    ),
                    "min_valid_pixel_ratio": float(min_valid_pixel_ratio),
                },
                "processing": {
                    "requested_year": year,
                    "requested_year_resolved": int(resolved_year),
                    "attempted_years_desc": [int(y) for y in year_attempts],
                    "effective_resolution_m": round(eff_res_m, 2),
                    "raster_width": int(width),
                    "raster_height": int(height),
                    "max_pixels": int(max_pixels),
                },
                "quality_notes": quality_notes,
            },
            error=False,
        )

    except CLMSInputError as exc:
        return ToolResponse(
            tool_name="clms_land_cover_exposure_tool",
            message=str(exc),
            error=True,
        )
    except CLMSServiceError as exc:
        logger.error("CLMS land-cover tool service error: %s", exc)
        return ToolResponse(
            tool_name="clms_land_cover_exposure_tool",
            message=str(exc),
            error=True,
        )
    except Exception as exc:
        logger.error("Unexpected CLMS land-cover tool error: %s", exc, exc_info=True)
        return ToolResponse(
            tool_name="clms_land_cover_exposure_tool",
            message=f"Unexpected error in clms_land_cover_exposure_tool: {exc}",
            error=True,
        )

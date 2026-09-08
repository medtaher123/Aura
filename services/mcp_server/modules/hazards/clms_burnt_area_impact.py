"""
CLMS Burnt Area Impact Tool.

Computes burnt-area exposure metrics over an AOI using Copernicus CLMS
Burnt Area products via Sentinel Hub Process API.
"""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import rasterio
import requests
from rasterio.features import geometry_mask
from rasterio.transform import from_bounds
from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPolygon, Polygon, mapping

from config import get_config
from core.logger import get_logger
from utils.bbox_service import get_city_candidates, reverse_geocode
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from utils.map_view_service import view_state_from_bbox

logger = get_logger(__name__)
config = get_config()

_TODAY_UTC = datetime.now(timezone.utc).date()

DEFAULT_COLLECTIONS = {
    "v4_daily": "162ee729-86a7-45bc-9cfe-c01f718e3216",  # 2025-present
    "v3_daily": "c698beab-cdb7-4b41-857a-63fc9a8d8c07",  # 2023-present
    "v4_monthly": "b8b617c6-182f-427e-a86c-23fc36ac6098",  # 2018-present
}

class CLMSBurntAreaInputError(ValueError):
    pass

class CLMSBurntAreaServiceError(RuntimeError):
    pass

class CLMSBurntAreaNoDataError(CLMSBurntAreaServiceError):
    pass

@dataclass(frozen=True)
class AOIContext:
    geometry: Polygon | MultiPolygon
    mode: str
    center_lat: float
    center_lon: float
    location_name: str | None
    radius_km: float | None
    quality_notes: list[str]

@dataclass(frozen=True)
class DatasetCandidate:
    key: str
    collection_id: str
    product_id: str
    min_date: datetime.date
    max_date: datetime.date | None
    uses_bf: bool

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _require_range(name: str, value: float, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise CLMSBurntAreaInputError(f"'{name}' must be between {lo} and {hi}.")
    return value

def _point_radius_bbox_polygon(lat: float, lon: float, radius_km: float) -> Polygon:
    radius_m = max(100.0, float(radius_km) * 1000.0)
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

def _estimate_bbox_area_m2(bounds: tuple[float, float, float, float]) -> float:
    minx, miny, maxx, maxy = bounds
    center_lat = (miny + maxy) / 2.0
    lat_m = 111_320.0 * max(0.0, (maxy - miny))
    lon_m = 111_320.0 * math.cos(math.radians(center_lat)) * max(0.0, (maxx - minx))
    return max(0.0, lat_m * lon_m)

def _compute_dimensions(
    bounds: tuple[float, float, float, float], *, target_res_m: float, max_pixels: int
) -> tuple[int, int, float]:
    minx, miny, maxx, maxy = bounds
    center_lat = (miny + maxy) / 2.0
    width_m = max(1.0, 111_320.0 * math.cos(math.radians(center_lat)) * (maxx - minx))
    height_m = max(1.0, 111_320.0 * (maxy - miny))

    base_w = max(1, int(math.ceil(width_m / target_res_m)))
    base_h = max(1, int(math.ceil(height_m / target_res_m)))
    px = base_w * base_h
    if px <= max_pixels:
        eff = max(width_m / base_w, height_m / base_h)
        return base_w, base_h, float(eff)

    scale = math.sqrt(px / max_pixels)
    w = max(1, int(base_w / scale))
    h = max(1, int(base_h / scale))
    eff = max(width_m / w, height_m / h)
    return w, h, float(eff)

def _parse_date(text: str, *, field_name: str) -> datetime.date:
    raw = str(text or "").strip()
    if not raw:
        raise CLMSBurntAreaInputError(f"'{field_name}' is required.")
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except Exception as exc:
        raise CLMSBurntAreaInputError(
            f"Invalid '{field_name}' format. Use YYYY-MM-DD or ISO datetime."
        ) from exc

def _resolve_date_range(
    start_date: str | None, end_date: str | None
) -> tuple[datetime.date, datetime.date]:
    if start_date is None and end_date is None:
        end = _TODAY_UTC
        return end - timedelta(days=30), end
    if start_date is None or end_date is None:
        raise CLMSBurntAreaInputError(
            "Provide both start_date and end_date, or omit both to use a default 30-day window."
        )
    start = _parse_date(start_date, field_name="start_date")
    end = _parse_date(end_date, field_name="end_date")
    if start > end:
        raise CLMSBurntAreaInputError("'start_date' must be earlier than or equal to 'end_date'.")
    return start, end

def _resolve_location_to_aoi(
    location: str, *, location_token: str | None, radius_km: float
) -> AOIContext:
    query = (
        location_token.strip()
        if isinstance(location_token, str) and location_token.strip()
        else location.strip()
    )
    candidates = get_city_candidates(
        query, limit=max(2, int(getattr(config, "clms_city_candidates_limit", 5) or 5))
    )
    if not candidates:
        raise CLMSBurntAreaInputError(
            f"No location candidates found for '{location}'. Provide lat/lon or polygon_wkt."
        )

    if location_token:
        chosen = candidates[0]
    elif len(candidates) > 1:
        preview = []
        for cand in candidates[:5]:
            preview.append(
                {
                    "display_name": cand.get("display_name"),
                    "lat": cand.get("lat"),
                    "lon": cand.get("lon"),
                    "bbox": cand.get("bbox"),
                    "place_id": cand.get("place_id"),
                    "osm_id": cand.get("osm_id"),
                    "osm_type": cand.get("osm_type"),
                }
            )
        raise CLMSBurntAreaInputError(
            "Location is ambiguous. Confirm with 'location_token' using "
            "'@place_id:<id>' or '@osm_id:<R|W|N><id>'. "
            f"Candidates: {preview}"
        )
    else:
        chosen = candidates[0]

    lat = _safe_float(chosen.get("lat"))
    lon = _safe_float(chosen.get("lon"))
    if lat is None or lon is None:
        raise CLMSBurntAreaInputError("Resolved location candidate has invalid coordinates.")

    bbox_raw = chosen.get("bbox")
    if isinstance(bbox_raw, list) and len(bbox_raw) == 4:
        min_lat, max_lat, min_lon, max_lon = bbox_raw
        geom = Polygon(
            [
                (float(min_lon), float(min_lat)),
                (float(max_lon), float(min_lat)),
                (float(max_lon), float(max_lat)),
                (float(min_lon), float(max_lat)),
                (float(min_lon), float(min_lat)),
            ]
        )
    else:
        geom = _point_radius_bbox_polygon(float(lat), float(lon), radius_km=radius_km)

    return AOIContext(
        geometry=geom,
        mode="location",
        center_lat=float(lat),
        center_lon=float(lon),
        location_name=str(chosen.get("display_name") or location),
        radius_km=None,
        quality_notes=[],
    )

def _resolve_aoi(
    *,
    location: str | None,
    lat: float | None,
    lon: float | None,
    polygon_wkt: str | None,
    radius_km: float,
    location_token: str | None,
) -> AOIContext:
    # Accept mixed inputs and enforce deterministic precedence:
    # polygon_wkt -> lat/lon -> location.
    if isinstance(polygon_wkt, str) and polygon_wkt.strip():
        try:
            geom = shapely_wkt.loads(polygon_wkt.strip())
        except Exception as exc:
            raise CLMSBurntAreaInputError(f"Invalid polygon_wkt: {exc}") from exc
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise CLMSBurntAreaInputError("polygon_wkt must be a Polygon or MultiPolygon.")
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            raise CLMSBurntAreaInputError("polygon_wkt produced an empty geometry.")
        center = geom.centroid
        return AOIContext(
            geometry=geom,
            mode="polygon",
            center_lat=float(center.y),
            center_lon=float(center.x),
            location_name=None,
            radius_km=None,
            quality_notes=[],
        )

    if lat is not None and lon is not None:
        lat_f = _require_range("lat", float(lat), -90.0, 90.0)
        lon_f = _require_range("lon", float(lon), -180.0, 180.0)
        geom = _point_radius_bbox_polygon(lat_f, lon_f, radius_km=radius_km)
        resolved_name = None
        try:
            rev = reverse_geocode(lat_f, lon_f)
            resolved_name = rev.get("city") or rev.get("country")
        except (RuntimeError, ValueError, TypeError):
            resolved_name = None
        return AOIContext(
            geometry=geom,
            mode="point_radius",
            center_lat=lat_f,
            center_lon=lon_f,
            location_name=resolved_name or f"{lat_f:.5f}, {lon_f:.5f}",
            radius_km=float(radius_km),
            quality_notes=["Point+radius AOI is converted to a bounding box approximation."],
        )

    if lat is not None or lon is not None:
        raise CLMSBurntAreaInputError(
            "Provide both lat and lon together, or omit both to use location/polygon_wkt."
        )

    if isinstance(location, str) and location.strip():
        return _resolve_location_to_aoi(
            location=location, location_token=location_token, radius_km=radius_km
        )

    raise CLMSBurntAreaInputError("Unable to resolve AOI from provided inputs.")

def _oauth_token() -> str:
    direct_token = (getattr(config, "clms_cdse_access_token", "") or "").strip()
    if direct_token:
        return direct_token

    client_id = (getattr(config, "clms_cdse_client_id", "") or "").strip()
    client_secret = (getattr(config, "clms_cdse_client_secret", "") or "").strip()
    token_url = (
        getattr(config, "clms_cdse_token_url", "")
        or "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    ).strip()
    if not client_id or not client_secret:
        raise CLMSBurntAreaServiceError(
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
        raise CLMSBurntAreaServiceError(
            f"Failed to obtain CDSE token (status={resp.status_code})."
        )
    payload = resp.json() if resp.content else {}
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise CLMSBurntAreaServiceError(
            "CDSE token response does not contain access_token."
        )
    return token

def _dataset_candidates(version: str) -> list[DatasetCandidate]:
    v = str(version or "auto").strip().lower()
    if v not in {"auto", "v4_daily", "v3_daily", "v4_monthly"}:
        raise CLMSBurntAreaInputError(
            "dataset_version must be one of: auto, v4_daily, v3_daily, v4_monthly."
        )
    configured = {
        "v4_daily": (
            getattr(config, "clms_ba_v4_daily_collection_id", "")
            or DEFAULT_COLLECTIONS["v4_daily"]
        ).strip(),
        "v3_daily": (
            getattr(config, "clms_ba_v3_daily_collection_id", "")
            or DEFAULT_COLLECTIONS["v3_daily"]
        ).strip(),
        "v4_monthly": (
            getattr(config, "clms_ba_v4_monthly_collection_id", "")
            or DEFAULT_COLLECTIONS["v4_monthly"]
        ).strip(),
    }
    catalog = {
        "v4_daily": DatasetCandidate(
            key="v4_daily",
            collection_id=configured["v4_daily"],
            product_id="ba_global_300m_daily_v4",
            min_date=datetime(2025, 1, 1, tzinfo=timezone.utc).date(),
            max_date=None,
            uses_bf=True,
        ),
        "v3_daily": DatasetCandidate(
            key="v3_daily",
            collection_id=configured["v3_daily"],
            product_id="ba_global_300m_daily_v3.1",
            min_date=datetime(2023, 1, 1, tzinfo=timezone.utc).date(),
            max_date=None,
            uses_bf=False,
        ),
        "v4_monthly": DatasetCandidate(
            key="v4_monthly",
            collection_id=configured["v4_monthly"],
            product_id="ba_global_300m_monthly_v4",
            min_date=datetime(2018, 1, 1, tzinfo=timezone.utc).date(),
            max_date=None,
            uses_bf=True,
        ),
    }
    if v == "auto":
        return [catalog["v4_daily"], catalog["v3_daily"], catalog["v4_monthly"]]
    return [catalog[v]]

def _fetch_burn_raster(
    *,
    candidate: DatasetCandidate,
    geometry: Polygon | MultiPolygon,
    date_from: datetime.date,
    date_to: datetime.date,
    width: int,
    height: int,
    token: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    process_url = (
        getattr(config, "clms_sh_process_url", "")
        or "https://sh.dataspace.copernicus.eu/api/v1/process"
    ).strip()

    if candidate.uses_bf:
        evalscript = """
//VERSION=3
function setup() {
  return {
    input: ["BF", "DOB", "dataMask"],
    output: { bands: 3, sampleType: "INT16" }
  };
}
function evaluatePixel(sample) {
  return [sample.BF, sample.DOB, sample.dataMask];
}
""".strip()
    else:
        evalscript = """
//VERSION=3
function setup() {
  return {
    input: ["day_of_burn", "dataMask"],
    output: { bands: 2, sampleType: "INT16" }
  };
}
function evaluatePixel(sample) {
  return [sample.day_of_burn, sample.dataMask];
}
""".strip()

    body = {
        "input": {
            "bounds": {"geometry": mapping(geometry)},
            "data": [
                {
                    "type": f"byoc-{candidate.collection_id}",
                    "dataFilter": {
                        "timeRange": {
                            "from": f"{date_from.isoformat()}T00:00:00Z",
                            "to": f"{date_to.isoformat()}T23:59:59Z",
                        }
                    },
                }
            ],
        },
        "output": {"width": int(width), "height": int(height), "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
        "evalscript": evalscript,
    }
    resp = requests.post(
        process_url,
        json=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "image/tiff",
            "Content-Type": "application/json",
        },
        timeout=45,
    )
    if resp.status_code != 200:
        raise CLMSBurntAreaServiceError(
            f"Sentinel Hub request failed (status={resp.status_code}) for {candidate.key}."
        )

    with rasterio.open(io.BytesIO(resp.content)) as src:
        arr = src.read()
    if candidate.uses_bf:
        if arr.shape[0] < 3:
            raise CLMSBurntAreaServiceError(
                f"Unexpected raster band count for {candidate.key}; expected 3."
            )
        return arr[0], arr[2], arr[1]
    if arr.shape[0] < 2:
        raise CLMSBurntAreaServiceError(
            f"Unexpected raster band count for {candidate.key}; expected 2."
        )
    return arr[0], arr[1], None

def _analyze_burnt_area(
    *,
    burn_primary: np.ndarray,
    data_mask: np.ndarray,
    dob: np.ndarray | None,
    polygon: Polygon | MultiPolygon,
    bounds: tuple[float, float, float, float],
    uses_bf: bool,
    min_burn_fraction: float,
) -> dict[str, Any]:
    h, w = burn_primary.shape
    transform = from_bounds(*bounds, width=w, height=h)
    aoi_mask = geometry_mask([mapping(polygon)], transform=transform, invert=True, out_shape=(h, w))
    valid_mask = (data_mask > 0) & aoi_mask
    valid_count = int(np.count_nonzero(valid_mask))
    if valid_count == 0:
        raise CLMSBurntAreaNoDataError("No valid pixels returned for this AOI.")

    primary_values = burn_primary[valid_mask]
    if uses_bf:
        burnt_mask = primary_values >= int(round(min_burn_fraction * 1000.0))
        mean_bf = float(np.mean(primary_values) / 1000.0) if primary_values.size else 0.0
    else:
        burnt_mask = primary_values > 0
        mean_bf = None

    burnt_count = int(np.count_nonzero(burnt_mask))
    burnt_ratio = float(burnt_count / valid_count) if valid_count else 0.0

    min_dob = None
    max_dob = None
    if dob is not None:
        dob_values = dob[valid_mask]
        positive = dob_values[dob_values > 0]
        if positive.size > 0:
            min_dob = int(np.min(positive))
            max_dob = int(np.max(positive))

    return {
        "valid_pixels": valid_count,
        "burnt_pixels": burnt_count,
        "burnt_ratio": round(burnt_ratio, 6),
        "mean_burn_fraction": round(mean_bf, 6) if mean_bf is not None else None,
        "min_day_of_burn": min_dob,
        "max_day_of_burn": max_dob,
    }

def _risk_band(burnt_ratio: float) -> str:
    if burnt_ratio >= 0.20:
        return "high"
    if burnt_ratio >= 0.05:
        return "moderate"
    return "low"

def clms_burnt_area_impact_tool(
    *,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    polygon_wkt: str | None = None,
    radius_km: float = 50.0,
    location_token: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    dataset_version: str = "auto",
    min_burn_fraction: float = 0.05,
    return_map: bool = True,
) -> ToolResponse:
    """
    Compute CLMS burnt-area impact metrics over an AOI.

    Location input (exactly one):
    - polygon_wkt, OR
    - lat+lon (+radius_km), OR
    - location (optionally disambiguated with location_token)
    """
    try:
        radius_f = _require_range("radius_km", float(radius_km), 0.1, 500.0)
        min_burn_fraction_f = _require_range(
            "min_burn_fraction", float(min_burn_fraction), 0.0, 1.0
        )
        date_from, date_to = _resolve_date_range(start_date, end_date)
        aoi = _resolve_aoi(
            location=location,
            lat=lat,
            lon=lon,
            polygon_wkt=polygon_wkt,
            radius_km=radius_f,
            location_token=location_token,
        )
        bounds = aoi.geometry.bounds
        area_m2 = _estimate_bbox_area_m2(bounds)
        width, height, eff_res_m = _compute_dimensions(
            bounds,
            target_res_m=300.0,
            max_pixels=int(getattr(config, "clms_max_pixels", 4_000_000) or 4_000_000),
        )
        token = _oauth_token()

        candidates = _dataset_candidates(dataset_version)
        candidate_notes: list[str] = []
        selected_candidate: DatasetCandidate | None = None
        metrics: dict[str, Any] | None = None
        for candidate in candidates:
            if date_to < candidate.min_date:
                candidate_notes.append(
                    f"Skipped {candidate.key}: requested period is earlier than dataset coverage."
                )
                continue
            if candidate.max_date is not None and date_from > candidate.max_date:
                candidate_notes.append(
                    f"Skipped {candidate.key}: requested period is later than dataset coverage."
                )
                continue
            try:
                burn_primary, data_mask, dob = _fetch_burn_raster(
                    candidate=candidate,
                    geometry=aoi.geometry,
                    date_from=max(date_from, candidate.min_date),
                    date_to=date_to,
                    width=width,
                    height=height,
                    token=token,
                )
                metrics = _analyze_burnt_area(
                    burn_primary=burn_primary,
                    data_mask=data_mask,
                    dob=dob,
                    polygon=aoi.geometry,
                    bounds=bounds,
                    uses_bf=candidate.uses_bf,
                    min_burn_fraction=min_burn_fraction_f,
                )
                selected_candidate = candidate
                break
            except CLMSBurntAreaNoDataError:
                candidate_notes.append(
                    f"{candidate.key} returned no valid AOI pixels for this query window."
                )
                continue

        if selected_candidate is None or metrics is None:
            raise CLMSBurntAreaServiceError(
                "No valid burnt-area pixels returned across attempted CLMS datasets."
            )

        pixel_area_m2 = area_m2 / max(1.0, float(width * height))
        burnt_area_km2 = (
            float(metrics["burnt_pixels"]) * pixel_area_m2 / 1_000_000.0
            if metrics["burnt_pixels"] > 0
            else 0.0
        )
        impact = {
            "burnt_area_km2_est": round(burnt_area_km2, 4),
            "burnt_area_pct": round(float(metrics["burnt_ratio"]) * 100.0, 3),
            "risk_band": _risk_band(float(metrics["burnt_ratio"])),
        }

        quality_notes = list(aoi.quality_notes)
        quality_notes.extend(candidate_notes)
        quality_notes.extend(
            [
                "Burnt area is EO-derived context information and can be revised over time.",
                "Point+radius mode approximates a circular query by a bounding box AOI.",
            ]
        )
        if selected_candidate.key != "v4_daily":
            quality_notes.append(
                f"Requested window required fallback to {selected_candidate.key}."
            )

        msg = (
            f"CLMS burnt-area impact for {aoi.location_name or 'AOI'} "
            f"({date_from.isoformat()} to {date_to.isoformat()}): "
            f"burnt_area={impact['burnt_area_km2_est']} km², "
            f"burnt_pct={impact['burnt_area_pct']}%, "
            f"risk_band={impact['risk_band']}."
        )

        coords = ToolCoordinates(lat=float(aoi.center_lat), lon=float(aoi.center_lon))
        maps = []
        if return_map:
            maps.append(
                {
                    "title": "CLMS burnt area impact AOI",
                    "view_state": view_state_from_bbox(
                        coords, padding=0.12, min_zoom=4.0, max_zoom=11.0
                    ),
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
                                            "burnt_area_km2": impact["burnt_area_km2_est"],
                                            "burnt_area_pct": impact["burnt_area_pct"],
                                            "risk_band": impact["risk_band"],
                                        },
                                    }
                                ],
                            },
                            "stroked": True,
                            "filled": True,
                            "get_fill_color": [255, 99, 71, 70],
                            "get_line_color": [255, 69, 0, 200],
                            "line_width_min_pixels": 1,
                            "pickable": True,
                        }
                    ],
                    "tooltip": {
                        "text": "Burnt area: {burnt_area_km2} km²\nBurnt pct: {burnt_area_pct}%\nRisk: {risk_band}"
                    },
                }
            )

        return ToolResponse(
            tool_name="clms_burnt_area_impact_tool",
            message=msg,
            city=aoi.location_name,
            coordinates=coords,
            artifacts=ToolArtifacts(maps=maps, thumbnails=[], urls=[]),
            data={
                "source": {
                    "service": "CLMS",
                    "dataset_identifier": selected_candidate.product_id,
                    "dataset_key": selected_candidate.key,
                    "collection_id": selected_candidate.collection_id,
                    "date_from_used": date_from.isoformat(),
                    "date_to_used": date_to.isoformat(),
                },
                "aoi": {
                    "input_mode": aoi.mode,
                    "lat": float(aoi.center_lat),
                    "lon": float(aoi.center_lon),
                    "radius_km": aoi.radius_km,
                    "area_m2_est": round(area_m2, 2),
                    "bounds_wgs84": [float(x) for x in bounds],
                },
                "pixel_stats": metrics,
                "impact": impact,
                "processing": {
                    "dataset_version_requested": dataset_version,
                    "effective_resolution_m": round(eff_res_m, 2),
                    "raster_width": int(width),
                    "raster_height": int(height),
                    "max_pixels": int(getattr(config, "clms_max_pixels", 4_000_000) or 4_000_000),
                },
                "quality_notes": quality_notes,
            },
            error=False,
        )

    except CLMSBurntAreaInputError as exc:
        return ToolResponse(
            tool_name="clms_burnt_area_impact_tool",
            message=str(exc),
            error=True,
        )
    except CLMSBurntAreaServiceError as exc:
        logger.error("CLMS burnt-area tool service error: %s", exc)
        return ToolResponse(
            tool_name="clms_burnt_area_impact_tool",
            message=str(exc),
            error=True,
        )
    except Exception as exc:
        logger.error("Unexpected CLMS burnt-area tool error: %s", exc, exc_info=True)
        return ToolResponse(
            tool_name="clms_burnt_area_impact_tool",
            message=f"Unexpected error in clms_burnt_area_impact_tool: {exc}",
            error=True,
        )

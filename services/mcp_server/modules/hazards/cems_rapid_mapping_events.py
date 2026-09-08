"""
CEMS Rapid Mapping events tool.

Queries Copernicus EMS Rapid Mapping public APIs and returns activation
metadata, AOIs, products, layers, and damage/exposure stats.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests
from shapely import wkt as shapely_wkt
from shapely.geometry import MultiPolygon, Polygon, mapping

from core.logger import get_logger
from utils.bbox_service import get_city_candidates
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from utils.map_view_service import view_state_from_bbox

logger = get_logger(__name__)

PUBLIC_ACTIVATIONS_INFO_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations-info/"
)
PUBLIC_ACTIVATIONS_DETAIL_URL = (
    "https://rapidmapping.emergency.copernicus.eu/backend/dashboard-api/public-activations/"
)

class CEMSInputError(ValueError):
    pass

class CEMSServiceError(RuntimeError):
    pass

@dataclass(frozen=True)
class AOIContext:
    geometry: Polygon | MultiPolygon
    mode: str
    center_lat: float
    center_lon: float
    location_name: str | None
    country_hint: str | None
    quality_notes: list[str]

def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None

def _require_range(name: str, value: float, lo: float, hi: float) -> float:
    if not (lo <= value <= hi):
        raise CEMSInputError(f"'{name}' must be between {lo} and {hi}.")
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

def _parse_iso_date(text: str | None, field_name: str) -> datetime | None:
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception as exc:
        raise CEMSInputError(
            f"Invalid '{field_name}' format. Use ISO date or datetime."
        ) from exc

def _resolve_location_to_aoi(
    location: str,
    *,
    location_token: str | None,
    radius_km: float,
) -> AOIContext:
    query = (
        location_token.strip()
        if isinstance(location_token, str) and location_token.strip()
        else location.strip()
    )
    candidates = get_city_candidates(query, limit=5)
    if not candidates:
        raise CEMSInputError(
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
        raise CEMSInputError(
            "Location is ambiguous. Confirm with 'location_token' using "
            "'@place_id:<id>' or '@osm_id:<R|W|N><id>'. "
            f"Candidates: {preview}"
        )
    else:
        chosen = candidates[0]

    lat = _safe_float(chosen.get("lat"))
    lon = _safe_float(chosen.get("lon"))
    if lat is None or lon is None:
        raise CEMSInputError("Resolved location candidate has invalid coordinates.")

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

    display_name = str(chosen.get("display_name") or location)
    country_hint = display_name.split(",")[-1].strip() if "," in display_name else None
    return AOIContext(
        geometry=geom,
        mode="location",
        center_lat=float(lat),
        center_lon=float(lon),
        location_name=display_name,
        country_hint=country_hint,
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
            raise CEMSInputError(f"Invalid polygon_wkt: {exc}") from exc
        if not isinstance(geom, (Polygon, MultiPolygon)):
            raise CEMSInputError("polygon_wkt must be a Polygon or MultiPolygon.")
        if not geom.is_valid:
            geom = geom.buffer(0)
        if geom.is_empty:
            raise CEMSInputError("polygon_wkt produced an empty geometry.")
        center = geom.centroid
        return AOIContext(
            geometry=geom,
            mode="polygon",
            center_lat=float(center.y),
            center_lon=float(center.x),
            location_name=None,
            country_hint=None,
            quality_notes=[],
        )

    if lat is not None and lon is not None:
        lat_f = _require_range("lat", float(lat), -90.0, 90.0)
        lon_f = _require_range("lon", float(lon), -180.0, 180.0)
        geom = _point_radius_bbox_polygon(lat_f, lon_f, radius_km=radius_km)
        return AOIContext(
            geometry=geom,
            mode="point_radius",
            center_lat=lat_f,
            center_lon=lon_f,
            location_name=f"{lat_f:.5f}, {lon_f:.5f}",
            country_hint=None,
            quality_notes=["Point+radius AOI is converted to a bounding box approximation."],
        )

    if lat is not None or lon is not None:
        raise CEMSInputError(
            "Provide both lat and lon together, or omit both to use location/polygon_wkt."
        )

    if isinstance(location, str) and location.strip():
        return _resolve_location_to_aoi(
            location=location, location_token=location_token, radius_km=radius_km
        )

    raise CEMSInputError("Unable to resolve AOI from provided inputs.")

def _fetch_json(url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
    resp = requests.get(url, params=params, timeout=25)
    if resp.status_code != 200:
        raise CEMSServiceError(
            f"CEMS API request failed (status={resp.status_code}) for {url}."
        )
    payload = resp.json()
    if not isinstance(payload, dict):
        raise CEMSServiceError("CEMS API response is not a JSON object.")
    return payload

def _fetch_activation_info_pages(*, max_pages: int = 12, page_size: int = 50) -> list[dict[str, Any]]:
    all_results: list[dict[str, Any]] = []
    offset = 0
    for _ in range(max_pages):
        payload = _fetch_json(
            PUBLIC_ACTIVATIONS_INFO_URL, params={"limit": page_size, "offset": offset}
        )
        rows = payload.get("results")
        if not isinstance(rows, list) or not rows:
            break
        all_results.extend([r for r in rows if isinstance(r, dict)])
        if payload.get("next") is None:
            break
        offset += page_size
    return all_results

def _fetch_activation_detail(code: str) -> dict[str, Any] | None:
    payload = _fetch_json(PUBLIC_ACTIVATIONS_DETAIL_URL, params={"code": code})
    results = payload.get("results")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return None

def _parse_wkt_geometry(text: Any) -> Polygon | MultiPolygon | None:
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        geom = shapely_wkt.loads(text)
        if isinstance(geom, (Polygon, MultiPolygon)) and not geom.is_empty:
            return geom
    except Exception:
        return None
    return None

def _normalize_hazards(hazard_types: list[str] | None) -> list[str]:
    if not hazard_types:
        return []
    out: list[str] = []
    for h in hazard_types:
        key = str(h or "").strip().lower()
        if key and key not in out:
            out.append(key)
    return out

def _passes_hazard_filter(detail: dict[str, Any], hazards: list[str]) -> bool:
    if not hazards:
        return True
    category = str(detail.get("category") or "").lower()
    sub_category = str(detail.get("subCategory") or "").lower()
    haystack = f"{category} {sub_category}"
    return any(h in haystack for h in hazards)

def _passes_date_filter(detail: dict[str, Any], start_dt: datetime | None, end_dt: datetime | None) -> bool:
    if start_dt is None and end_dt is None:
        return True
    event_time = detail.get("eventTime") or detail.get("activationTime")
    if not isinstance(event_time, str) or not event_time.strip():
        return False
    try:
        event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
    except Exception:
        return False
    if start_dt is not None and event_dt < start_dt:
        return False
    if end_dt is not None and event_dt > end_dt:
        return False
    return True

def _extract_countries(detail: dict[str, Any]) -> list[str]:
    countries = detail.get("countries")
    out: list[str] = []
    if isinstance(countries, list):
        for c in countries:
            if isinstance(c, dict):
                name = str(c.get("name") or "").strip()
            else:
                name = str(c or "").strip()
            if name and name not in out:
                out.append(name)
    return out

def _match_geometry_or_metadata(
    *,
    detail: dict[str, Any],
    query_geom: Polygon | MultiPolygon,
    location_text: str | None,
    country_hint: str | None,
) -> tuple[bool, str, list[dict[str, Any]], Polygon | MultiPolygon | None]:
    activation_geom = _parse_wkt_geometry(detail.get("extent"))
    aoi_hits: list[dict[str, Any]] = []
    if activation_geom is not None and query_geom.intersects(activation_geom):
        aois = detail.get("aois")
        if isinstance(aois, list):
            for aoi in aois:
                if not isinstance(aoi, dict):
                    continue
                geom = _parse_wkt_geometry(aoi.get("extent"))
                if geom is None or not query_geom.intersects(geom):
                    continue
                aoi_hits.append(aoi)
        return True, "geometry_intersection", aoi_hits, activation_geom

    # Fallback matching when geometry is absent or non-intersecting
    countries = [c.lower() for c in _extract_countries(detail)]
    name = str(detail.get("name") or "").lower()
    reason = str(detail.get("reason") or "").lower()
    loc = str(location_text or "").strip().lower()
    if loc and (loc in name or loc in reason):
        return True, "metadata_fallback", [], activation_geom
    if country_hint and country_hint.lower() in countries:
        return True, "metadata_fallback", [], activation_geom
    return False, "none", [], activation_geom

def _summarize_products(aois: list[dict[str, Any]]) -> tuple[dict[str, int], int]:
    by_type: dict[str, int] = {"REF": 0, "DEL": 0, "GRA": 0}
    total = 0
    for aoi in aois:
        products = aoi.get("products")
        if not isinstance(products, list):
            continue
        for p in products:
            if not isinstance(p, dict):
                continue
            total += 1
            ptype = str(p.get("type") or "").upper()
            if ptype in by_type:
                by_type[ptype] += 1
    return by_type, total

def cems_rapid_mapping_events_tool(
    *,
    location: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    polygon_wkt: str | None = None,
    radius_km: float | None = 50,
    location_token: str | None = None,
    hazard_types: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    only_active: bool = False,
    limit: int = 20,
) -> ToolResponse:
    """Query CEMS Rapid Mapping activations with spatial and metadata filters.
    
    Examples:
        - Quelles evenements (flood ou wildfire) ont eu lieu autour d'Athènes entre 2022-01-01 et 2026-12-31 ?
    """
    try:
        radius = max(1.0, min(300.0, float(radius_km if radius_km is not None else 50.0)))
        max_results = max(1, min(100, int(limit)))
        start_dt = _parse_iso_date(start_date, "start_date")
        end_dt = _parse_iso_date(end_date, "end_date")
        if start_dt and end_dt and end_dt < start_dt:
            raise CEMSInputError("'end_date' must be >= 'start_date'.")

        aoi = _resolve_aoi(
            location=location,
            lat=lat,
            lon=lon,
            polygon_wkt=polygon_wkt,
            radius_km=radius,
            location_token=location_token,
        )
        hazards = _normalize_hazards(hazard_types)
        info_rows = _fetch_activation_info_pages()
        if not info_rows:
            return ToolResponse(
                tool_name="cems_rapid_mapping_events_tool",
                message="No CEMS rapid mapping activation metadata available.",
                error=False,
                data={"activations": []},
            )

        candidates = sorted(
            info_rows, key=lambda r: str(r.get("activationTime") or ""), reverse=True
        )
        matches: list[dict[str, Any]] = []
        map_features: list[dict[str, Any]] = []
        for row in candidates:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            detail = _fetch_activation_detail(code)
            if not detail:
                continue
            if only_active and bool(detail.get("closed")):
                continue
            if not _passes_hazard_filter(detail, hazards):
                continue
            if not _passes_date_filter(detail, start_dt, end_dt):
                continue

            matched, match_mode, aoi_hits, activation_geom = _match_geometry_or_metadata(
                detail=detail,
                query_geom=aoi.geometry,
                location_text=location or aoi.location_name,
                country_hint=aoi.country_hint,
            )
            if not matched:
                continue

            aois = detail.get("aois") if isinstance(detail.get("aois"), list) else []
            selected_aois = aoi_hits if aoi_hits else [x for x in aois if isinstance(x, dict)]
            product_type_counts, product_total = _summarize_products(selected_aois)
            countries = _extract_countries(detail)
            activation_entry = {
                "code": code,
                "name": detail.get("name"),
                "category": detail.get("category"),
                "sub_category": detail.get("subCategory"),
                "closed": bool(detail.get("closed")),
                "event_time": detail.get("eventTime"),
                "activation_time": detail.get("activationTime"),
                "countries": countries,
                "centroid_wkt": detail.get("centroid"),
                "extent_wkt": detail.get("extent"),
                "n_aois": detail.get("n_aois") or len(aois),
                "n_products": detail.get("n_products") or product_total,
                "report_link": detail.get("reportLink"),
                "products_path": detail.get("productsPath"),
                "match_mode": match_mode,
                "product_type_counts": product_type_counts,
                "aois": [
                    {
                        "name": aoi_row.get("name"),
                        "number": aoi_row.get("number"),
                        "extent_wkt": aoi_row.get("extent"),
                        "blp_path": aoi_row.get("blpPath"),
                        "products": [
                            {
                                "id": p.get("id"),
                                "type": p.get("type"),
                                "feasible": p.get("feasible"),
                                "status_code": (p.get("version") or {}).get("statusCode")
                                if isinstance(p.get("version"), dict)
                                else None,
                                "expected_delivery": p.get("expectedDelivery"),
                                "delivery_time": (p.get("version") or {}).get("deliveryTime")
                                if isinstance(p.get("version"), dict)
                                else None,
                                "download_path": p.get("downloadPath"),
                                "layers": p.get("layers") if isinstance(p.get("layers"), list) else [],
                                "stats": p.get("stats"),
                            }
                            for p in (aoi_row.get("products") or [])
                            if isinstance(p, dict)
                        ],
                    }
                    for aoi_row in selected_aois
                ],
                "stats": detail.get("stats"),
            }
            matches.append(activation_entry)

            if activation_geom is not None:
                map_features.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(activation_geom),
                        "properties": {
                            "code": code,
                            "category": activation_entry["category"],
                            "closed": activation_entry["closed"],
                            "match_mode": match_mode,
                        },
                    }
                )
            if len(matches) >= max_results:
                break

        coords = ToolCoordinates(lat=float(aoi.center_lat), lon=float(aoi.center_lon))
        if not matches:
            return ToolResponse(
                tool_name="cems_rapid_mapping_events_tool",
                message="No CEMS rapid mapping activations matched the provided filters.",
                coordinates=coords,
                data={
                    "activations": [],
                    "applied_filters": {
                        "hazard_types": hazards,
                        "start_date": start_date,
                        "end_date": end_date,
                        "only_active": bool(only_active),
                        "limit": max_results,
                    },
                    "quality_notes": aoi.quality_notes,
                },
                error=False,
            )

        bounds = aoi.geometry.bounds
        view_state = view_state_from_bbox(coords, padding=0.18, min_zoom=3.0, max_zoom=10.0)
        maps = [
            {
                "title": "CEMS rapid mapping activations",
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
                                    "properties": {"kind": "query_aoi"},
                                },
                                *map_features,
                            ],
                        },
                        "stroked": True,
                        "filled": True,
                        "get_fill_color": [220, 20, 60, 60],
                        "get_line_color": [220, 20, 60, 200],
                        "line_width_min_pixels": 1,
                        "pickable": True,
                    }
                ],
                "tooltip": {"text": "{code} ({category})\nClosed: {closed}\nMatch: {match_mode}"},
            }
        ]

        msg = (
            f"Found {len(matches)} CEMS rapid-mapping activation(s) "
            f"for {aoi.location_name or 'AOI'}."
        )
        return ToolResponse(
            tool_name="cems_rapid_mapping_events_tool",
            message=msg,
            city=aoi.location_name,
            coordinates=coords,
            artifacts=ToolArtifacts(maps=maps, thumbnails=[], urls=[]),
            data={
                "source": {
                    "service": "CEMS Rapid Mapping",
                    "list_endpoint": PUBLIC_ACTIVATIONS_INFO_URL,
                    "detail_endpoint": PUBLIC_ACTIVATIONS_DETAIL_URL,
                },
                "aoi": {
                    "input_mode": aoi.mode,
                    "lat": float(aoi.center_lat),
                    "lon": float(aoi.center_lon),
                    "bounds_wgs84": [float(x) for x in bounds],
                },
                "applied_filters": {
                    "hazard_types": hazards,
                    "start_date": start_date,
                    "end_date": end_date,
                    "only_active": bool(only_active),
                    "limit": max_results,
                },
                "activations": matches,
                "quality_notes": aoi.quality_notes,
            },
            error=False,
        )
    except CEMSInputError as exc:
        return ToolResponse(
            tool_name="cems_rapid_mapping_events_tool",
            message=str(exc),
            error=True,
        )
    except CEMSServiceError as exc:
        logger.error("CEMS rapid-mapping tool service error: %s", exc)
        return ToolResponse(
            tool_name="cems_rapid_mapping_events_tool",
            message=str(exc),
            error=True,
        )
    except Exception as exc:
        logger.error("Unexpected CEMS rapid-mapping tool error: %s", exc, exc_info=True)
        return ToolResponse(
            tool_name="cems_rapid_mapping_events_tool",
            message=f"Unexpected error in cems_rapid_mapping_events_tool: {exc}",
            error=True,
        )

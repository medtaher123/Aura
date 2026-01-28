"""GEOGLOWS v2 Streamflow Forecast Tool.

Provides river discharge forecasts and flood risk analysis using the GEOGLOWS ECMWF
global streamflow forecasting system.
"""

from typing import Optional
from datetime import datetime
from functools import lru_cache
from mcp_singleton import mcp
import requests
import numpy as np
import s3fs
import xarray as xr


from utils.contracts import make_tool_response

from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.map_view_service import view_state_from_points

RETRO_RETURN_PERIODS_ZARR = "s3://geoglows-v2/retrospective/return-periods.zarr"
FORECASTS_BUCKET = "geoglows-v2-forecasts"

# Hydroviewer uses an ArcGIS map service for interactive feature identification.
# We can use the same service to infer a GEOGLOWS reach_id (LINKNO / river_id)
# from a lat/lon point.
GEOGLOWS_ARCGIS_LAYER0 = (
    "https://livefeeds3.arcgis.com/arcgis/rest/services/GEOGLOWS/"
    "GlobalWaterModel_Medium/MapServer/0"
)

GEOGLOWS_ARCGIS_QUERY = (
    "https://livefeeds3.arcgis.com/arcgis/rest/services/GEOGLOWS/"
    "GlobalWaterModel_Medium/MapServer/0/query"
)

_REACH_ID_KEYS = (
    "Terminal TDX Hydro Link Number",
    "TDX Hydro Link Number",
    "LINKNO",
    "linkno",
    "river_id",
    "RIVID",
    "rivid",
    "COMID",
    "comid",
    "reach_id",
    "outletcomid",
    "outletCOMID",
)


def _coerce_reach_id(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        if not v or v.lower() in {"null", "none", "nan"}:
            return None
        v = v.replace(",", "")
        try:
            return int(v)
        except Exception:
            return None
    try:
        return int(value)
    except Exception:
        return None


def _extract_reach_id_from_attrs(attrs: object) -> Optional[int]:
    if not isinstance(attrs, dict):
        return None
    for key in _REACH_ID_KEYS:
        if key in attrs:
            rid = _coerce_reach_id(attrs.get(key))
            if rid is not None and rid > 0:
                return rid
    return None


@lru_cache(maxsize=1)
def _get_arcgis_service_wkid() -> int:
    """Best-effort: get the MapServer spatial reference WKID.

    ArcGIS identify expects `mapExtent` in the service/map spatial reference.
    If we provide a WGS84 bbox to a WebMercator service, it can identify the
    wrong feature near dense networks.
    """
    try:
        base = GEOGLOWS_ARCGIS_LAYER0.rsplit("/", 1)[0]
        resp = requests.get(base, params={"f": "json"}, timeout=10)
        if resp.status_code != 200:
            return 4326
        payload = resp.json() if resp.content else {}
        sr = payload.get("spatialReference") if isinstance(payload, dict) else None
        if isinstance(sr, dict):
            wkid = sr.get("latestWkid") or sr.get("wkid")
            if isinstance(wkid, int) and wkid > 0:
                return wkid
    except Exception:
        pass
    return 4326


def _lonlat_to_webmercator(lon: float, lat: float) -> tuple[float, float]:
    """Convert lon/lat WGS84 to WebMercator meters (EPSG:3857/102100)."""
    # Clamp latitude to valid WebMercator range
    lat = max(min(lat, 85.05112878), -85.05112878)
    origin_shift = 20037508.342789244
    x = (lon * origin_shift) / 180.0
    import math

    y = math.log(math.tan((90.0 + lat) * math.pi / 360.0)) / (math.pi / 180.0)
    y = (y * origin_shift) / 180.0
    return x, y


def _webmercator_to_lonlat(x: float, y: float) -> tuple[float, float]:
    """Convert WebMercator meters (EPSG:3857/102100) to lon/lat WGS84."""
    origin_shift = 20037508.342789244
    lon = (x / origin_shift) * 180.0
    import math

    lat = (y / origin_shift) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return lon, lat


def _esri_polyline_to_geojson(geom: object) -> Optional[dict]:
    """Convert an ArcGIS polyline geometry (esriJSON) into a GeoJSON FeatureCollection."""
    if not isinstance(geom, dict):
        return None
    paths = geom.get("paths")
    if not isinstance(paths, list) or not paths:
        return None

    # Some ArcGIS services return geometry in WebMercator even if outSR is provided.
    # Detect SR and convert to lon/lat when needed.
    sr = geom.get("spatialReference")
    wkid = None
    if isinstance(sr, dict):
        wkid = sr.get("latestWkid") or sr.get("wkid")
    is_webmercator = wkid in {3857, 102100}

    lines: list[list[list[float]]] = []
    for path in paths:
        if not isinstance(path, list) or len(path) < 2:
            continue
        coords: list[list[float]] = []
        for pt in path:
            if not isinstance(pt, (list, tuple)) or len(pt) < 2:
                continue
            try:
                x = float(pt[0])
                y = float(pt[1])
            except Exception:
                continue
            if is_webmercator:
                lon, lat = _webmercator_to_lonlat(x, y)
                coords.append([lon, lat])
            else:
                # ArcGIS geometry is typically [x,y] = [lon,lat] in wkid=4326.
                coords.append([x, y])
        if len(coords) >= 2:
            lines.append(coords)

    if not lines:
        return None

    geometry: dict
    if len(lines) == 1:
        geometry = {"type": "LineString", "coordinates": lines[0]}
    else:
        geometry = {"type": "MultiLineString", "coordinates": lines}

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": geometry,
            }
        ],
    }


def _point_to_segment_distance(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
    import math

    vx = x2 - x1
    vy = y2 - y1
    if vx == 0 and vy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * vx + (py - y1) * vy) / (vx * vx + vy * vy)
    if t < 0:
        t = 0.0
    elif t > 1:
        t = 1.0
    projx = x1 + t * vx
    projy = y1 + t * vy
    return math.hypot(px - projx, py - projy)


def _min_distance_to_paths(px: float, py: float, paths: object) -> Optional[float]:
    import math

    if not isinstance(paths, list):
        return None
    best = None
    for path in paths:
        if not isinstance(path, list) or len(path) < 2:
            continue
        for i in range(len(path) - 1):
            p1 = path[i]
            p2 = path[i + 1]
            if not isinstance(p1, (list, tuple)) or not isinstance(p2, (list, tuple)):
                continue
            if len(p1) < 2 or len(p2) < 2:
                continue
            try:
                x1 = float(p1[0])
                y1 = float(p1[1])
                x2 = float(p2[0])
                y2 = float(p2[1])
            except Exception:
                continue
            dist = _point_to_segment_distance(px, py, x1, y1, x2, y2)
            if best is None or dist < best:
                best = dist
    return best


def _query_geoglows_nearest_feature(
    lat: float, lon: float, *, return_geometry: bool = False
) -> tuple[Optional[int], Optional[dict]]:
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None, None

    cx, cy = _lonlat_to_webmercator(lon_f, lat_f)
    headers = {"User-Agent": "metaplanet-llm-streamflow"}

    best: tuple[float, int, Optional[dict]] | None = None
    for dist in (1000, 2000, 5000, 10000, 20000):
        params = {
            "f": "json",
            "geometry": f"{cx},{cy}",
            "geometryType": "esriGeometryPoint",
            "inSR": 3857,
            "spatialRel": "esriSpatialRelIntersects",
            "distance": dist,
            "units": "esriSRUnit_Meter",
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": 3857,
        }
        try:
            resp = requests.get(GEOGLOWS_ARCGIS_QUERY, params=params, headers=headers, timeout=15)
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        payload = resp.json() if resp.content else {}
        features = payload.get("features") if isinstance(payload, dict) else None
        if not isinstance(features, list) or not features:
            continue

        for feature in features:
            if not isinstance(feature, dict):
                continue
            attrs = feature.get("attributes")
            reach_id = _extract_reach_id_from_attrs(attrs)
            if reach_id is None:
                continue
            geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
            if isinstance(geometry, dict) and "spatialReference" not in geometry:
                geometry["spatialReference"] = {"wkid": 3857}
            paths = geometry.get("paths") if isinstance(geometry, dict) else None
            distance = _min_distance_to_paths(cx, cy, paths)
            if distance is None:
                continue
            if best is None or distance < best[0]:
                best = (distance, reach_id, geometry)

        if best is not None:
            break

    if best is None:
        return None, None

    _, reach_id, geometry = best
    geojson = None
    if return_geometry and isinstance(geometry, dict):
        geojson = _esri_polyline_to_geojson(geometry)
        if isinstance(geojson, dict):
            try:
                geojson["features"][0]["properties"] = {"river_id": reach_id, "reach_id": reach_id}
            except Exception:
                pass
    return reach_id, geojson


def _identify_geoglows_river_feature(
    lat: float, lon: float, *, return_geometry: bool = False
) -> tuple[Optional[int], Optional[dict]]:
    """Identify nearest GEOGLOWS river feature at a point.

    Returns:
      (reach_id, geojson_feature_collection)
    """
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None, None

    # Identify needs `mapExtent` in the MapServer spatial reference.
    wkid = _get_arcgis_service_wkid()
    if wkid in {3857, 102100}:
        cx, cy = _lonlat_to_webmercator(lon_f, lat_f)
        pad_m = 8000.0
        map_extent = f"{cx - pad_m},{cy - pad_m},{cx + pad_m},{cy + pad_m}"
        geometry = f"{cx},{cy}"
        geom_sr = wkid
    else:
        # Small bbox around the point for identify to work without a real map view.
        pad = 0.05
        map_extent = f"{lon_f - pad},{lat_f - pad},{lon_f + pad},{lat_f + pad}"
        geometry = f"{lon_f},{lat_f}"
        geom_sr = 4326

    identify_url = GEOGLOWS_ARCGIS_LAYER0.rsplit("/", 1)[0] + "/identify"
    params = {
        "f": "json",
        "geometry": geometry,
        "geometryType": "esriGeometryPoint",
        # Spatial reference of the input geometry (lon/lat).
        "sr": geom_sr,
        # Force output geometry in lon/lat so the overlay aligns with the basemap.
        "outSR": 4326,
        "layers": "all:0",
        "tolerance": 10,
        "mapExtent": map_extent,
        "imageDisplay": "800,600,96",
        "returnGeometry": "true" if return_geometry else "false",
    }

    headers = {"User-Agent": "metaplanet-llm-streamflow"}
    try:
        resp = requests.get(identify_url, params=params, headers=headers, timeout=15)
    except Exception:
        return None, None
    if resp.status_code != 200:
        return None, None

    payload = resp.json() if resp.content else {}
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or not results:
        return _query_geoglows_nearest_feature(lat_f, lon_f, return_geometry=return_geometry)

    first = results[0] if isinstance(results[0], dict) else {}
    attrs = first.get("attributes") if isinstance(first, dict) else None
    if not isinstance(attrs, dict):
        return _query_geoglows_nearest_feature(lat_f, lon_f, return_geometry=return_geometry)

    reach_id = _extract_reach_id_from_attrs(attrs)
    if reach_id is None:
        return _query_geoglows_nearest_feature(lat_f, lon_f, return_geometry=return_geometry)

    geojson = None
    if return_geometry:
        geojson = _esri_polyline_to_geojson(first.get("geometry"))
        if isinstance(geojson, dict):
            try:
                geojson["features"][0]["properties"] = {"river_id": reach_id, "reach_id": reach_id}
            except Exception:
                pass

    return reach_id, geojson


def _find_reach_for_river(lat: float, lon: float) -> Optional[int]:
    """Infer a GEOGLOWS reach_id (LINKNO / river_id) from a lat/lon point.

    Strategy:
    - Use the ArcGIS MapServer layer referenced by the GEOGLOWS Hydroviewer.
    - Call its `/identify` endpoint around the given point and extract the
      reach identifier from returned feature attributes.

    Notes:
    - This is a best-effort "snap to nearest river". It can be wrong near
      confluences, deltas, or if the input point is far from the modeled river.
    - If the service is unavailable or returns no features, returns None.
    """
    rid, _ = _identify_geoglows_river_feature(lat, lon, return_geometry=False)
    return rid


@lru_cache(maxsize=3)
def _get_s3fs() -> s3fs.S3FileSystem:
    return s3fs.S3FileSystem(anon=True)


def _find_latest_forecast_zarr_uri() -> Optional[str]:
    fs = _get_s3fs()
    try:
        entries = fs.ls(FORECASTS_BUCKET)
    except Exception:
        entries = []

    if not entries:
        return None

    matches = [e for e in entries if str(e).endswith(".zarr")]
    if not matches:
        return None

    # Prefer latest lexicographic path (usually date-suffixed folders)
    latest = sorted(matches)[-1]
    return f"s3://{latest}"


def _find_river_coord(ds: xr.Dataset) -> Optional[str]:
    candidates = ["river_id", "rivid", "comid", "linkno", "link_id", "reach_id"]
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    return None


def _open_zarr(uri: str) -> xr.Dataset:
    return xr.open_dataset(uri, engine="zarr", storage_options={"anon": True})


@lru_cache(maxsize=3)
def _get_return_periods_dataset() -> xr.Dataset:
    return _open_zarr(RETRO_RETURN_PERIODS_ZARR)


def _river_id_exists(reach_id: int) -> bool:
    try:
        ds = _get_return_periods_dataset()
        river_coord = _find_river_coord(ds)
        if not river_coord:
            return False
        ds.sel({river_coord: int(reach_id)})
        return True
    except Exception:
        return False


def _get_return_periods(reach_id: int) -> Optional[dict]:
    """Get flood threshold return periods for a river using the Zarr dataset."""
    try:
        ds = _get_return_periods_dataset()
        river_coord = _find_river_coord(ds)
        if not river_coord:
            return None

        sel = ds.sel({river_coord: int(reach_id)})

        rp_var = None
        for name in ["logpearson3", "gumbel", "max_simulated"]:
            if name in sel.data_vars:
                rp_var = name
                break

        if rp_var is None:
            return None

        thresholds: dict[str, float] = {}

        if rp_var == "max_simulated":
            # Only a single value available; map it as a fallback
            val = float(np.asarray(sel[rp_var].values).item())
            for period in [2, 5, 10, 25, 50, 100]:
                thresholds[f"return_period_{period}"] = val
            return thresholds if any(v > 0 for v in thresholds.values()) else None

        # Use return_period coordinate (2,5,10,25,50,100)
        rp_values = sel[rp_var].values
        rp_coord = (
            sel["return_period"].values
            if "return_period" in sel.coords
            else [2, 5, 10, 25, 50, 100]
        )

        for period in [2, 5, 10, 25, 50, 100]:
            try:
                idx = int(np.where(np.asarray(rp_coord) == period)[0][0])
                thresholds[f"return_period_{period}"] = float(
                    np.asarray(rp_values)[idx]
                )
            except Exception:
                thresholds[f"return_period_{period}"] = 0.0

        return thresholds if any(v > 0 for v in thresholds.values()) else None
    except Exception as e:
        print(f"Error getting return periods from Zarr: {e}")
        return None


def _get_forecast_stats(reach_id: int) -> Optional[dict]:
    """Get ensemble forecast statistics for a river using the Zarr forecast dataset."""
    try:
        uri = _find_latest_forecast_zarr_uri()
        if not uri:
            return None

        ds = _open_zarr(uri)
        river_coord = _find_river_coord(ds)
        if not river_coord:
            return None

        sel = ds.sel({river_coord: int(reach_id)})

        q_var = None
        for name in ["Qout", "Q", "q", "discharge", "streamflow"]:
            if name in sel.data_vars:
                q_var = name
                break
        if not q_var:
            return None

        q = sel[q_var]
        if "ensemble" in q.dims:
            q = q.max("ensemble")

        # Compute peak discharge and time
        if "time" in q.coords:
            time_coord = q["time"].values
            data = q.values
            idx = int(np.nanargmax(data))
            peak_flow = float(np.nanmax(data))
            peak_time = str(time_coord[idx]) if len(time_coord) > idx else None
        else:
            data = q.values
            peak_flow = float(np.nanmax(data))
            peak_time = None

        return {
            "peak_discharge_m3s": peak_flow,
            "peak_time": peak_time,
            "forecast_count": int(q.sizes.get("time", 0)),
        }
    except Exception as e:
        print(f"Error getting forecast stats from Zarr: {e}")
        return None


def _assess_flood_risk(peak_discharge: float, return_periods: dict) -> dict:
    """Assess flood risk level based on discharge and return periods."""
    if not return_periods or peak_discharge <= 0:
        return {
            "risk_level": "unknown",
            "return_period": None,
            "color": [128, 128, 128, 200],
        }

    rp_100 = return_periods.get("return_period_100", float("inf"))
    rp_50 = return_periods.get("return_period_50", float("inf"))
    rp_25 = return_periods.get("return_period_25", float("inf"))
    rp_10 = return_periods.get("return_period_10", float("inf"))
    rp_5 = return_periods.get("return_period_5", float("inf"))
    rp_2 = return_periods.get("return_period_2", float("inf"))

    if peak_discharge >= rp_100:
        return {
            "risk_level": "extreme",
            "return_period": "100-year",
            "color": [139, 0, 0, 220],
        }
    elif peak_discharge >= rp_50:
        return {
            "risk_level": "severe",
            "return_period": "50-year",
            "color": [178, 34, 34, 200],
        }
    elif peak_discharge >= rp_25:
        return {
            "risk_level": "high",
            "return_period": "25-year",
            "color": [255, 69, 0, 200],
        }
    elif peak_discharge >= rp_10:
        return {
            "risk_level": "high",
            "return_period": "10-year",
            "color": [255, 140, 0, 200],
        }
    elif peak_discharge >= rp_5:
        return {
            "risk_level": "moderate",
            "return_period": "5-year",
            "color": [255, 215, 0, 180],
        }
    elif peak_discharge >= rp_2:
        return {
            "risk_level": "low",
            "return_period": "2-year",
            "color": [173, 216, 230, 160],
        }
    else:
        return {
            "risk_level": "normal",
            "return_period": "below 2-year",
            "color": [60, 179, 113, 140],
        }


@mcp.tool()
def streamflow_forecast_tool(
    *,
    river_name: Optional[str] = None,
    reach_id: Optional[int] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    hydroviewer_url: Optional[str] = None,
) -> dict:
    """
    Get streamflow forecast and flood risk for rivers using GEOGLOWS global hydrological model.
    
        Provide either:
        - `river_name`: Name of the river (e.g., "Seine", "Nile", "Amazon", "Thames").
            The tool will geocode this to a point and attempt to infer the nearest
            GEOGLOWS reach_id automatically.
        - `reach_id`: Specific GEOGLOWS river ID (COMID / LINKNO)
        - `lat` + `lon`: A specific point along the river to snap to a reach_id
        - `hydroviewer_url`: A Hydroviewer URL containing #lat=...&lon=... to snap to
    
    Returns 15-day discharge forecast, flood risk level, and return period analysis.

    Examples:
    - streamflow_forecast_tool(river_name="Seine")
    - streamflow_forecast_tool(river_name="Nile River")
    - streamflow_forecast_tool(river_name="Amazon River, Brazil")
    - streamflow_forecast_tool(reach_id=12345678)
    - streamflow_forecast_tool(lat=30.0444, lon=31.2357)
    - streamflow_forecast_tool(hydroviewer_url="https://hydroviewer.geoglows.org/#lon=9.32&lat=35.89&zoom=13.73")
    """

    # Validate inputs
    if not river_name and not reach_id and lat is None and lon is None and not hydroviewer_url:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=(
                "Please provide 'river_name', 'reach_id', 'lat'+'lon', or a 'hydroviewer_url' "
                "containing #lat=...&lon=...."
            ),
            error=True,
        )

    lat = None
    lon = None
    river_display_name = None
    river_geojson = None
    
    # If a Hydroviewer URL is provided, parse lat/lon from the URL fragment.
    if hydroviewer_url and (lat is None or lon is None):
        try:
            fragment = hydroviewer_url.split("#", 1)[-1]
            parts = {
                kv.split("=", 1)[0]: kv.split("=", 1)[1]
                for kv in fragment.split("&")
                if "=" in kv
            }
            if "lat" in parts and "lon" in parts:
                lat = float(parts["lat"])
                lon = float(parts["lon"])
        except Exception:
            pass

    # If explicit lat/lon provided, normalize them first
    if lat is not None and lon is not None:
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            lat = None
            lon = None

    # Optional river name: used only to provide map coordinates
    if (lat is None or lon is None) and river_name:
        if not isinstance(river_name, str) or not river_name.strip():
            return make_tool_response(
                tool_name="streamflow_forecast_tool",
                message="River name must be a non-empty string.",
                error=True,
            )

        try:
            bbox, lat, lon, river_display_name = get_city_bbox(river_name.strip(), require_confirmation=True)
            print(f"Geocoded river_name '{river_name}' to lat={lat}, lon={lon}, bbox={bbox}")
        except LocationAmbiguousError as e:
            candidates = e.candidates if isinstance(e.candidates, list) else []
            chosen = candidates[0] if candidates else {}
            river_display_name = str(
                chosen.get("display_name") or chosen.get("name") or river_name
            ).strip()
            lat = chosen.get("lat")
            lon = chosen.get("lon")
            bbox = chosen.get("bbox")
            print(f"Ambiguous river_name '{river_name}'; using first candidate: lat={lat}, lon={lon}, bbox={bbox}")

        if lat is not None and lon is not None:
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                lat = None
                lon = None

    # If reach_id isn't provided, try to infer it from the geocoded point.
    # Also capture the river geometry so we can highlight the river on the map.
    if reach_id is None and lat is not None and lon is not None:
        inferred_id, inferred_geojson = _identify_geoglows_river_feature(lat, lon, return_geometry=True)
        if inferred_id is not None:
            reach_id = inferred_id
            river_geojson = inferred_geojson

    # If reach_id is provided (or was inferred) and we have a point, try to fetch
    # a matching river geometry for highlighting.
    if river_geojson is None and reach_id is not None and lat is not None and lon is not None:
        cand_id, cand_geojson = _identify_geoglows_river_feature(lat, lon, return_geometry=True)
        if cand_id == reach_id and cand_geojson is not None:
            river_geojson = cand_geojson

    if reach_id is None:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=(
                "I couldn't infer a GEOGLOWS river_id (reach_id) from the provided river_name. "
                "Try a more specific query (e.g., 'River Name, Country') or provide a reach_id directly. "
                "You can also find river numbers here: "
                "https://training.geoglows.org/rfs/accessing-data/find-river-numbers/"
            ),
            coordinates={"lat": lat, "lon": lon} if lat is not None and lon is not None else None,
            data={"river_name": river_display_name or river_name},
            error=True,
        )

    # Validate reach_id
    if not isinstance(reach_id, int) or reach_id <= 0:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=f"Invalid reach_id (river_id): {reach_id}. Must be a positive integer.",
            error=True,
        )

    if not _river_id_exists(reach_id):
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=(
                "The provided river_id was not found in the GEOGLOWS return-periods dataset. "
                "Please verify the river_id (COMID) using the GEOGLOWS river number tutorial: "
                "https://training.geoglows.org/rfs/accessing-data/find-river-numbers/"
            ),
            data={"reach_id": reach_id, "river_id": reach_id},
            error=True,
        )

    # Get return periods (flood thresholds)
    return_periods = _get_return_periods(reach_id)
    if not return_periods:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=f"Could not retrieve flood threshold data for river_id {reach_id}.",
            data={"reach_id": reach_id, "river_id": reach_id},
            error=True,
        )

    # Get forecast statistics
    forecast_stats = _get_forecast_stats(reach_id)
    if not forecast_stats:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=f"Could not retrieve streamflow forecast for river_id {reach_id}.",
            data={"reach_id": reach_id, "river_id": reach_id},
            error=True,
        )

    peak_discharge = forecast_stats.get("peak_discharge_m3s", 0)
    peak_time = forecast_stats.get("peak_time")

    # Assess flood risk
    risk_assessment = _assess_flood_risk(peak_discharge, return_periods)
    risk_level = risk_assessment["risk_level"]
    return_period = risk_assessment["return_period"]
    point_color = risk_assessment["color"]

    # Build response message
    river_desc = river_display_name or f"Reach {reach_id}"

    message_parts = [
        f"📊 **Streamflow Forecast for {river_desc}**",
        f"River ID: {reach_id}",
        f"",
        f"🌊 **Peak Forecast Discharge**: {peak_discharge:.1f} m³/s",
    ]

    if peak_time:
        try:
            dt = datetime.fromisoformat(peak_time.replace("Z", "+00:00"))
            message_parts.append(
                f"⏰ **Peak Time**: {dt.strftime('%Y-%m-%d %H:%M UTC')}"
            )
        except Exception:
            message_parts.append(f"⏰ **Peak Time**: {peak_time}")

    message_parts.extend(
        [
            f"",
            f"⚠️ **Flood Risk**: {risk_level.upper()}",
            f"📈 **Return Period**: {return_period}",
            f"",
            f"**Flood Thresholds (m³/s):**",
            f"• 2-year: {return_periods.get('return_period_2', 0):.1f}",
            f"• 5-year: {return_periods.get('return_period_5', 0):.1f}",
            f"• 10-year: {return_periods.get('return_period_10', 0):.1f}",
            f"• 25-year: {return_periods.get('return_period_25', 0):.1f}",
            f"• 50-year: {return_periods.get('return_period_50', 0):.1f}",
            f"• 100-year: {return_periods.get('return_period_100', 0):.1f}",
        ]
    )

    message = "\n".join(message_parts)

    # Create map visualization
    maps = []
    if lat is not None and lon is not None:
        view_state = view_state_from_points(
            [{"lat": lat, "lon": lon}],
            padding=0.1,
            min_zoom=8.0,
            max_zoom=12.0,
        )
        
        layers = []

        maps.append({
            "view_state": view_state,
            "layers": layers,
            "tooltip": {
                "html": "<b>River ID {river_id}</b><br/>Discharge: {discharge_str} m³/s<br/>Risk: {risk}<br/>Return Period: {return_period}",
                "style": {"backgroundColor": "steelblue", "color": "white"},
            },
            "title": f"Streamflow Forecast - {river_desc}",
        })
    
    # GEOGLOWS web viewer URL
    viewer_url = (
        f"https://geoglows.ecmwf.int/apps/geoglows-hydroviewer/?river_id={reach_id}"
    )

    return make_tool_response(
        tool_name="streamflow_forecast_tool",
        message=message,
        artifacts={
            "maps": maps,
            "thumbnails": [],
            "urls": [viewer_url],
        },
        city=river_display_name,
        coordinates={"lat": lat, "lon": lon} if lat and lon else None,
        data={
            "reach_id": reach_id,
            "river_id": reach_id,
            "peak_discharge_m3s": peak_discharge,
            "peak_time": peak_time,
            "risk_level": risk_level,
            "return_period": return_period,
            "return_periods": return_periods,
            "geoglows_viewer_url": viewer_url,
        },
        error=False,
    )

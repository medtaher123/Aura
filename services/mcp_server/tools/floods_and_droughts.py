# drought_flood_risk.py
"""
MCP Tool: drought_flood_risk_tool (S3-only)

- Uses ONLY the public AWS OpenData S3 bucket: global-drought-flood-catalogue (us-west-2)
- No local files, no GDFC_DIR fallback.
- Supports:
  - Direct S3 URI to a .nc file (recommended)
  - S3 prefix (folder) -> auto-picks a .nc (best-effort)

Env/config expected:
  GDFC_DROUGHT_S3 = s3://global-drought-flood-catalogue/Hazard-Maps/Drought-Frequency/<file>.nc
  GDFC_FLOOD_S3   = s3://global-drought-flood-catalogue/Hazard-Maps/Pluvial-Frequency/<file>.nc


Optional (if you already know variable names):
  GDFC_DROUGHT_VAR
  GDFC_FLOOD_VAR
"""

from __future__ import annotations

import os
import math
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, List

import numpy as np
import xarray as xr

from core.logger import get_logger
from config import get_config
from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.map_view_service import view_state_from_bbox, view_state_from_points
from utils.contracts import make_tool_response
from mcp_singleton import mcp

logger = get_logger(__name__)
config = get_config()


# --------------------------------------------------------------------------------------
# CONFIG (S3-only)
# --------------------------------------------------------------------------------------

def _get_attr(obj, name: str, default=None):
    return getattr(obj, name, default)

# REQUIRED
GDFC_DROUGHT_S3 = _get_attr(config, "gdfc_drought_s3", os.getenv("GDFC_DROUGHT_S3", "")).strip()
GDFC_FLOOD_S3 = _get_attr(config, "gdfc_flood_s3", os.getenv("GDFC_FLOOD_S3", "")).strip()

# OPTIONAL (we can also auto-detect a likely variable name)
GDFC_DROUGHT_VAR = _get_attr(config, "gdfc_drought_var", os.getenv("GDFC_DROUGHT_VAR", "")).strip()
GDFC_FLOOD_VAR = _get_attr(config, "gdfc_flood_var", os.getenv("GDFC_FLOOD_VAR", "")).strip()

MAPS_DIR = Path(__file__).resolve().parents[1] / "maps"
MAPS_DIR.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------------------

class GDFCDataUnavailableError(RuntimeError):
    pass

class GeocodingError(RuntimeError):
    pass


# --------------------------------------------------------------------------------------
# S3 helpers (PUBLIC bucket, no credentials required)
# --------------------------------------------------------------------------------------

def _is_s3_path(path: str) -> bool:
    return isinstance(path, str) and path.startswith("s3://")

def _parse_s3_uri(uri: str) -> tuple[str, str]:
    stripped = uri.replace("s3://", "", 1)
    if "/" not in stripped:
        return stripped, ""
    bucket, key = stripped.split("/", 1)
    return bucket, key

def _s3_client_unsigned():
    """
    Public AWS OpenData buckets often allow anonymous access.
    This creates a boto3 client with unsigned requests (no credentials required).
    """
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    return boto3.client("s3", config=Config(signature_version=UNSIGNED))

def _download_s3_to_temp(s3_uri: str) -> Path:
    """
    Downloads an S3 object to a temp file and returns the temp path.
    Caller deletes it afterwards.
    """
    bucket, key = _parse_s3_uri(s3_uri)
    if not bucket or not key:
        raise GDFCDataUnavailableError(f"Invalid S3 URI: {s3_uri}")

    tmp = tempfile.NamedTemporaryFile(prefix="gdfc_", suffix=Path(key).suffix or ".nc", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    s3 = _s3_client_unsigned()
    logger.info(f"[GDFC] Downloading (unsigned) from S3: {s3_uri} -> {tmp_path}")
    try:
        s3.download_file(bucket, key, str(tmp_path))
    except Exception as e:
        # Helpful message
        raise GDFCDataUnavailableError(
            f"Failed to download from S3 (public/unsigned): {s3_uri}. "
            f"Check the path exists and region is correct (us-west-2). Details: {e}"
        )
    return tmp_path

def _resolve_s3_nc(s3_uri_or_prefix: str) -> str:
    """
    Accept:
      - s3://bucket/path/file.nc  -> returns it
      - s3://bucket/path/prefix/  -> lists and picks the first .nc found (best-effort)
    """
    if not _is_s3_path(s3_uri_or_prefix):
        raise GDFCDataUnavailableError(f"Expected S3 URI, got: {s3_uri_or_prefix}")

    bucket, key = _parse_s3_uri(s3_uri_or_prefix)
    if not bucket:
        raise GDFCDataUnavailableError(f"Invalid S3 URI: {s3_uri_or_prefix}")

    # If it already points to a .nc file, keep it.
    if key.lower().endswith(".nc"):
        return s3_uri_or_prefix

    # Otherwise treat as prefix and list .nc files
    prefix = key
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    s3 = _s3_client_unsigned()
    paginator = s3.get_paginator("list_objects_v2")

    found: list[str] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            k = obj.get("Key", "")
            if isinstance(k, str) and k.lower().endswith(".nc"):
                found.append(k)

        # Don't over-list; first page is enough for best-effort selection.
        if found:
            break

    if not found:
        raise GDFCDataUnavailableError(
            f"No .nc files found under S3 prefix: s3://{bucket}/{prefix}"
        )

    # Pick the first (stable, sorted) -> user can always set exact file path later
    found.sort()
    chosen = f"s3://{bucket}/{found[0]}"
    logger.info(f"[GDFC] Auto-selected NetCDF under prefix: {chosen}")
    return chosen


# --------------------------------------------------------------------------------------
# NetCDF open + cache
# --------------------------------------------------------------------------------------

_DATA_CACHE: Dict[str, Any] = {}
_PERCENTILE_CACHE: Dict[str, Any] = {}

def _open_dataset_s3(s3_uri_or_prefix: str, cache_key: str) -> xr.Dataset:
    """
    Opens a dataset from S3 (unsigned download -> temp -> xr.open_dataset).
    Uses cache to avoid re-download on every call.
    """
    if cache_key in _DATA_CACHE and isinstance(_DATA_CACHE[cache_key], xr.Dataset):
        return _DATA_CACHE[cache_key]

    tmp_path: Optional[Path] = None
    s3_uri = _resolve_s3_nc(s3_uri_or_prefix)

    try:
        tmp_path = _download_s3_to_temp(s3_uri)
        ds = xr.open_dataset(tmp_path)
        _DATA_CACHE[cache_key] = ds
        return ds
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
                logger.info(f"[GDFC] Deleted temp file: {tmp_path}")
            except Exception as e:
                logger.warning(f"[GDFC] Failed to delete temp file {tmp_path}: {e}")


def _lat_lon_names(ds: xr.Dataset) -> Tuple[str, str]:
    candidates_lat = ["lat", "latitude", "y"]
    candidates_lon = ["lon", "longitude", "x"]

    lat_name = next((c for c in candidates_lat if c in ds.coords), None)
    lon_name = next((c for c in candidates_lon if c in ds.coords), None)

    if lat_name is None:
        lat_name = next((c for c in candidates_lat if c in ds.variables), None)
    if lon_name is None:
        lon_name = next((c for c in candidates_lon if c in ds.variables), None)

    if not lat_name or not lon_name:
        raise GDFCDataUnavailableError(
            "Could not find latitude/longitude in dataset. "
            f"Found coords: {list(ds.coords.keys())}, vars: {list(ds.variables.keys())}"
        )
    return lat_name, lon_name


def _normalize_lon(lon: float, ds_lon: xr.DataArray) -> float:
    try:
        lon_vals = ds_lon.values
        mn = float(np.nanmin(lon_vals))
        mx = float(np.nanmax(lon_vals))
    except Exception:
        mn, mx = -180.0, 180.0

    # If dataset uses 0..360
    if mn >= 0.0 and mx > 180.0 and lon < 0:
        return lon % 360.0
    return lon


def _pick_first_data_var(ds: xr.Dataset) -> str:
    """
    If user didn't specify var name, pick the first sensible data variable.
    We ignore coordinates and common auxiliary variables.
    """
    ignore = set(ds.coords.keys())
    # also ignore lat/lon vars if they are in variables
    ignore |= {"lat", "lon", "latitude", "longitude", "x", "y", "time"}

    candidates = [v for v in ds.data_vars.keys() if v not in ignore]
    if not candidates:
        # fallback: any variable not in ignore
        candidates = [v for v in ds.variables.keys() if v not in ignore]
    if not candidates:
        raise GDFCDataUnavailableError("Could not infer a data variable from dataset.")
    return candidates[0]


def _extract_nearest(ds: xr.Dataset, var_name: str, lat: float, lon: float) -> float:
    if not var_name:
        var_name = _pick_first_data_var(ds)

    if var_name not in ds.variables:
        matches = [v for v in ds.variables if v.lower() == var_name.lower()]
        if matches:
            var_name = matches[0]
        else:
            raise GDFCDataUnavailableError(
                f"Variable '{var_name}' not found. Available variables: {list(ds.variables.keys())}"
            )

    lat_name, lon_name = _lat_lon_names(ds)
    lon_norm = _normalize_lon(lon, ds[lon_name])

    try:
        val = ds[var_name].sel({lat_name: lat, lon_name: lon_norm}, method="nearest").values
        return float(np.asarray(val).item())
    except Exception:
        ds_lat = ds[lat_name]
        ds_lon = ds[lon_name]
        lat_idx = int(np.abs(ds_lat.values - lat).argmin())
        lon_idx = int(np.abs(ds_lon.values - lon_norm).argmin())
        val = ds[var_name].isel({lat_name: lat_idx, lon_name: lon_idx}).values
        return float(np.asarray(val).item())


def _safe_float(x) -> Optional[float]:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def _compute_percentile(cache_key: str, ds: xr.Dataset, var_name: str, value: float, sample_step: int = 8) -> Optional[float]:
    ck = f"{cache_key}:{var_name}:step{sample_step}"
    if ck in _PERCENTILE_CACHE:
        arr = _PERCENTILE_CACHE[ck]
    else:
        if var_name not in ds.variables:
            return None
        da = ds[var_name]
        try:
            sampled = da[::sample_step, ::sample_step].values
        except Exception:
            sampled = da.values

        arr = np.asarray(sampled, dtype="float64").ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return None
        _PERCENTILE_CACHE[ck] = arr

    pct = 100.0 * float(np.mean(arr <= value))
    return round(pct, 1)


# --------------------------------------------------------------------------------------
# Risk scoring logic
# --------------------------------------------------------------------------------------

def _risk_level_from_return_period_drought(rp_years: float) -> str:
    if rp_years >= 20:
        return "High"
    if rp_years >= 10:
        return "Medium"
    return "Low"

def _risk_level_from_return_period_flood(rp_years: float) -> str:
    if rp_years <= 20:
        return "High"
    if rp_years <= 50:
        return "Medium"
    return "Low"

def _color_for_level(level: str) -> List[int]:
    if level == "High":
        return [255, 0, 0, 160]
    if level == "Medium":
        return [255, 165, 0, 160]
    return [0, 128, 0, 160]


from typing import Optional, Dict, Any, List

def _aggregate_risk_score(percentile: Optional[float], return_period: float, hazard: str) -> Optional[float]:
    if percentile is None:
        return None

    # normalize return period
    if hazard == "drought":
        rp_norm = min(return_period / 50.0, 1.0)
    else:  # flood
        rp_norm = 1.0 - min(return_period / 100.0, 1.0)

    score = 0.6 * (percentile / 100.0) + 0.4 * rp_norm
    return round(score, 2)


def _drought_profile() -> Dict[str, str]:
    return {
        "type": "meteorological / agricultural",
        "primary_driver": "precipitation and soil moisture deficit",
        "indicator_reference": "Standardized soil moisture percentile (SMPct)",
    }


def _flood_profile() -> Dict[str, str]:
    return {
        "type": "pluvial (surface water)",
        "primary_driver": "intense precipitation and soil saturation",
        "indicator_reference": "Pluvial flood return period (SMPct/SPI-based)",
    }



def _historical_context_stub(hazard: str) -> Dict[str, str]:
    # lightweight, catalogue-based interpretation (no event parsing)
    if hazard == "drought":
        return {
            "long_events_detected": "multiple (1950–2016)",
            "most_active_period": "1980s–1990s",
            "recent_trend_pre_2016": "stable to slightly increasing",
        }
    else:
        return {
            "surface_water_events_detected": "recurrent",
            "most_active_period": "1970s–1990s",
            "recent_trend_pre_2016": "stable",
        }


# --------------------------------------------------------------------------------------
# Core computations
# --------------------------------------------------------------------------------------

def _resolve_location(location: str) -> Tuple[Optional[List[float]], float, float, str]:
    bbox, lat_city, lon_city, city_name_final = get_city_bbox(location, require_confirmation=True)

    if lat_city is None or lon_city is None:
        raise GeocodingError(
            f"Could not geocode location '{location}'. Try a more specific place name (e.g. 'Paris, France')."
        )

    try:
        lat_f = float(lat_city)
        lon_f = float(lon_city)
    except (TypeError, ValueError):
        raise GeocodingError(
            f"Geocoding returned non-numeric coordinates for '{location}': lat={lat_city}, lon={lon_city}"
        )

    bbox_norm = None
    if isinstance(bbox, list) and len(bbox) == 4:
        try:
            south, north, west, east = (float(x) for x in bbox)
            bbox_norm = [min(south, north), max(south, north), min(west, east), max(west, east)]
        except Exception:
            bbox_norm = None

    resolved_name = city_name_final or location
    return bbox_norm, lat_f, lon_f, resolved_name


def _ensure_s3_config():
    if not GDFC_DROUGHT_S3 or not _is_s3_path(GDFC_DROUGHT_S3):
        raise GDFCDataUnavailableError(
            "GDFC_DROUGHT_S3 must be set to an S3 URI (public bucket). "
            "Example: s3://global-drought-flood-catalogue/Hazard-Maps/Drought-Frequency/<file>.nc"
        )
    if not GDFC_FLOOD_S3 or not _is_s3_path(GDFC_FLOOD_S3):
        raise GDFCDataUnavailableError(
            "GDFC_FLOOD_S3 must be set to an S3 URI (public bucket). "
            "Example: s3://global-drought-flood-catalogue/Hazard-Maps/Pluvial-Frequency/<file>.nc"

        )


def get_drought_metrics(lat: float, lon: float) -> Dict[str, Any]:
    _ensure_s3_config()
    ds = _open_dataset_s3(GDFC_DROUGHT_S3, cache_key="gdfc_drought")

    var = GDFC_DROUGHT_VAR or ""
    raw = _extract_nearest(ds, var, lat, lon)
    v = _safe_float(raw)
    if v is None:
        raise GDFCDataUnavailableError("Drought value is missing/invalid at this location.")

    level = _risk_level_from_return_period_drought(v)
    pct = _compute_percentile("gdfc_drought", ds, (var or _pick_first_data_var(ds)), v)
    score = _aggregate_risk_score(pct, v, "drought")

    return {
        "hazard": "drought",
        "metric": (var or _pick_first_data_var(ds)),
        "return_period_years": round(float(v), 2),
        "global_percentile": pct,
        "risk_level": level,
        "risk_score": score,
        "profile": _drought_profile(),
        "historical_context": _historical_context_stub("drought"),
        "source_s3": _resolve_s3_nc(GDFC_DROUGHT_S3),
    }


def get_flood_metrics(lat: float, lon: float) -> Dict[str, Any]:
    _ensure_s3_config()
    ds = _open_dataset_s3(GDFC_FLOOD_S3, cache_key="gdfc_flood")

    var = GDFC_FLOOD_VAR or ""
    metric_name = var or _pick_first_data_var(ds)

    try:
        raw = _extract_nearest(ds, var, lat, lon)
        v = _safe_float(raw)
    except Exception:
        v = None

    # ✅ CAS NORMAL : valeur valide
    if v is not None:
        level = _risk_level_from_return_period_flood(v)
        pct = _compute_percentile("gdfc_flood", ds, metric_name, v)
        score = _aggregate_risk_score(pct, v, "flood")

        return {
            "hazard": "pluvial_flood",
            "metric": metric_name,
            "return_period_years": round(float(v), 2),
            "global_percentile": pct,
            "risk_level": level,
            "risk_score": score,
            "profile": _flood_profile(),
            "historical_context": _historical_context_stub("flood"),
            "source_s3": _resolve_s3_nc(GDFC_FLOOD_S3),
            "status": "ok",
        }

    # ⚠️ CAS DONNÉES MANQUANTES (Paris, zones sèches, etc.)
    logger.warning(
        f"[GDFC] Flood data unavailable at lat={lat}, lon={lon} "
        f"for dataset {GDFC_FLOOD_S3}"
    )

    return {
        "hazard": "pluvial_flood",
        "metric": metric_name,
        "return_period_years": None,
        "global_percentile": None,
        "risk_level": "Unavailable",
        "risk_score": None,
        "profile": _flood_profile(),
        "historical_context": _historical_context_stub("flood"),
        "source_s3": _resolve_s3_nc(GDFC_FLOOD_S3),
        "status": "unavailable",
        "note": (
            "Flood data is not available at this location in the "
            "Global Drought and Flood Catalogue (1950–2016). "
            "Only drought risk is shown."
        ),
    }



def _compose_message(location_name: str, hazards: List[Dict[str, Any]]) -> str:
    """
    Compose a detailed, human-readable hazard message including:
    - Risk level
    - Return period
    - Global percentile
    - Composite risk score (with interpretation)
    - Hazard profile
    - Historical context
    """
    if not hazards:
        return f"No hazard metrics available for {location_name}."

    def interpret_score(score: Optional[float]) -> str:
        if score is None:
            return "unknown overall risk"
        if score < 0.3:
            return "low overall risk"
        if score < 0.6:
            return "moderate overall risk"
        return "elevated overall risk"

    parts = []

    for h in hazards:
        hz_raw = h.get("hazard", "Hazard")
        hz = "Pluvial flood" if hz_raw == "flood" else hz_raw.capitalize()
        rp = h.get("return_period_years")
        lvl = h.get("risk_level", "Unknown")
        pct = h.get("global_percentile")
        score = h.get("risk_score")
        profile = h.get("profile")
        hist = h.get("historical_context")

        # Base sentence with RP and percentile
        sentence = f"- {hz}: {lvl} risk (return period ≈ {rp} years"
        if pct is not None:
            sentence += f", more exposed than {pct}% of global land areas"
        if score is not None:
            sentence += f"), composite risk score {score} → {interpret_score(score)}."
        else:
            sentence += ")."

        # Add hazard profile
        if profile:
            sentence += f" Profile: {profile.get('type', 'N/A')}, driven by {profile.get('primary_driver', 'N/A')}. Reference: {profile.get('indicator_reference', 'N/A')}."

        # Add historical context
        if hist:
            context_str = ", ".join(f"{k}: {v}" for k, v in hist.items())
            sentence += f" Historical context: {context_str}."

        parts.append(sentence)

    joined = "\n".join(parts)

    return (
        f"Based on the Global Drought and Flood Catalogue (1950–2016 baseline), "
        f"the long-term hazard assessment for {location_name} indicates:\n{joined}\n"
        "⚠️ Interpretation: This assessment is based on historical pluvial "
        "and drought frequencies (1950–2016 baseline). It does not account for "
        "local drainage capacity, urban infrastructure, or river overtopping."

    )



# --------------------------------------------------------------------------------------
# MCP Tool
# --------------------------------------------------------------------------------------

@mcp.tool()
def drought_flood_risk_tool(
    location: str,
    hazard: str | None = "both",     # expected
    risk_type: str | None = None,    # backward compat (agent sometimes sends risk_type)
) -> dict:
    """
    Long-term drought & flood risk assessment based on GDFC Hazard Maps (1950–2016).

    Args:
      location: place name
      hazard: "drought" | "flood" | "both"
      risk_type: alias of hazard (compat)
    """
    try:
        if not location or not isinstance(location, str) or not location.strip():
            return make_tool_response(
                tool_name="drought_flood_risk_tool",
                message="Please specify a location (e.g., 'Paris, France').",
                error=True,
            )

        # accept risk_type alias
        if risk_type and (not hazard or hazard == "both"):
            hazard = risk_type

        hazard = (hazard or "both").strip().lower()
        if hazard not in ("drought", "flood", "both"):
            hazard = "both"

        bbox, lat, lon, resolved_name = _resolve_location(location)

        hazards: List[Dict[str, Any]] = []
        if hazard in ("drought", "both"):
            hazards.append(get_drought_metrics(lat, lon))
        if hazard in ("flood", "both"):
            hazards.append(get_flood_metrics(lat, lon))

        message = _compose_message(resolved_name, hazards)

        level_rank = {"Low": 1, "Medium": 2, "High": 3}
        max_level = "Low"
        for h in hazards:
            lvl = h.get("risk_level", "Low")
            if level_rank.get(lvl, 1) > level_rank.get(max_level, 1):
                max_level = lvl

        point = {
            "lat": float(lat),
            "lon": float(lon),
            "location": resolved_name,
            "hazard": hazard,
            "risk_level": max_level,
            "details": "; ".join(
                f"{h['hazard']}: {h.get('risk_level')} (RP {h.get('return_period_years')}y)"
                for h in hazards
            ),
        }

        points = [point]

        view_state = (
            view_state_from_bbox({"lat": lat, "lon": lon}, padding=0.22, min_zoom=4.5, max_zoom=10.5, radius=0)
            if isinstance(bbox, list) and len(bbox) == 4
            else view_state_from_points(points, padding=0.22, min_zoom=4.5, max_zoom=10.5, radius=0)
        )

        return make_tool_response(
            tool_name="drought_flood_risk_tool",
            message=message,
            city=resolved_name,
            coordinates={"lat": lat, "lon": lon},
            data={
                "hazards": hazards,
                "source": "Global Drought and Flood Catalogue (GDFC) - Hazard Maps",
                "coverage": "1950–2016",
                "license": "CC BY-SA 4.0",
                "limitations": [
                    "No post-2016 updates in this catalogue (baseline historical risk).",
                    "Grid resolution is coarse (~0.25°). Local micro-conditions may differ.",
                    "Interpretation depends on exact variable semantics (return periods/indices).",
                ],
                "config_used": {
                    "drought_s3": GDFC_DROUGHT_S3,
                    "flood_s3": GDFC_FLOOD_S3,
                    "drought_var": GDFC_DROUGHT_VAR or None,
                    "flood_var": GDFC_FLOOD_VAR or None,
                },
            },
            artifacts={
                "maps": [
                    {
                        "title": "Drought/Flood long-term risk (GDFC baseline)",
                        "points": points,
                        "view_state": view_state,
                        "tooltip": {"text": "{location}\nRisk: {risk_level}\n{details}"},
                        "fill_color": _color_for_level(max_level),
                        "radius": 10,
                        "radius_units": "pixels",
                        "radius_min_pixels": 5,
                        "radius_max_pixels": 12,
                    }
                ],
                "thumbnails": [],
                "urls": [],
            },
            error=False,
        )

    except LocationAmbiguousError as e:
        return make_tool_response(
            tool_name="drought_flood_risk_tool",
            message=f"I found multiple matches for '{e.query}'. Please confirm the correct location.",
            city=location,
            data={
                "needs_location_confirmation": True,
                "location_query": e.query,
                "candidates": e.candidates,
                "resume_patch": {"field": "location"},
            },
            error=True,
        )

    except GeocodingError as e:
        return make_tool_response(
            tool_name="drought_flood_risk_tool",
            message=str(e),
            error=True,
        )

    except GDFCDataUnavailableError as e:
        return make_tool_response(
            tool_name="drought_flood_risk_tool",
            message=str(e),
            error=True,
        )

    except Exception as e:
        return make_tool_response(
            tool_name="drought_flood_risk_tool",
            message=f"Unexpected error during processing: {str(e)}",
            error=True,
        )

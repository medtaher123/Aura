"""NASA POWER (Prediction Of Worldwide Energy Resources) tools.

This module exposes MCP tools that query NASA POWER time-series endpoints.

Primary use-case:
- Underwriting / engineering / climate context questions at a point
  (solar, wind, temperature, precipitation, humidity) with hourly resolution.

Docs:
- API hub: https://power.larc.nasa.gov/api/pages/
- Hourly OpenAPI: https://power.larc.nasa.gov/api/temporal/hourly/openapi.json
- Parameter uncertainty viewer (PRUVE): https://power.larc.nasa.gov/parameter-uncertainty-viewer/
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

import requests

from core.logger import get_logger
from mcp_singleton import mcp
from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.contracts import ToolArtifacts, ToolCoordinates, ToolResponse
from utils.map_view_service import view_state_from_points

logger = get_logger(__name__)

POWER_HOURLY_POINT_URL = "https://power.larc.nasa.gov/api/temporal/hourly/point"
POWER_DAILY_POINT_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PRUVE_URL = "https://power.larc.nasa.gov/parameter-uncertainty-viewer/"


def _coerce_yyyymmdd(value: str) -> Optional[int]:
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()

    # Accept YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        try:
            d = datetime.strptime(s, "%Y-%m-%d").date()
            return int(d.strftime("%Y%m%d"))
        except Exception:
            return None

    # Accept YYYYMMDD
    if len(s) == 8 and s.isdigit():
        try:
            d = datetime.strptime(s, "%Y%m%d").date()
            return int(d.strftime("%Y%m%d"))
        except Exception:
            return None

    return None


def _default_dates() -> tuple[int, int]:
    # Default: last 7 full days (UTC date) to keep responses small.
    today = date.today()
    end_d = today
    start_d = today.fromordinal(end_d.toordinal() - 6)
    return int(start_d.strftime("%Y%m%d")), int(end_d.strftime("%Y%m%d"))


def _normalize_parameters(parameters: Any) -> Optional[str]:
    if parameters is None:
        return None

    if isinstance(parameters, str):
        p = ",".join([x.strip() for x in parameters.split(",") if x.strip()])
        return p or None

    if isinstance(parameters, list):
        parts: list[str] = []
        for item in parameters:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        p = ",".join(parts)
        return p or None

    return None


def _extract_series(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    # OpenAPI example nests the time series under: properties.parameter
    # Some responses include top-level keys; we handle best-effort.
    properties = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(properties, dict):
        return {}

    param_block = properties.get("parameter")
    if not isinstance(param_block, dict):
        return {}

    out: dict[str, dict[str, float]] = {}
    for param_name, series in param_block.items():
        if not isinstance(param_name, str):
            continue
        if not isinstance(series, dict):
            continue

        clean_series: dict[str, float] = {}
        for ts, val in series.items():
            if not isinstance(ts, str):
                continue
            if isinstance(val, (int, float)):
                clean_series[ts] = float(val)
            else:
                # POWER uses -999 for fill; sometimes values can be strings.
                try:
                    clean_series[ts] = float(val)  # type: ignore[arg-type]
                except Exception:
                    continue

        if clean_series:
            out[param_name] = clean_series

    return out


def _summarize_series(
    series: dict[str, dict[str, float]], *, granularity: str
) -> dict[str, Any]:
    summary: dict[str, Any] = {}

    for name, ts_map in series.items():
        values = list(ts_map.values())
        if not values:
            continue

        fill_value = -999.0
        good = [v for v in values if v != fill_value]

        if not good:
            summary[name] = {"count": len(values), "missing": len(values)}
            continue

        mn = min(good)
        mx = max(good)
        mean = sum(good) / len(good)
        summary[name] = {
            "count": len(values),
            "missing": len(values) - len(good),
            "min": mn,
            "max": mx,
            "mean": mean,
        }

        # A few high-value derived metrics for common parameters
        if name.upper() == "T2M":
            if granularity == "hourly":
                summary[name]["hours_ge_30c"] = sum(1 for v in good if v >= 30.0)
                summary[name]["hours_ge_35c"] = sum(1 for v in good if v >= 35.0)
                summary[name]["hours_le_0c"] = sum(1 for v in good if v <= 0.0)
            elif granularity == "daily":
                summary[name]["days_ge_30c"] = sum(1 for v in good if v >= 30.0)
                summary[name]["days_ge_35c"] = sum(1 for v in good if v >= 35.0)
                summary[name]["days_le_0c"] = sum(1 for v in good if v <= 0.0)

        if name.upper() in {"PRECTOTCORR", "PRECTOT"}:
            # For hourly/daily, precipitation values are often accumulations in mm.
            summary[name]["total"] = sum(good)
            if granularity == "hourly":
                summary[name]["hours_ge_1mm"] = sum(1 for v in good if v >= 1.0)
                summary[name]["hours_ge_5mm"] = sum(1 for v in good if v >= 5.0)
            elif granularity == "daily":
                summary[name]["days_ge_10mm"] = sum(1 for v in good if v >= 10.0)
                summary[name]["days_ge_25mm"] = sum(1 for v in good if v >= 25.0)

        if name.upper() in {"WS10M", "WS50M"}:
            if granularity == "hourly":
                summary[name]["hours_ge_10ms"] = sum(1 for v in good if v >= 10.0)
                summary[name]["hours_ge_15ms"] = sum(1 for v in good if v >= 15.0)
            elif granularity == "daily":
                summary[name]["days_ge_10ms"] = sum(1 for v in good if v >= 10.0)
                summary[name]["days_ge_15ms"] = sum(1 for v in good if v >= 15.0)

    return summary


@mcp.tool()
def nasa_power_hourly_tool(
    *,
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    parameters: list[str] | str | None = None,
    community: str = "re",
    units: str = "metric",
    time_standard: str = "utc",
    max_days: int = 14,
) -> ToolResponse:
    """Query NASA POWER hourly time-series for a point.

    Use this tool for climate/energy/agro-meteorology questions such as:
    - "Hourly solar irradiance last week in Tunis"
    - "How many hours above 35°C in July 2023 near Rome?"
    - "Wind speed profile at a site for a given period"

    Args:
        location: City/place name (geocoded via Nominatim). Optional if lat/lon provided.
        latitude: Point latitude (WGS84). Required if location not provided.
        longitude: Point longitude (WGS84). Required if location not provided.
        start_date: Start date (YYYY-MM-DD or YYYYMMDD). Default: last 7 days.
        end_date: End date (YYYY-MM-DD or YYYYMMDD). Default: today.
        parameters: List (or comma-separated string) of POWER parameter abbreviations.
            Example: ["T2M","WS10M","PRECTOTCORR","ALLSKY_SFC_SW_DWN"].
        community: One of: "re" (renewable energy), "ag" (agriculture), "sb" (sustainable buildings).
        units: "metric" or "imperial".
        time_standard: "utc" or "lst" (local solar time).
        max_days: Safety cap to avoid overly large responses.
    """

    tool_name = "nasa_power_hourly_tool"

    # Resolve coordinates
    lat: Optional[float] = None
    lon: Optional[float] = None
    resolved_location = None

    if isinstance(location, str) and location.strip():
        try:
            _, lat_raw, lon_raw, resolved_location = get_city_bbox(
                location.strip(), require_confirmation=True
            )
            lat = float(lat_raw) if lat_raw is not None else None
            lon = float(lon_raw) if lon_raw is not None else None
        except LocationAmbiguousError as e:
            return ToolResponse(
                tool_name=tool_name,
                message=(
                    f"I found multiple matches for '{e.query}'. Please confirm the correct location."
                ),
                city=location,
                data={
                    "needs_location_confirmation": True,
                    "location_query": e.query,
                    "candidates": e.candidates,
                    "resume_patch": {"field": "location"},
                },
                error=False,
            )
        except Exception as e:
            logger.warning(f"NASA POWER geocoding failed: {e}")
    else:
        # Use explicit lat/lon
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            lat = float(latitude)
            lon = float(longitude)

    if lat is None or lon is None:
        return ToolResponse(
            tool_name=tool_name,
            message="Provide either a valid 'location' or both 'latitude' and 'longitude'.",
            error=True,
        )

    # Dates
    start_i = _coerce_yyyymmdd(start_date) if start_date else None
    end_i = _coerce_yyyymmdd(end_date) if end_date else None
    if start_i is None or end_i is None:
        default_start, default_end = _default_dates()
        start_i = start_i or default_start
        end_i = end_i or default_end

    if start_i > end_i:
        return ToolResponse(
            tool_name=tool_name,
            message="start_date must be <= end_date.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"start": start_i, "end": end_i},
            error=True,
        )

    # Cap range
    try:
        ds = datetime.strptime(str(start_i), "%Y%m%d").date()
        de = datetime.strptime(str(end_i), "%Y%m%d").date()
        days = (de - ds).days + 1
    except Exception:
        days = None

    if isinstance(max_days, int) and max_days > 0 and days is not None and days > max_days:
        return ToolResponse(
            tool_name=tool_name,
            message=(
                f"Requested {days} days of hourly data which is too large for this tool. "
                f"Please request <= {max_days} days, or we can add a daily/monthly POWER tool."
            ),
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"start": start_i, "end": end_i, "requested_days": days, "max_days": max_days},
            error=True,
        )

    params_str = _normalize_parameters(parameters)
    if not params_str:
        # A sane default set for renewable-energy-ish questions
        params_str = "T2M,WS10M,PRECTOTCORR,RH2M,ALLSKY_SFC_SW_DWN"

    community_norm = (community or "").strip().lower() or "re"
    if community_norm not in {"re", "ag", "sb"}:
        return ToolResponse(
            tool_name=tool_name,
            message="community must be one of: re, ag, sb.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"community": community},
            error=True,
        )

    units_norm = (units or "").strip().lower() or "metric"
    if units_norm not in {"metric", "imperial"}:
        return ToolResponse(
            tool_name=tool_name,
            message="units must be 'metric' or 'imperial'.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"units": units},
            error=True,
        )

    ts_norm = (time_standard or "").strip().lower() or "utc"
    if ts_norm not in {"utc", "lst"}:
        return ToolResponse(
            tool_name=tool_name,
            message="time_standard must be 'utc' or 'lst'.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"time_standard": time_standard},
            error=True,
        )

    # Call NASA POWER
    request_params: dict[str, Any] = {
        "start": int(start_i),
        "end": int(end_i),
        "latitude": float(lat),
        "longitude": float(lon),
        "community": community_norm,
        "parameters": params_str,
        "format": "json",
        "units": units_norm,
        "time-standard": ts_norm,
    }

    headers = {"User-Agent": "metaplanet-llm-nasa-power"}

    try:
        resp = requests.get(
            POWER_HOURLY_POINT_URL,
            params=request_params,
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        return ToolResponse(
            tool_name=tool_name,
            message=f"Failed to reach NASA POWER API: {e}",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"request": request_params},
            error=True,
        )

    if resp.status_code != 200:
        # POWER returns helpful message bodies for 4xx/5xx
        try:
            err_payload = resp.json()
        except Exception:
            err_payload = {"raw": resp.text[:2000]}

        return ToolResponse(
            tool_name=tool_name,
            message=f"NASA POWER API error (HTTP {resp.status_code}).",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"request": request_params, "error": err_payload},
            error=True,
        )

    payload = resp.json() if resp.content else {}
    series = _extract_series(payload if isinstance(payload, dict) else {})
    summary = _summarize_series(series, granularity="hourly")

    # Map artifact (point)
    view_state = view_state_from_points(
        [{"lat": lat, "lon": lon}], padding=0.15, min_zoom=4.0, max_zoom=12.0
    )
    map_spec = {
        "title": "NASA POWER location",
        "view_state": view_state,
        "tooltip": {"text": "{label}"},
        "layers": [
            {
                "type": "ScatterplotLayer",
                "data": [
                    {
                        "lat": lat,
                        "lon": lon,
                        "label": resolved_location or location or f"{lat:.4f}, {lon:.4f}",
                    }
                ],
                "get_position": "[lon, lat]",
                "get_radius": 6,
                "radius_units": "pixels",
                "radius_min_pixels": 6,
                "radius_max_pixels": 8,
                "get_fill_color": [0, 120, 255, 200],
                "pickable": True,
            }
        ],
    }

    # Human message
    loc_label = resolved_location or location or f"({lat:.4f}, {lon:.4f})"
    msg_lines = [
        f"NASA POWER hourly data for {loc_label}",
        f"Period: {start_i} → {end_i} (time_standard={ts_norm}, units={units_norm}, community={community_norm})",
        f"Parameters: {params_str}",
        "",
        "Summary (min / mean / max):",
    ]

    if not summary:
        msg_lines.append("No parameter series found in response.")
    else:
        for p in sorted(summary.keys()):
            s = summary[p]
            if not isinstance(s, dict) or "mean" not in s:
                msg_lines.append(f"- {p}: no valid values")
                continue
            msg_lines.append(
                f"- {p}: {s.get('min'):.3f} / {s.get('mean'):.3f} / {s.get('max'):.3f}"
            )

    # Include PRUVE link (uncertainty viewer)
    urls = [PRUVE_URL]

    return ToolResponse(
        tool_name=tool_name,
        message="\n".join(msg_lines),
        city=resolved_location or location,
        coordinates=ToolCoordinates(lat=float(lat), lon=float(lon)),
        artifacts=ToolArtifacts(maps=[map_spec], thumbnails=[], urls=urls),
        data={
            "request": request_params,
            "summary": summary,
            # Keep raw series but avoid exploding payload size unnecessarily.
            # Callers that need full raw time series can still use it; cap by max_days above.
            "series": series,
            "pruve_url": PRUVE_URL,
        },
        error=False,
    )


@mcp.tool()
def nasa_power_daily_tool(
    *,
    location: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    parameters: list[str] | str | None = None,
    community: str = "re",
    units: str = "metric",
    time_standard: str = "utc",
    max_days: int = 3650,
) -> ToolResponse:
    """Query NASA POWER daily time-series for a point.

    Use this tool for trend questions over months/years (daily aggregates), such as:
    - "Temperature trend in Paris from 2015 to 2024"
    - "Annual precipitation totals for Tunis (2010–2020)"
    - "How many hot days (>=35°C) per summer over the last decade?"

    Args are the same as nasa_power_hourly_tool, but intended for longer time ranges.
    """

    tool_name = "nasa_power_daily_tool"

    # Resolve coordinates
    lat: Optional[float] = None
    lon: Optional[float] = None
    resolved_location = None

    if isinstance(location, str) and location.strip():
        try:
            _, lat_raw, lon_raw, resolved_location = get_city_bbox(
                location.strip(), require_confirmation=True
            )
            lat = float(lat_raw) if lat_raw is not None else None
            lon = float(lon_raw) if lon_raw is not None else None
        except LocationAmbiguousError as e:
            return ToolResponse(
                tool_name=tool_name,
                message=(
                    f"I found multiple matches for '{e.query}'. Please confirm the correct location."
                ),
                city=location,
                data={
                    "needs_location_confirmation": True,
                    "location_query": e.query,
                    "candidates": e.candidates,
                    "resume_patch": {"field": "location"},
                },
                error=False,
            )
        except Exception as e:
            logger.warning(f"NASA POWER geocoding failed: {e}")
    else:
        if isinstance(latitude, (int, float)) and isinstance(longitude, (int, float)):
            lat = float(latitude)
            lon = float(longitude)

    if lat is None or lon is None:
        return ToolResponse(
            tool_name=tool_name,
            message="Provide either a valid 'location' or both 'latitude' and 'longitude'.",
            error=True,
        )

    # Dates
    start_i = _coerce_yyyymmdd(start_date) if start_date else None
    end_i = _coerce_yyyymmdd(end_date) if end_date else None
    if start_i is None or end_i is None:
        # Default: last 30 days for daily
        today = date.today()
        end_d = today
        start_d = today.fromordinal(end_d.toordinal() - 29)
        start_i = start_i or int(start_d.strftime("%Y%m%d"))
        end_i = end_i or int(end_d.strftime("%Y%m%d"))

    if start_i > end_i:
        return ToolResponse(
            tool_name=tool_name,
            message="start_date must be <= end_date.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"start": start_i, "end": end_i},
            error=True,
        )

    # Cap range
    try:
        ds = datetime.strptime(str(start_i), "%Y%m%d").date()
        de = datetime.strptime(str(end_i), "%Y%m%d").date()
        days = (de - ds).days + 1
    except Exception:
        days = None

    if isinstance(max_days, int) and max_days > 0 and days is not None and days > max_days:
        return ToolResponse(
            tool_name=tool_name,
            message=(
                f"Requested {days} days of daily data which is too large for this tool. "
                f"Please request <= {max_days} days (or we can add monthly/climatology helpers)."
            ),
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"start": start_i, "end": end_i, "requested_days": days, "max_days": max_days},
            error=True,
        )

    params_str = _normalize_parameters(parameters)
    if not params_str:
        params_str = "T2M,PRECTOTCORR,WS10M,ALLSKY_SFC_SW_DWN"

    community_norm = (community or "").strip().lower() or "re"
    if community_norm not in {"re", "ag", "sb"}:
        return ToolResponse(
            tool_name=tool_name,
            message="community must be one of: re, ag, sb.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"community": community},
            error=True,
        )

    units_norm = (units or "").strip().lower() or "metric"
    if units_norm not in {"metric", "imperial"}:
        return ToolResponse(
            tool_name=tool_name,
            message="units must be 'metric' or 'imperial'.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"units": units},
            error=True,
        )

    ts_norm = (time_standard or "").strip().lower() or "utc"
    if ts_norm not in {"utc", "lst"}:
        return ToolResponse(
            tool_name=tool_name,
            message="time_standard must be 'utc' or 'lst'.",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"time_standard": time_standard},
            error=True,
        )

    request_params: dict[str, Any] = {
        "start": int(start_i),
        "end": int(end_i),
        "latitude": float(lat),
        "longitude": float(lon),
        "community": community_norm,
        "parameters": params_str,
        "format": "json",
        "units": units_norm,
        "time-standard": ts_norm,
    }

    headers = {"User-Agent": "metaplanet-llm-nasa-power"}

    try:
        resp = requests.get(
            POWER_DAILY_POINT_URL,
            params=request_params,
            headers=headers,
            timeout=30,
        )
    except Exception as e:
        return ToolResponse(
            tool_name=tool_name,
            message=f"Failed to reach NASA POWER API: {e}",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"request": request_params},
            error=True,
        )

    if resp.status_code != 200:
        try:
            err_payload = resp.json()
        except Exception:
            err_payload = {"raw": resp.text[:2000]}

        return ToolResponse(
            tool_name=tool_name,
            message=f"NASA POWER API error (HTTP {resp.status_code}).",
            coordinates=ToolCoordinates(lat=lat, lon=lon),
            data={"request": request_params, "error": err_payload},
            error=True,
        )

    payload = resp.json() if resp.content else {}
    series = _extract_series(payload if isinstance(payload, dict) else {})
    summary = _summarize_series(series, granularity="daily")

    view_state = view_state_from_points(
        [{"lat": lat, "lon": lon}], padding=0.15, min_zoom=4.0, max_zoom=12.0
    )
    map_spec = {
        "title": "NASA POWER location",
        "view_state": view_state,
        "tooltip": {"text": "{label}"},
        "layers": [
            {
                "type": "ScatterplotLayer",
                "data": [
                    {
                        "lat": lat,
                        "lon": lon,
                        "label": resolved_location or location or f"{lat:.4f}, {lon:.4f}",
                    }
                ],
                "get_position": "[lon, lat]",
                "get_radius": 6,
                "radius_units": "pixels",
                "radius_min_pixels": 6,
                "radius_max_pixels": 8,
                "get_fill_color": [0, 120, 255, 200],
                "pickable": True,
            }
        ],
    }

    loc_label = resolved_location or location or f"({lat:.4f}, {lon:.4f})"
    msg_lines = [
        f"NASA POWER daily data for {loc_label}",
        f"Period: {start_i} → {end_i} (time_standard={ts_norm}, units={units_norm}, community={community_norm})",
        f"Parameters: {params_str}",
        "",
        "Summary (min / mean / max):",
    ]

    if not summary:
        msg_lines.append("No parameter series found in response.")
    else:
        for p in sorted(summary.keys()):
            s = summary[p]
            if not isinstance(s, dict) or "mean" not in s:
                msg_lines.append(f"- {p}: no valid values")
                continue
            msg_lines.append(
                f"- {p}: {s.get('min'):.3f} / {s.get('mean'):.3f} / {s.get('max'):.3f}"
            )

    urls = [PRUVE_URL]

    return ToolResponse(
        tool_name=tool_name,
        message="\n".join(msg_lines),
        city=resolved_location or location,
        coordinates=ToolCoordinates(lat=float(lat), lon=float(lon)),
        artifacts=ToolArtifacts(maps=[map_spec], thumbnails=[], urls=urls),
        data={
            "request": request_params,
            "summary": summary,
            "series": series,
            "pruve_url": PRUVE_URL,
        },
        error=False,
    )

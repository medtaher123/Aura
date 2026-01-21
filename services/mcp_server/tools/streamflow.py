"""GEOGLOWS v2 Streamflow Forecast Tool.

Provides river discharge forecasts and flood risk analysis using the GEOGLOWS ECMWF
global streamflow forecasting system.
"""

from typing import Optional
from datetime import datetime
from functools import lru_cache
from mcp_singleton import mcp
import numpy as np
import s3fs
import xarray as xr


from utils.contracts import make_tool_response

from utils.bbox_service import LocationAmbiguousError, get_city_bbox
from utils.map_view_service import view_state_from_points

RETRO_RETURN_PERIODS_ZARR = "s3://geoglows-v2/retrospective/return-periods.zarr"
FORECASTS_BUCKET = "geoglows-v2-forecasts"


def _find_reach_for_river(lat: float, lon: float) -> Optional[int]:
    """Placeholder reach lookup by coordinates.

    The recommended GEOGLOWS method is to use river_id (COMID) directly.
    This function currently cannot resolve river_id from coordinates without
    loading the hydrography datasets, so it returns None.
    """
    return None


@lru_cache(maxsize=1)
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


@lru_cache(maxsize=1)
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
) -> dict:
    """
    Get streamflow forecast and flood risk for rivers using GEOGLOWS global hydrological model.

    Provide either:
    - `river_name`: Name of the river (e.g., "Seine", "Nile", "Amazon", "Thames")
    - `reach_id`: Specific GEOGLOWS river ID (COMID)

    Returns 15-day discharge forecast, flood risk level, and return period analysis.

    Examples:
    - streamflow_forecast_tool(river_name="Seine")
    - streamflow_forecast_tool(river_name="Nile River")
    - streamflow_forecast_tool(river_name="Amazon River, Brazil")
    - streamflow_forecast_tool(reach_id=12345678)
    """

    # Validate inputs
    if not river_name and not reach_id:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message="Please provide either 'river_name' (e.g., 'Seine', 'Nile') or 'reach_id' (GEOGLOWS river ID).",
            error=True,
        )

    lat = None
    lon = None
    river_display_name = None

    # Optional river name: used only to provide map coordinates
    if river_name:
        if not isinstance(river_name, str) or not river_name.strip():
            return make_tool_response(
                tool_name="streamflow_forecast_tool",
                message="River name must be a non-empty string.",
                error=True,
            )

        try:
            bbox, lat, lon, river_display_name = get_city_bbox(
                river_name.strip(), require_confirmation=True
            )
        except LocationAmbiguousError as e:
            candidates = e.candidates if isinstance(e.candidates, list) else []
            chosen = candidates[0] if candidates else {}
            river_display_name = str(
                chosen.get("display_name") or chosen.get("name") or river_name
            ).strip()
            lat = chosen.get("lat")
            lon = chosen.get("lon")
            bbox = chosen.get("bbox")

        if lat is not None and lon is not None:
            try:
                lat = float(lat)
                lon = float(lon)
            except (TypeError, ValueError):
                lat = None
                lon = None

    if reach_id is None:
        return make_tool_response(
            tool_name="streamflow_forecast_tool",
            message=(
                "Streamflow data access via the recommended S3 datasets requires a river_id (COMID). "
                "Please provide a river_id. You can find river numbers here: "
                "https://training.geoglows.org/rfs/accessing-data/find-river-numbers/"
            ),
            coordinates={"lat": lat, "lon": lon} if lat and lon else None,
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
        point_data = [
            {
                "lat": lat,
                "lon": lon,
                "river_id": reach_id,
                "discharge": peak_discharge,
                "risk": risk_level,
                "return_period": return_period,
            }
        ]

        view_state = view_state_from_points(
            [{"lat": lat, "lon": lon}],
            padding=0.1,
            min_zoom=8.0,
            max_zoom=12.0,
        )

        maps.append(
            {
                "view_state": view_state,
                "layers": [
                    {
                        "type": "ScatterplotLayer",
                        "data": point_data,
                        "get_position": "[lon, lat]",
                        "get_radius": 500,
                        "radius_units": "meters",
                        "radius_min_pixels": 8,
                        "radius_max_pixels": 30,
                        "get_fill_color": point_color,
                        "pickable": True,
                    }
                ],
                "tooltip": {
                    "html": "<b>River ID {river_id}</b><br/>Discharge: {discharge:.1f} m³/s<br/>Risk: {risk}<br/>Return Period: {return_period}",
                    "style": {"backgroundColor": "steelblue", "color": "white"},
                },
                "title": f"Streamflow Forecast - {river_desc}",
            }
        )

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
